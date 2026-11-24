"""Gera o pacote de dados do LabEEE (CSV ou Excel) a partir do InfluxDB.

Uso pela linha de comando (dentro do container):
    python exportar.py --inicio 2026-11-03 --fim 2026-11-10 --resolucao 10min --fuso local --formato xlsx
"""
import io
import json
import os
import zipfile
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

import metadados as md

FUSOS = {"local": ("America/Sao_Paulo", "Florianópolis (UTC−3)"), "utc": ("UTC", "UTC")}
RESOLUCOES = {"bruto": None, "10min": "10min", "1h": "1h"}
CONJUNTOS = {
    "ambiente": "Temperatura, umidade e CO₂ (HOBO)",
    "presenca": "Presença nas mesas",
    "janelas": "Janelas e portas do salão",
    "ar": "Ar-condicionado (Daikin)",
}
# Depois do último envio, por quanto tempo o estado (ocupada, aberta, ligado) é considerado válido.
# O Home Assistant reenvia tudo a cada 10 min; sem notícia por 30 min, o estado vira "desconhecido".
VALIDADE_ESTADO = pd.Timedelta(minutes=30)
# Nas tabelas de períodos, interrupções menores que isso (tomada/sensor perdendo a rede) são ignoradas.
JUNTAR_INTERRUPCOES = np.timedelta64(5, "m")
LIMITE_EXCEL = 1_048_575


# ---------------------------------------------------------------- leitura do InfluxDB
class FonteInflux:
    def __init__(self, url=None, org=None, bucket=None, token=None):
        self.url = (url or os.environ.get("INFLUX_URL", "http://influxdb:8086")).rstrip("/")
        self.org = org or os.environ.get("INFLUX_ORG", "LabEEE")
        self.bucket = bucket or os.environ.get("INFLUX_BUCKET", "LabEEE")
        self.token = token or os.environ.get("DADOS_INFLUX_TOKEN", "")

    def consulta(self, flux):
        r = requests.post(
            f"{self.url}/api/v2/query", params={"org": self.org},
            headers={"Authorization": f"Token {self.token}", "Accept": "application/csv",
                     "Content-Type": "application/json"},
            json={"query": flux, "dialect": {"annotations": [], "header": True}}, timeout=300)
        r.raise_for_status()
        blocos = [b for b in r.text.replace("\r\n", "\n").split("\n\n") if b.strip()]
        if not blocos:
            return pd.DataFrame(columns=["_time", "id", "campo", "valor"])
        df = pd.concat([pd.read_csv(io.StringIO(b), dtype={"id": str}) for b in blocos], ignore_index=True)
        df = df.drop(columns=[c for c in ("Unnamed: 0", "", "result", "table") if c in df.columns])
        df["_time"] = pd.to_datetime(df["_time"], utc=True, format="ISO8601")
        return df


def _flux(bucket, ini, fim, medida, campos, tag, texto=False):
    filtro = " or ".join(f'r._field == "{c}"' for c in campos)
    conv = "string(v: r._value)" if texto else "float(v: r._value)"
    return f'''from(bucket: "{bucket}")
  |> range(start: {ini.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, stop: {fim.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
  |> filter(fn: (r) => r._measurement == "{medida}" and ({filtro}))
  |> map(fn: (r) => ({{_time: r._time, id: r.{tag}, campo: r._field, valor: {conv}}}))
  |> group()
  |> sort(columns: ["_time"])'''


def ler(fonte, medida, campos, tag, ini, fim, texto=False):
    """Leituras em formato longo: _time (UTC), id, campo, valor. Pega 30 min antes do início
    para saber o estado de cada sensor no começo do período."""
    return fonte.consulta(_flux(fonte.bucket, ini - VALIDADE_ESTADO, fim, medida, campos, tag, texto))


# ---------------------------------------------------------------- estados (ocupada, aberta, ligado)
def segmentos(tempos, valores, fim_periodo):
    """Cada leitura vale até a próxima leitura (ou no máximo VALIDADE_ESTADO).
    Devolve arrays (inicio, fim, valor) com valor NaN = desconhecido."""
    t = np.asarray(tempos, dtype="datetime64[ns]")
    v = np.asarray(valores, dtype=float)
    if len(t) == 0:
        return t, t, v
    prox = np.append(t[1:], np.datetime64(fim_periodo.astimezone(timezone.utc).replace(tzinfo=None), "ns"))
    limite = t + np.timedelta64(int(VALIDADE_ESTADO.total_seconds()), "s")
    fim = np.minimum(prox, limite)
    return t, fim, v


def intervalos(ini_seg, fim_seg, val, p_ini, p_fim):
    """Junta trechos seguidos com valor 1 e corta no período pedido."""
    saida = []
    a = b = None
    for s, e, x in zip(ini_seg, fim_seg, val):
        if x == 1:
            if a is not None and s <= b:
                b = max(b, e)
            else:
                if a is not None:
                    saida.append((a, b))
                a, b = s, e
        else:
            if a is not None:
                saida.append((a, b))
                a = None
    if a is not None:
        saida.append((a, b))
    juntos = []
    for a, b in saida:
        if juntos and a - juntos[-1][1] < JUNTAR_INTERRUPCOES:
            juntos[-1] = (juntos[-1][0], max(juntos[-1][1], b))
        else:
            juntos.append((a, b))
    saida = juntos
    p0 =np.datetime64(p_ini.astimezone(timezone.utc).replace(tzinfo=None), "ns")
    p1 = np.datetime64(p_fim.astimezone(timezone.utc).replace(tzinfo=None), "ns")
    res = []
    for a, b in saida:
        a2, b2 = max(a, p0), min(b, p1)
        if b2 > a2:
            res.append((a2, b2, a < p0, b > p1))
    return res


def fracoes(ini_seg, fim_seg, val, bordas):
    """Fração de cada janela de tempo em que o valor foi 1, considerando só o tempo com estado conhecido.
    Se menos da metade da janela tem estado conhecido, devolve vazio."""
    bordas_ns = bordas.astype("datetime64[ns]").astype("int64").astype(float)
    if len(ini_seg) == 0:
        return np.full(len(bordas) - 1, np.nan)
    s = ini_seg.astype("datetime64[ns]").astype("int64").astype(float)
    e = fim_seg.astype("datetime64[ns]").astype("int64").astype(float)
    conhecido = ~np.isnan(val)
    um = (val == 1)

    def acumulado(mask):
        xs = np.empty(2 * len(s))
        ys = np.empty(2 * len(s))
        xs[0::2], xs[1::2] = s, e
        dur = np.where(mask, e - s, 0.0)
        cum = np.concatenate([[0.0], np.cumsum(dur)])
        ys[0::2], ys[1::2] = cum[:-1], cum[1:]
        ordem = np.argsort(xs, kind="stable")
        return np.interp(bordas_ns, xs[ordem], ys[ordem], left=0.0, right=cum[-1])

    occ = np.diff(acumulado(um & conhecido))
    con = np.diff(acumulado(conhecido))
    passo = np.diff(bordas_ns)
    with np.errstate(invalid="ignore", divide="ignore"):
        f = np.where(con >= 0.5 * passo, occ / con, np.nan)
    return np.round(f, 3)


# ---------------------------------------------------------------- utilidades de tempo
def _local(serie_utc, tz):
    return serie_utc.dt.tz_convert(tz).dt.tz_localize(None)


def _grade(ini, fim, passo, tz):
    g = pd.date_range(ini.astimezone(ZoneInfo(tz)), fim.astimezone(ZoneInfo(tz)), freq=passo, inclusive="left")
    return g


def _bordas_utc(grade, passo):
    return np.append(grade.tz_convert("UTC").tz_localize(None).values,
                     (grade[-1] + pd.Timedelta(passo)).tz_convert("UTC").tz_localize(None).to_datetime64()) \
        if len(grade) else np.array([], dtype="datetime64[ns]")


def _no_periodo(df, ini, fim):
    return df[(df["_time"] >= pd.Timestamp(ini)) & (df["_time"] < pd.Timestamp(fim))]


def _ordenar_ids(ids):
    def chave(x):
        s = str(x)
        num = "".join(ch for ch in s if ch.isdigit())
        return (int(num) if num else 10**9, s)
    return sorted(ids, key=chave)


# ---------------------------------------------------------------- conjuntos
def tabela_ambiente(fonte, ini, fim, resolucao, tz):
    df = ler(fonte, "ambiente", ["temp_c", "ur_pct", "co2_ppm"], "serie", ini, fim)
    df = _no_periodo(df, ini, fim)
    cols = ["data_hora", "sensor", "bancada", "temp_c", "ur_pct", "co2_ppm"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    larga = df.pivot_table(index=["_time", "id"], columns="campo", values="valor", aggfunc="mean").reset_index()
    for c in ("temp_c", "ur_pct", "co2_ppm"):
        if c not in larga:
            larga[c] = np.nan
    if resolucao == "bruto":
        out = larga.rename(columns={"id": "sensor"})
        out["data_hora"] = _local(out["_time"], tz)
    else:
        passo = RESOLUCOES[resolucao]
        grade = _grade(ini, fim, passo, tz)
        partes = []
        for sid, g in larga.groupby("id"):
            g = g.set_index(g["_time"].dt.tz_convert(tz))[["temp_c", "ur_pct", "co2_ppm"]]
            r = g.resample(passo, origin=grade[0] if len(grade) else "start_day").mean().reindex(grade)
            r["sensor"] = sid
            partes.append(r)
        out = pd.concat(partes)
        out.index.name = "data_hora"
        out = out.reset_index()
        out["data_hora"] = out["data_hora"].dt.tz_localize(None)
    out["bancada"] = out["sensor"].map(md.bancada_do_hobo)
    out["temp_c"] = out["temp_c"].round(2)
    out["ur_pct"] = out["ur_pct"].round(1)
    out["co2_ppm"] = out["co2_ppm"].round(0)
    ordem = {s: i for i, s in enumerate(_ordenar_ids(out["sensor"].unique()))}
    out = out.sort_values(["data_hora", "sensor"], key=lambda c: c.map(ordem) if c.name == "sensor" else c)
    return out[cols].reset_index(drop=True)


def _estado(df_estado, ini, fim, resolucao, tz, nome_id, nome_valor, nome_fracao, ids_fixos=None):
    """Monta (tabela por passo, tabela de períodos) para um estado 0/1 com 'desconhecido' = NaN."""
    ids = _ordenar_ids(set(df_estado["id"].unique()) | set(ids_fixos or []))
    periodos = []
    linhas = []
    passo = RESOLUCOES.get(resolucao)
    grade = _grade(ini, fim, passo, tz) if passo else None
    bordas = _bordas_utc(grade, passo) if passo else None
    for i in ids:
        g = df_estado[df_estado["id"] == i].sort_values("_time")
        t = g["_time"].dt.tz_convert("UTC").dt.tz_localize(None).values
        s, e, v = segmentos(t, g["valor"].values, fim)
        for a, b, cortado_ini, cortado_fim in intervalos(s, e, v, ini, fim):
            periodos.append({nome_id: i, "inicio": a, "fim": b,
                             "duracao_min": round((b - a) / np.timedelta64(1, "m"), 1),
                             "comecou_antes_do_periodo": bool(cortado_ini),
                             "continuou_depois_do_periodo": bool(cortado_fim)})
        if passo:
            f = fracoes(s, e, v, bordas)
            linhas.append(pd.DataFrame({"data_hora": grade.tz_localize(None), nome_id: i, nome_fracao: f}))
    per = pd.DataFrame(periodos, columns=[nome_id, "inicio", "fim", "duracao_min",
                                          "comecou_antes_do_periodo", "continuou_depois_do_periodo"])
    for c in ("inicio", "fim"):
        per[c] = pd.to_datetime(per[c]).dt.tz_localize("UTC").dt.tz_convert(tz).dt.tz_localize(None)
    per = per.sort_values(["inicio", nome_id]).reset_index(drop=True)
    if passo:
        tab = pd.concat(linhas, ignore_index=True) if linhas else pd.DataFrame(columns=["data_hora", nome_id, nome_fracao])
    else:
        tab = None
    return tab, per


def tabelas_presenca(fonte, ini, fim, resolucao, tz):
    df = ler(fonte, "presenca", ["presente"], "pc", ini, fim)
    mesas = [str(m) for b in md.BANCADAS.values() for m in b["mesas"]]
    tab, per = _estado(df, ini, fim, resolucao, tz, "mesa", "ocupada", "fracao_ocupada", mesas)
    if resolucao == "bruto":
        b = _no_periodo(df, ini, fim).rename(columns={"id": "mesa", "valor": "ocupada"})
        b["data_hora"] = _local(b["_time"], tz)
        b["ocupada"] = b["ocupada"].round().astype("Int64")
        tab = b[["data_hora", "mesa", "ocupada"]]
    tab = tab.copy()
    tab["mesa"] = tab["mesa"].astype(int)
    per["mesa"] = per["mesa"].astype(int)
    tab["bancada"] = tab["mesa"].map(md.bancada_da_mesa)
    per["bancada"] = per["mesa"].map(md.bancada_da_mesa)
    tab = tab[["data_hora", "mesa", "bancada"] + [c for c in tab.columns if c not in ("data_hora", "mesa", "bancada")]]
    per = per[["mesa", "bancada"] + [c for c in per.columns if c not in ("mesa", "bancada")]]
    return {"presenca": tab.reset_index(drop=True), "presenca_periodos": per}


def tabelas_janelas(fonte, ini, fim, resolucao, tz):
    df = ler(fonte, "janela", ["aberta", "disponivel", "bateria"], "nome", ini, fim)
    df = df[df["id"].isin(md.JANELAS_SALAO)]
    larga = df.pivot_table(index=["_time", "id"], columns="campo", values="valor", aggfunc="last").reset_index()
    for c in ("aberta", "disponivel", "bateria"):
        if c not in larga:
            larga[c] = np.nan
    est = larga[["_time", "id"]].copy()
    est["valor"] = np.where(larga["disponivel"] == 0, np.nan, larga["aberta"])
    tab, per = _estado(est, ini, fim, resolucao, tz, "janela", "aberta", "fracao_aberta", md.JANELAS_SALAO)
    if resolucao == "bruto":
        b = _no_periodo(larga, ini, fim).rename(columns={"id": "janela", "bateria": "bateria_pct"})
        b["data_hora"] = _local(b["_time"], tz)
        for c in ("aberta", "disponivel"):
            b[c] = b[c].round().astype("Int64")
        tab = b[["data_hora", "janela", "aberta", "disponivel", "bateria_pct"]]
    tab = tab.copy()
    tab["lado"] = tab["janela"].str[-1]
    per["lado"] = per["janela"].str[-1]
    tab = tab[["data_hora", "janela", "lado"] + [c for c in tab.columns if c not in ("data_hora", "janela", "lado")]]
    per = per[["janela", "lado"] + [c for c in per.columns if c not in ("janela", "lado")]]
    return {"janelas": tab.reset_index(drop=True), "janelas_periodos": per}


def tabelas_ar(fonte, ini, fim, resolucao, tz):
    num = ler(fonte, "daikin", ["ligado", "setpoint", "temp_retorno", "filtro_sujo"], "unidade", ini, fim)
    txt = ler(fonte, "daikin", ["modo", "ventilador"], "unidade", ini, fim, texto=True)
    for d in (num, txt):
        d["id"] = d["id"].astype(str).str.replace("_", "-")
    nomes = {"setpoint": "setpoint_c", "temp_retorno": "temp_retorno_c"}
    lig = num[num["campo"] == "ligado"][["_time", "id", "valor"]]
    tab, per = _estado(lig, ini, fim, resolucao, tz, "unidade", "ligado", "fracao_ligado", list(md.AR_LOCAL))
    larga_n = num.pivot_table(index=["_time", "id"], columns="campo", values="valor", aggfunc="last")
    larga_t = txt.pivot_table(index=["_time", "id"], columns="campo", values="valor", aggfunc="last") \
        if not txt.empty else pd.DataFrame()
    larga = larga_n.join(larga_t, how="outer").reset_index().rename(columns=nomes)
    for c in ("ligado", "setpoint_c", "temp_retorno_c", "filtro_sujo", "modo", "ventilador"):
        if c not in larga:
            larga[c] = np.nan
    if resolucao == "bruto":
        b = _no_periodo(larga, ini, fim).rename(columns={"id": "unidade"})
        b["data_hora"] = _local(b["_time"], tz)
        for c in ("ligado", "filtro_sujo"):
            b[c] = b[c].round().astype("Int64")
        b.loc[b["ligado"] == 0, "modo"] = "desligado"
        tab = b[["data_hora", "unidade", "ligado", "setpoint_c", "temp_retorno_c", "modo", "ventilador", "filtro_sujo"]]
    else:
        passo = RESOLUCOES[resolucao]
        grade = _grade(ini, fim, passo, tz)
        extras = []
        lim = max(1, int(VALIDADE_ESTADO / pd.Timedelta(passo)))
        for u, g in larga.groupby("id"):
            g = g.set_index(g["_time"].dt.tz_convert(tz))
            orig = grade[0] if len(grade) else "start_day"
            r = pd.DataFrame(index=grade)
            r["setpoint_c"] = g["setpoint_c"].resample(passo, origin=orig).last().reindex(grade.union(g.index).sort_values()) \
                .ffill(limit=lim).reindex(grade) if g["setpoint_c"].notna().any() else np.nan
            r["temp_retorno_c"] = g["temp_retorno_c"].resample(passo, origin=orig).mean().reindex(grade)
            for c in ("modo", "ventilador"):
                s = g[c].dropna()
                r[c] = s.resample(passo, origin=orig).last().reindex(grade).ffill(limit=lim) if len(s) else None
            r["filtro_sujo"] = g["filtro_sujo"].resample(passo, origin=orig).max().reindex(grade)
            r["unidade"] = u
            extras.append(r)
        ex = pd.concat(extras)
        ex.index = ex.index.tz_localize(None)
        ex.index.name = "data_hora"
        ex = ex.reset_index()
        tab = tab.merge(ex, on=["data_hora", "unidade"], how="left")
        tab["temp_retorno_c"] = tab["temp_retorno_c"].round(2)
        tab["filtro_sujo"] = tab["filtro_sujo"].round().astype("Int64")
        tab.loc[tab["fracao_ligado"] == 0, "modo"] = "desligado"
    tab = tab.copy()
    tab["local"] = tab["unidade"].map(md.AR_LOCAL)
    per["local"] = per["unidade"].map(md.AR_LOCAL)
    tab = tab[["data_hora", "unidade", "local"] + [c for c in tab.columns if c not in ("data_hora", "unidade", "local")]]
    per = per[["unidade", "local"] + [c for c in per.columns if c not in ("unidade", "local")]]
    return {"ar_condicionado": tab.reset_index(drop=True), "ar_condicionado_periodos": per}


# ---------------------------------------------------------------- textos
NOMES_ABAS = {
    "ambiente": "Ambiente", "presenca": "Presença", "presenca_periodos": "Presença - períodos",
    "janelas": "Janelas", "janelas_periodos": "Janelas - períodos",
    "ar_condicionado": "Ar-condicionado", "ar_condicionado_periodos": "Ar - períodos",
    "sensores": "Sensores",
}

DICIONARIO = {
    "data_hora": "Data e hora no fuso escolhido. Na versão por passo, é o INÍCIO do intervalo (10:00 = de 10:00 a 10:10).",
    "sensor": "Número de série do HOBO.",
    "bancada": "Bancada do salão (B1 a B5). Veja a aba/arquivo Sensores para as mesas de cada uma.",
    "temp_c": "Temperatura do ar (°C). Na versão por passo, média das leituras do intervalo.",
    "ur_pct": "Umidade relativa do ar (%).",
    "co2_ppm": "CO₂ (ppm). Só nos HOBO MX1102 (um por bancada).",
    "mesa": "Número da mesa (o PC da mesa tem uma tomada inteligente).",
    "ocupada": "1 = PC da mesa em execução, 0 = parado.",
    "fracao_ocupada": "Fração do intervalo com o PC em execução (0 a 1). Vazio = sem informação.",
    "janela": "Janela ou porta do salão (1A–12A no lado A, 1B–9B no lado B).",
    "lado": "Lado do salão (A ou B).",
    "aberta": "1 = aberta, 0 = fechada.",
    "fracao_aberta": "Fração do intervalo em que ficou aberta (0 a 1). Vazio = sensor fora do ar.",
    "disponivel": "1 = sensor respondendo, 0 = fora do ar (nesse caso 'aberta' não vale).",
    "bateria_pct": "Bateria do sensor (%).",
    "unidade": "Unidade interna Daikin (1-00 a 1-08).",
    "local": "Onde fica a unidade.",
    "ligado": "1 = ligado, 0 = desligado.",
    "fracao_ligado": "Fração do intervalo em que ficou ligado (0 a 1).",
    "setpoint_c": "Temperatura programada (°C).",
    "temp_retorno_c": "Temperatura do ar que volta para a unidade, medida por ela (°C).",
    "modo": "Modo de operação (cool = resfriar, heat = aquecer, fan_only = só ventilar, dry, auto…) ou 'desligado'.",
    "ventilador": "Velocidade do ventilador.",
    "filtro_sujo": "1 = a unidade pede limpeza do filtro.",
    "inicio": "Início do período (fuso escolhido).",
    "fim": "Fim do período (fuso escolhido).",
    "duracao_min": "Duração em minutos.",
    "comecou_antes_do_periodo": "VERDADEIRO = já estava assim antes do início do período baixado.",
    "continuou_depois_do_periodo": "VERDADEIRO = continuou assim depois do fim do período baixado.",
}


def texto_leiame(params, tabelas, gerado_em):
    tz_nome = FUSOS[params["fuso"]][1]
    res = {"bruto": "bruto (cada leitura como chegou)", "10min": "a cada 10 minutos", "1h": "a cada hora"}[params["resolucao"]]
    l = [
        "LabEEE — Gêmeo Digital — pacote de dados",
        "=" * 44,
        "",
        f"Período: {params['inicio_txt']} até {params['fim_txt']} (o fim não entra)",
        f"Horário: {tz_nome}",
        f"Resolução: {res}",
        f"Gerado em: {gerado_em}",
        "",
        "Tabelas",
        "-------",
    ]
    vazias = {"ar_condicionado_periodos": "nenhum ar ligado no período",
              "presenca_periodos": "nenhuma mesa ocupada no período",
              "janelas_periodos": "nenhuma janela aberta no período"}
    for nome, df in tabelas.items():
        extra = f" ({vazias.get(nome, 'sem dados no período')})" if len(df) == 0 else ""
        l.append(f"{NOMES_ABAS.get(nome, nome)}: {len(df)} linhas{extra}")
    l += [
        "",
        "Como os dados são coletados",
        "---------------------------",
        "Os sensores mandam os dados para o Home Assistant, que publica tudo no MQTT; o Telegraf grava no",
        "InfluxDB. Os HOBO mandam a cada ~10 min. Presença, janelas e ar-condicionado são enviados a cada",
        "10 min e sempre que mudam. Um estado (ocupada, aberta, ligado) vale até a próxima mensagem, por",
        "no máximo 30 min; depois disso fica desconhecido (célula vazia).",
        "",
        "Tabelas de 'períodos': cada linha é um trecho contínuo com a mesa ocupada, a janela aberta ou o",
        "ar ligado. Servem para responder 'quais mesas estavam ocupadas e quando'. Interrupções de",
        "menos de 5 min (tomada ou sensor perdendo a rede por instantes) não quebram o período.",
        "",
        "Células vazias = sem dado (sensor fora do ar ou sem leitura no intervalo). Nada foi inventado ou",
        "interpolado.",
        "",
        "Colunas",
        "-------",
    ]
    usadas = []
    for df in tabelas.values():
        for c in df.columns:
            if c not in usadas:
                usadas.append(c)
    for c in usadas:
        if c in DICIONARIO:
            l.append(f"{c}: {DICIONARIO[c]}")
    l += ["", "Sensores, mesas e bancadas: veja a tabela Sensores.",
          "Dúvidas: Pedro Santana Steiner e Leonardo Savi (equipe do Gêmeo Digital do LabEEE)."]
    return "\n".join(l)


EXEMPLO_PY = '''"""Exemplo: abrir o pacote de dados do LabEEE no Python (pandas)."""
import pandas as pd

amb = pd.read_csv("ambiente.csv", parse_dates=["data_hora"])
print(amb.head())

# Temperatura média de cada bancada, por hora
por_hora = (amb.set_index("data_hora")
               .groupby("bancada")["temp_c"]
               .resample("1h").mean()
               .unstack(0))
print(por_hora.head())

# Quanto tempo cada mesa ficou ocupada no período (horas)
try:
    per = pd.read_csv("presenca_periodos.csv", parse_dates=["inicio", "fim"])
    print((per.groupby("mesa")["duracao_min"].sum() / 60).sort_values(ascending=False))
except FileNotFoundError:
    pass
'''


def datapackage(params, tabelas):
    def tipo(s):
        if pd.api.types.is_bool_dtype(s):
            return "boolean"
        if pd.api.types.is_integer_dtype(s):
            return "integer"
        if pd.api.types.is_float_dtype(s):
            return "number"
        if pd.api.types.is_datetime64_any_dtype(s):
            return "datetime"
        return "string"
    recursos = []
    for nome, df in tabelas.items():
        recursos.append({
            "name": nome, "path": f"{nome}.csv", "profile": "tabular-data-resource",
            "dialect": {"delimiter": ",", "header": True}, "encoding": "utf-8",
            "schema": {"fields": [{"name": c, "type": tipo(df[c]), "description": DICIONARIO.get(c, "")}
                                  for c in df.columns]},
        })
    return {
        "profile": "tabular-data-package",
        "name": "labeee-gemeo-digital",
        "title": "LabEEE — Gêmeo Digital",
        "description": f"Dados do Living Lab do LabEEE/UFSC de {params['inicio_txt']} a {params['fim_txt']}, "
                       f"horário {FUSOS[params['fuso']][1]}, resolução {params['resolucao']}.",
        "resources": recursos,
    }


# ---------------------------------------------------------------- pacote
def montar(fonte, inicio, fim, conjuntos, resolucao="10min", fuso="local"):
    """inicio/fim: datetime com fuso. Devolve dict nome -> DataFrame."""
    tz = FUSOS[fuso][0]
    tab = {}
    if "ambiente" in conjuntos:
        tab["ambiente"] = tabela_ambiente(fonte, inicio, fim, resolucao, tz)
    if "presenca" in conjuntos:
        tab.update(tabelas_presenca(fonte, inicio, fim, resolucao, tz))
    if "janelas" in conjuntos:
        tab.update(tabelas_janelas(fonte, inicio, fim, resolucao, tz))
    if "ar" in conjuntos:
        tab.update(tabelas_ar(fonte, inicio, fim, resolucao, tz))
    tab["sensores"] = pd.DataFrame(md.tabela_sensores())
    return tab


def nome_arquivo(inicio, fim, resolucao, fuso, formato):
    f = (fim - timedelta(seconds=1)).strftime("%Y-%m-%d")
    return f"labeee_{inicio:%Y-%m-%d}_a_{f}_{resolucao}_{'florianopolis' if fuso == 'local' else 'utc'}_{formato}.zip"


def _csv(df):
    d = df.copy()
    for c in d.columns:
        if pd.api.types.is_datetime64_any_dtype(d[c]):
            d[c] = d[c].dt.strftime("%Y-%m-%d %H:%M:%S")
    return d.to_csv(index=False, lineterminator="\n").encode("utf-8")


def _xlsx(tabelas, leiame):
    from openpyxl.utils import get_column_letter
    for nome, df in tabelas.items():
        if len(df) > LIMITE_EXCEL:
            raise ValueError(f"A tabela {NOMES_ABAS.get(nome, nome)} tem {len(df):,} linhas, mais do que o Excel "
                             f"aguenta. Escolha um período menor, outra resolução ou o formato CSV.")
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame({"Leia-me": leiame.split("\n")}).to_excel(w, sheet_name="Leia-me", index=False)
        for nome, df in tabelas.items():
            aba = NOMES_ABAS.get(nome, nome)[:31]
            d = df.copy()
            for c in d.columns:
                if str(d[c].dtype) in ("Int64",):
                    d[c] = d[c].astype("float")
            d.to_excel(w, sheet_name=aba, index=False)
            ws = w.sheets[aba]
            ws.freeze_panes = "A2"
            for i, c in enumerate(d.columns, start=1):
                largura = max(len(str(c)), 10)
                if pd.api.types.is_datetime64_any_dtype(d[c]):
                    largura = 19
                    for cel in ws.iter_cols(min_col=i, max_col=i, min_row=2):
                        for x in cel:
                            x.number_format = "dd/mm/yyyy hh:mm"
                elif d[c].dtype == object and len(d):
                    largura = min(max(largura, int(d[c].astype(str).str.len().max() or 0)), 60)
                ws.column_dimensions[get_column_letter(i)].width = largura + 2
        w.sheets["Leia-me"].column_dimensions["A"].width = 110
    return buf.getvalue()


def gerar_zip(tabelas, params, formato):
    gerado = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d %H:%M (Florianópolis)")
    leiame = texto_leiame(params, tabelas, gerado)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("LEIA-ME.txt", leiame)
        if formato == "xlsx":
            z.writestr("labeee_dados.xlsx", _xlsx(tabelas, leiame))
        else:
            for nome, df in tabelas.items():
                z.writestr(f"{nome}.csv", _csv(df))
            z.writestr("datapackage.json", json.dumps(datapackage(params, tabelas), ensure_ascii=False, indent=2))
            z.writestr("exemplo_python.py", EXEMPLO_PY)
    return buf.getvalue()


def pacote(fonte, inicio, fim, conjuntos, resolucao, fuso, formato, agora=None):
    tz = FUSOS[fuso][0]
    # Não gera linhas no futuro: se o período inclui hoje, termina agora (arredondado para o passo).
    agora = agora or datetime.now(timezone.utc)
    if fim > agora:
        passo = pd.Timedelta(RESOLUCOES[resolucao] or "1min")
        fim = pd.Timestamp(agora).tz_convert(tz).floor(passo).to_pydatetime()
        if fim <= inicio:
            raise ValueError("O período escolhido ainda não começou.")
    tabelas = montar(fonte, inicio, fim, conjuntos, resolucao, fuso)
    params = {"inicio_txt": inicio.astimezone(ZoneInfo(tz)).strftime("%d/%m/%Y %H:%M"),
              "fim_txt": fim.astimezone(ZoneInfo(tz)).strftime("%d/%m/%Y %H:%M"),
              "fuso": fuso, "resolucao": resolucao}
    return nome_arquivo(inicio.astimezone(ZoneInfo(tz)), fim.astimezone(ZoneInfo(tz)), resolucao, fuso, formato), \
        gerar_zip(tabelas, params, formato)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Gera o pacote de dados do LabEEE")
    p.add_argument("--inicio", required=True, help="AAAA-MM-DD (fuso escolhido)")
    p.add_argument("--fim", required=True, help="AAAA-MM-DD, não incluso")
    p.add_argument("--conjuntos", default="ambiente,presenca,janelas,ar")
    p.add_argument("--resolucao", default="10min", choices=list(RESOLUCOES))
    p.add_argument("--fuso", default="local", choices=list(FUSOS))
    p.add_argument("--formato", default="csv", choices=["csv", "xlsx"])
    p.add_argument("--saida", default=".")
    a = p.parse_args()
    tz = ZoneInfo(FUSOS[a.fuso][0])
    ini = datetime.fromisoformat(a.inicio).replace(tzinfo=tz)
    fim = datetime.fromisoformat(a.fim).replace(tzinfo=tz)
    nome, dados = pacote(FonteInflux(), ini, fim, a.conjuntos.split(","), a.resolucao, a.fuso, a.formato)
    with open(os.path.join(a.saida, nome), "wb") as f:
        f.write(dados)
    print(nome, f"{len(dados) / 1e6:.1f} MB")
