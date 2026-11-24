"""Portal de dados do LabEEE: página para baixar os dados, com o mesmo login do Grafana."""
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from flask import Flask, Response, abort, jsonify, render_template, request, send_file

import exportar as ex
import gemeo

app = Flask(__name__)
GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://grafana_dashboard:3000").rstrip("/")
GRAFANA_PUBLICO = os.environ.get("GRAFANA_PUBLICO", "http://localhost:3000").rstrip("/")
PASTA_MENSAL = Path(os.environ.get("PASTA_MENSAL", "/dados_mensais"))
MAX_DIAS = int(os.environ.get("MAX_DIAS", "366"))
MAX_DIAS_BRUTO = int(os.environ.get("MAX_DIAS_BRUTO", "92"))
FLORIPA = ZoneInfo("America/Sao_Paulo")
_cache = {}


# ---------------------------------------------------------------- login do Grafana
def usuario():
    """Pergunta ao Grafana quem é o dono do cookie de sessão. Sem sessão válida, devolve None."""
    cookie = request.headers.get("Cookie", "")
    if "grafana_session" not in cookie:
        return None
    agora = time.time()
    if cookie in _cache and agora - _cache[cookie][1] < 60:
        return _cache[cookie][0]
    try:
        r = requests.get(f"{GRAFANA_URL}/api/user", headers={"Cookie": cookie}, timeout=5)
    except requests.RequestException:
        return None
    u = r.json().get("login") if r.status_code == 200 else None
    _cache[cookie] = (u, agora)
    if len(_cache) > 500:
        _cache.clear()
    return u


def exige_login():
    u = usuario()
    if not u:
        abort(Response(render_template("login.html", grafana=GRAFANA_PUBLICO), status=401))
    return u


# ---------------------------------------------------------------- tempo vindo do Grafana
def tempo_grafana(txt, agora):
    """Aceita o que o Grafana manda no link: epoch em ms, 'now', 'now-7d', 'now/d', 'now-1M/M'..."""
    if not txt:
        return None
    if txt.isdigit():
        return datetime.fromtimestamp(int(txt) / 1000, FLORIPA)
    m = re.fullmatch(r"now(?:-(\d+)([smhdwMy]))?(?:/([dwMy]))?", txt)
    if not m:
        return None
    t = agora
    if m.group(1):
        n, u = int(m.group(1)), m.group(2)
        t -= {"s": timedelta(seconds=n), "m": timedelta(minutes=n), "h": timedelta(hours=n),
              "d": timedelta(days=n), "w": timedelta(weeks=n), "M": timedelta(days=30 * n),
              "y": timedelta(days=365 * n)}[u]
    return t


MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
         "outubro", "novembro", "dezembro"]


@app.template_filter("mes")
def nome_mes(arquivo):
    a, m = arquivo[14:21].split("-")
    return f"{MESES[int(m) - 1]}/{a}"


def mensais():
    if not PASTA_MENSAL.exists():
        return []
    return sorted([p.name for p in PASTA_MENSAL.glob("labeee_mensal_*.zip")], reverse=True)


# ---------------------------------------------------------------- páginas
@app.get("/")
def inicio():
    u = exige_login()
    agora = datetime.now(FLORIPA)
    t0 = tempo_grafana(request.args.get("from", ""), agora) or agora - timedelta(days=7)
    t1 = tempo_grafana(request.args.get("to", ""), agora) or agora
    return render_template("index.html", usuario=u, inicio=t0.strftime("%Y-%m-%d"), fim=t1.strftime("%Y-%m-%d"),
                           hoje=agora.strftime("%Y-%m-%d"), conjuntos=ex.CONJUNTOS, mensais=mensais(),
                           max_dias=MAX_DIAS, max_dias_bruto=MAX_DIAS_BRUTO, grafana=GRAFANA_PUBLICO)


@app.get("/baixar")
def baixar():
    exige_login()
    a = request.args
    try:
        fuso = a.get("fuso", "local")
        tz = ZoneInfo(ex.FUSOS[fuso][0])
        ini = datetime.strptime(a["inicio"], "%Y-%m-%d").replace(tzinfo=tz)
        fim = datetime.strptime(a["fim"], "%Y-%m-%d").replace(tzinfo=tz) + timedelta(days=1)  # o dia final entra
        resolucao = a.get("resolucao", "10min")
        formato = a.get("formato", "xlsx")
        conjuntos = [c for c in a.getlist("conjunto") if c in ex.CONJUNTOS]
        if resolucao not in ex.RESOLUCOES or formato not in ("xlsx", "csv"):
            raise ValueError("opção inválida")
    except (KeyError, ValueError):
        return erro("Confira as datas e as opções e tente de novo.")
    if not conjuntos:
        return erro("Marque pelo menos um tipo de dado.")
    dias = (fim - ini).days
    if dias <= 0:
        return erro("A data final tem que ser igual ou depois da inicial.")
    limite = MAX_DIAS_BRUTO if resolucao == "bruto" else MAX_DIAS
    if dias > limite:
        return erro(f"Para essa resolução o período máximo é de {limite} dias. Escolha um período menor "
                    f"ou baixe os pacotes mensais.")
    try:
        nome, dados = ex.pacote(ex.FonteInflux(), ini, fim, conjuntos, resolucao, fuso, formato)
    except ValueError as e:
        return erro(str(e))
    except requests.RequestException:
        app.logger.exception("falha ao consultar o InfluxDB")
        return erro("Não consegui ler o banco de dados agora. Tente de novo em alguns minutos.", 503)
    app.logger.info("download %s por %s", nome, usuario())
    return Response(dados, mimetype="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"'})


@app.get("/mensal/<nome>")
def baixar_mensal(nome):
    exige_login()
    if nome not in mensais():
        abort(404)
    return send_file(PASTA_MENSAL / nome, as_attachment=True, download_name=nome)


# ---------------------------------------------------------------- Gêmeo 3D
PASTA_MODELO = Path(os.environ.get("PASTA_MODELO", Path(__file__).parent / "modelo")).resolve()
_estado = {"t": 0, "dados": None}


@app.get("/gemeo3d")
def gemeo3d():
    exige_login()
    return render_template("gemeo3d.html", grafana=GRAFANA_PUBLICO, simulado=request.args.get("simulado") == "1")


@app.get("/gemeo3d/estado.json")
def gemeo3d_estado():
    exige_login()
    if time.time() - _estado["t"] > 4:  # todos os navegadores abertos dividem a mesma consulta
        try:
            _estado["dados"] = gemeo.estado_atual(ex.FonteInflux())
            _estado["t"] = time.time()
        except requests.RequestException:
            app.logger.exception("falha ao consultar o InfluxDB (gêmeo 3D)")
            if _estado["dados"] is None:
                return jsonify(erro="banco de dados indisponível"), 503
    return jsonify(_estado["dados"])


@app.get("/gemeo3d/<any('Labeee_gemeo.ifc', 'Labeee_gemeo.bin.gz'):nome>")
def gemeo3d_modelo(nome):
    """O .ifc é o modelo original; o .bin.gz é a versão leve gerada no build (cozinhar_modelo.mjs)."""
    exige_login()
    arq = PASTA_MODELO / nome
    if not arq.exists():
        abort(404)
    return send_file(arq, mimetype="application/octet-stream", max_age=3600)


@app.get("/saude")
def saude():
    return "ok"


def erro(msg, status=400):
    return render_template("erro.html", msg=msg), status
