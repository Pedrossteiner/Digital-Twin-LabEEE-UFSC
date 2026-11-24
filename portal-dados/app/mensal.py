"""Gera, no começo de cada mês, o pacote do mês anterior (10 min, horário de Florianópolis, CSV + Excel).

Roda em laço dentro do container: confere a cada hora se falta algum mês desde PRIMEIRO_MES.
"""
import io
import logging
import os
import time
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import exportar as ex

PASTA = Path(os.environ.get("PASTA_MENSAL", "/dados_mensais"))
PRIMEIRO_MES = os.environ.get("PRIMEIRO_MES", "2026-11")  # primeiro mês com coleta completa
TZ = ZoneInfo("America/Sao_Paulo")
logging.basicConfig(level=logging.INFO, format="%(asctime)s mensal %(message)s")


def meses_pendentes(agora):
    a, m = map(int, PRIMEIRO_MES.split("-"))
    while (a, m) < (agora.year, agora.month):
        nome = f"labeee_mensal_{a:04d}-{m:02d}.zip"
        if not (PASTA / nome).exists():
            yield a, m, nome
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)


def gerar(a, m, nome):
    ini = datetime(a, m, 1, tzinfo=TZ)
    fim = datetime(a + 1, 1, 1, tzinfo=TZ) if m == 12 else datetime(a, m + 1, 1, tzinfo=TZ)
    fonte = ex.FonteInflux()
    conj = list(ex.CONJUNTOS)
    _, csv_zip = ex.pacote(fonte, ini, fim, conj, "10min", "local", "csv")
    _, xlsx_zip = ex.pacote(fonte, ini, fim, conj, "10min", "local", "xlsx")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for prefixo, dados in (("csv/", csv_zip), ("", xlsx_zip)):
            with zipfile.ZipFile(io.BytesIO(dados)) as src:
                for n in src.namelist():
                    if n == "LEIA-ME.txt":
                        continue
                    z.writestr(prefixo + n if n != "labeee_dados.xlsx" else f"labeee_{a:04d}-{m:02d}.xlsx", src.read(n))
        with zipfile.ZipFile(io.BytesIO(xlsx_zip)) as src:
            z.writestr("LEIA-ME.txt", src.read("LEIA-ME.txt"))
    tmp = PASTA / (nome + ".tmp")
    tmp.write_bytes(buf.getvalue())
    tmp.rename(PASTA / nome)
    logging.info("gerado %s (%.1f MB)", nome, len(buf.getvalue()) / 1e6)


def laco():
    PASTA.mkdir(parents=True, exist_ok=True)
    while True:
        for a, m, nome in meses_pendentes(datetime.now(TZ)):
            try:
                gerar(a, m, nome)
            except Exception:  # noqa: BLE001 — tenta de novo na próxima hora
                logging.exception("falha ao gerar %s", nome)
        time.sleep(3600)


if __name__ == "__main__":
    laco()
