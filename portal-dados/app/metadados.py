"""Cadastro fixo dos sensores do LabEEE usado nos pacotes de dados.

Quando um sensor mudar de lugar ou for trocado, atualize aqui.
"""

# Bancadas do salão: cada uma tem um gateway Shelly BLU, um HOBO MX1102 (CO2)
# e três MX1101 (temperatura/umidade). "zona_ar" é o ar-condicionado que atende a bancada.
BANCADAS = {
    "B1": {"mesas": [51, 52, 53, 54, 61, 62, 63, 64], "shelly": "shellyblu 1", "zona_ar": "1-02",
           "co2": "20590561", "temp": ["20589706", "20589709", "20589716"]},
    "B2": {"mesas": [31, 32, 33, 34, 41, 42, 43, 44], "shelly": "shellyblu 2", "zona_ar": "1-03",
           "co2": "20590559", "temp": ["20589722", "20589732", "20589744"]},
    "B3": {"mesas": [11, 12, 13, 14, 21, 22, 23, 24], "shelly": "shellyblu 3", "zona_ar": "1-04",
           "co2": "20590562", "temp": ["20589717", "20589733", "20589763"]},
    "B4": {"mesas": [15, 16, 17, 25, 26, 27], "shelly": "shellyblu 4", "zona_ar": "1-06",
           "co2": "20590564", "temp": ["20589702", "20589725", "20589761"]},
    "B5": {"mesas": [35, 36, 37, 45, 46, 47], "shelly": "shellyblu 5", "zona_ar": "1-05",
           "co2": "20590558", "temp": ["20589721", "20589729", "20589766"]},
}

AR_LOCAL = {
    "1-00": "Sala de reunião 1",
    "1-01": "Sala de reunião 2",
    "1-02": "Salão (bancada B1)",
    "1-03": "Salão (bancada B2)",
    "1-04": "Salão (bancada B3)",
    "1-05": "Salão (bancada B5)",
    "1-06": "Salão (bancada B4)",
    "1-07": "Sala da Ana Paula",
    "1-08": "Sala do Lamberts",
}

JANELAS_SALAO = [f"{i}A" for i in range(1, 13)] + [f"{i}B" for i in range(1, 10)]


def descricao_bancada(b):
    m = BANCADAS[b]["mesas"]
    linha1 = [x for x in m if x // 10 == m[0] // 10]
    linha2 = [x for x in m if x // 10 != m[0] // 10]
    return f"mesas {linha1[0]}–{linha1[-1]} e {linha2[0]}–{linha2[-1]}"


def bancada_da_mesa(mesa):
    for b, d in BANCADAS.items():
        if int(mesa) in d["mesas"]:
            return b
    return ""


def bancada_do_hobo(serie):
    for b, d in BANCADAS.items():
        if serie == d["co2"] or serie in d["temp"]:
            return b
    return ""


def modelo_do_hobo(serie):
    return "HOBO MX1102 (CO₂, temperatura, umidade)" if str(serie).startswith("20590") else \
        "HOBO MX1101 (temperatura, umidade)"


def tabela_sensores():
    """Uma linha por sensor/equipamento, para o arquivo sensores.csv / aba Sensores."""
    linhas = []
    for b, d in BANCADAS.items():
        for s in [d["co2"]] + d["temp"]:
            linhas.append({
                "tipo": "ambiente", "id": s, "modelo": modelo_do_hobo(s), "local": "Salão",
                "bancada": b, "descricao_bancada": descricao_bancada(b),
                "grandezas": "temp_c, ur_pct, co2_ppm" if s.startswith("20590") else "temp_c, ur_pct",
                "intervalo_envio": "~10 min",
            })
    for b, d in BANCADAS.items():
        for m in d["mesas"]:
            linhas.append({
                "tipo": "presenca", "id": f"mesa {m}", "modelo": "Tomada inteligente Sonoff (PC da mesa)",
                "local": "Salão", "bancada": b, "descricao_bancada": descricao_bancada(b),
                "grandezas": "ocupada (PC em execução)", "intervalo_envio": "10 min e a cada mudança",
            })
    for j in JANELAS_SALAO:
        linhas.append({
            "tipo": "janela", "id": j, "modelo": "Sensor de abertura Zigbee", "local": "Salão",
            "bancada": "", "descricao_bancada": f"lado {j[-1]}",
            "grandezas": "aberta, disponivel, bateria_pct", "intervalo_envio": "10 min e a cada mudança",
        })
    for u, local in AR_LOCAL.items():
        b = next((k for k, d in BANCADAS.items() if d["zona_ar"] == u), "")
        linhas.append({
            "tipo": "ar_condicionado", "id": f"Daikin {u}", "modelo": "Daikin VRV (rede DIII-Net)",
            "local": local, "bancada": b, "descricao_bancada": descricao_bancada(b) if b else "",
            "grandezas": "ligado, setpoint_c, temp_retorno_c, modo, ventilador, filtro_sujo",
            "intervalo_envio": "10 min e a cada mudança",
        })
    return linhas
