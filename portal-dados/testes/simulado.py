"""Fonte de dados simulada que responde às mesmas consultas Flux do exportar.py."""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import metadados as md  # noqa: E402

RNG = np.random.default_rng(42)


def _gera(ini, fim):
    rows = []
    t0 = ini.floor("10min")
    tempos = pd.date_range(t0, fim, freq="10min", tz="UTC")
    # ambiente
    for b in md.BANCADAS.values():
        for s in [b["co2"]] + b["temp"]:
            off = RNG.integers(0, 600)
            for t in tempos:
                if RNG.random() < 0.03:
                    continue  # leitura perdida
                tt = t + pd.Timedelta(seconds=int(off + RNG.integers(-20, 20)))
                h = tt.tz_convert("America/Sao_Paulo").hour
                temp = 23 + 2 * np.sin((h - 9) / 24 * 2 * np.pi) + RNG.normal(0, .2)
                rows += [(tt, s, "temp_c", round(temp, 2)), (tt, s, "ur_pct", round(60 + RNG.normal(0, 2), 1))]
                if s.startswith("20590"):
                    rows.append((tt, s, "co2_ppm", float(int(450 + (300 if 9 <= h < 18 else 0) + RNG.normal(0, 20)))))
    # estados (presenca, janela, daikin): muda em horários aleatórios, publica a cada 10 min + mudança
    def estado(ids, medida, campo, prob_on):
        out = []
        for i in ids:
            v = 0
            for t in tempos:
                h = t.tz_convert("America/Sao_Paulo").hour
                p = prob_on if 8 <= h < 18 and t.tz_convert("America/Sao_Paulo").weekday() < 5 else 0.01
                if RNG.random() < 0.15:
                    nv = int(RNG.random() < p)
                    if nv != v:
                        tm = t + pd.Timedelta(seconds=int(RNG.integers(1, 590)))
                        v = nv
                        out.append((tm, i, campo, float(v)))
                out.append((t + pd.Timedelta(seconds=5), i, campo, float(v)))
        return out
    pres = estado([str(m) for b in md.BANCADAS.values() for m in b["mesas"]], "presenca", "presente", .6)
    jan = estado(md.JANELAS_SALAO, "janela", "aberta", .4)
    # janela 7B fora do ar numa parte do tempo
    jrows = []
    for (t, i, c, v) in jan:
        disp = 0.0 if i == "7B" and t.day % 3 == 0 else 1.0
        jrows += [(t, i, "aberta", v), (t, i, "disponivel", disp), (t, i, "bateria", 95.0)]
    ar = estado([u.replace("-", "_") for u in md.AR_LOCAL], "daikin", "ligado", .5)
    arrows = []
    for (t, i, c, v) in ar:
        arrows += [(t, i, "ligado", v), (t, i, "setpoint", 24.0), (t, i, "temp_retorno", round(25 + RNG.normal(0, .5), 2)),
                   (t, i, "filtro_sujo", 1.0 if i == "1_02" else 0.0), (t, i, "modo", "cool" if v else "off"),
                   (t, i, "ventilador", "low")]
    return {"ambiente": rows, "presenca": [(t, i, "presente", v) for (t, i, c, v) in pres],
            "janela": jrows, "daikin": arrows}


class FonteSimulada:
    bucket = "LabEEE"

    def __init__(self, ini, fim):
        self.dados = _gera(pd.Timestamp(ini).tz_convert("UTC") - pd.Timedelta(hours=1),
                           pd.Timestamp(fim).tz_convert("UTC"))
        self.consultas = []

    def consulta(self, flux):
        self.consultas.append(flux)
        start = pd.Timestamp(re.search(r"start: (\S+?),", flux).group(1))
        stop = pd.Timestamp(re.search(r"stop: (\S+?)\)", flux).group(1))
        medida = re.search(r'_measurement == "(\w+)"', flux).group(1)
        campos = re.findall(r'r._field == "(\w+)"', flux)
        texto = "string(v:" in flux
        rows = [r for r in self.dados[medida] if r[2] in campos and start <= r[0] < stop]
        df = pd.DataFrame(rows, columns=["_time", "id", "campo", "valor"])
        if not texto:
            df["valor"] = df["valor"].astype(float)
        return df.sort_values("_time").reset_index(drop=True)
