"""Sobe o portal localmente com dados simulados e um 'Grafana' falso que aceita o cookie grafana_session=ok."""
import sys, threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from flask import Flask, request, jsonify
import exportar as ex
from simulado import FonteSimulada

g = Flask("grafana")
@g.get("/api/user")
def user():
    return (jsonify(login="pedro"), 200) if "grafana_session=ok" in request.headers.get("Cookie", "") else ("", 401)
threading.Thread(target=lambda: g.run(port=3999), daemon=True).start()

import os
os.environ["GRAFANA_URL"] = "http://127.0.0.1:3999"
os.environ["PASTA_MENSAL"] = sys.argv[1]
tz = ZoneInfo("America/Sao_Paulo")
fonte = FonteSimulada(datetime(2026, 10, 1, tzinfo=tz), datetime(2026, 11, 11, tzinfo=tz))
ex.FonteInflux = lambda *a, **k: fonte
import web
web.app.run(port=8099)
