"""Simulador da demo: grava no InfluxDB dados parecidos com os do LabEEE.

Na primeira vez preenche os últimos 7 dias; depois grava os dados novos a cada minuto.
Usa o mesmo gerador dos testes do portal (portal-dados/testes/simulado.py).
"""
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

sys.path.insert(0, "/sim")
from simulado import _gera  # noqa: E402

URL = os.environ.get("INFLUX_URL", "http://influxdb:8086")
ORG = os.environ.get("INFLUX_ORG", "LabEEE")
BUCKET = os.environ.get("INFLUX_BUCKET", "LabEEE")
TOKEN = os.environ["INFLUX_TOKEN"]
TAG = {"ambiente": "serie", "presenca": "pc", "janela": "nome", "daikin": "unidade"}


def linhas(dados, desde):
    for medida, rows in dados.items():
        for t, i, campo, v in rows:
            if t <= desde:
                continue
            valor = f'"{v}"' if isinstance(v, str) else repr(float(v))
            yield f"{medida},{TAG[medida]}={i} {campo}={valor} {int(t.value)}"


def grava(ls):
    for k in range(0, len(ls), 5000):
        r = requests.post(f"{URL}/api/v2/write", params={"org": ORG, "bucket": BUCKET, "precision": "ns"},
                          headers={"Authorization": f"Token {TOKEN}"}, data="\n".join(ls[k:k + 5000]), timeout=60)
        r.raise_for_status()


def espera_influx():
    for _ in range(60):
        try:
            if requests.get(f"{URL}/health", timeout=5).ok:
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    raise SystemExit("InfluxDB não respondeu")


if __name__ == "__main__":
    espera_influx()
    agora = pd.Timestamp(datetime.now(timezone.utc))
    ultimo = agora - pd.Timedelta(days=7)
    ls = list(linhas(_gera(ultimo, agora), ultimo))
    grava(ls)
    print(f"histórico simulado: {len(ls)} pontos (7 dias)", flush=True)
    ultimo = agora
    while True:
        time.sleep(60)
        agora = pd.Timestamp(datetime.now(timezone.utc))
        ls = list(linhas(_gera(ultimo - pd.Timedelta(minutes=10), agora), ultimo))
        grava(ls)
        ultimo = agora
