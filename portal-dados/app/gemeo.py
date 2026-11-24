"""Estado atual de todos os sensores, para o Gêmeo 3D (última leitura de cada um)."""
from datetime import datetime, timedelta, timezone

import pandas as pd

# (medida, tag que identifica o sensor, campos numéricos, campos de texto)
MEDIDAS = {
    "hobo": ("ambiente", "serie", ["temp_c", "ur_pct", "co2_ppm"], []),
    "mesas": ("presenca", "pc", ["presente"], []),
    "janelas": ("janela", "nome", ["aberta", "disponivel", "bateria"], []),
    "daikin": ("daikin", "unidade", ["ligado", "setpoint", "temp_retorno"], ["modo"]),
}
JANELA_BUSCA = timedelta(hours=24)  # mais velho que isso aparece como "sem dado"


def _flux(bucket, ini, fim, medida, tag, campos, texto):
    filtro = " or ".join(f'r._field == "{c}"' for c in campos)
    conv = "string(v: r._value)" if texto else "float(v: r._value)"
    return f'''from(bucket: "{bucket}")
  |> range(start: {ini.strftime("%Y-%m-%dT%H:%M:%SZ")}, stop: {fim.strftime("%Y-%m-%dT%H:%M:%SZ")})
  |> filter(fn: (r) => r._measurement == "{medida}" and ({filtro}))
  |> last()
  |> map(fn: (r) => ({{_time: r._time, id: r.{tag}, campo: r._field, valor: {conv}}}))
  |> group()'''


def estado_atual(fonte, agora=None):
    agora = (agora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    ini, fim = agora - JANELA_BUSCA, agora + timedelta(minutes=1)
    saida = {"hora": agora.isoformat(timespec="seconds")}
    for chave, (medida, tag, num, txt) in MEDIDAS.items():
        partes = [fonte.consulta(_flux(fonte.bucket, ini, fim, medida, tag, num, False))]
        if txt:
            partes.append(fonte.consulta(_flux(fonte.bucket, ini, fim, medida, tag, txt, True)))
        df = pd.concat([p for p in partes if len(p)], ignore_index=True) if any(len(p) for p in partes) else None
        grupo = {}
        if df is not None:
            df = df.sort_values("_time").groupby(["id", "campo"], as_index=False).last()
            for sid, d in df.groupby("id"):
                sid = str(sid).replace("_", "-") if chave == "daikin" else str(sid)
                e = {}
                for _, r in d.iterrows():
                    v = r["valor"]
                    if isinstance(v, str):
                        try:
                            v = float(v) if r["campo"] not in txt else v
                        except ValueError:
                            pass
                    e[r["campo"]] = None if (isinstance(v, float) and pd.isna(v)) else v
                # idade = da leitura mais recente do sensor (o HA reenvia o estado a cada 10 min)
                e["idade_min"] = round((pd.Timestamp(agora) - d["_time"].max()).total_seconds() / 60, 1)
                if chave == "mesas":
                    e = {"ocupada": int(round(e.get("presente") or 0)), "idade_min": e["idade_min"]}
                grupo[sid] = e
        saida[chave] = grupo
    return saida
