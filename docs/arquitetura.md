# Arquitetura

```mermaid
flowchart LR
  subgraph Lab["LabEEE (salão + salas)"]
    HOBO["20 HOBO MX1101/MX1102<br/>temp · umidade · CO₂"]
    ZB["Sensores Zigbee<br/>janelas e portas"]
    PC["36 PCs (ping)<br/>presença por mesa"]
    DK["9 Daikin<br/>Modbus (gateway D3-Net)"]
  end
  HOBO -- BLE --> SH["6 Shelly BLU Gateway"] --> HA
  ZB --> Z2M["Zigbee2MQTT"] --> MQTT
  PC --> HA
  DK --> HA
  HA["Home Assistant<br/>automações publicam a cada 10 min<br/>e a cada mudança"] --> MQTT["Broker MQTT"]
  HA -. alertas .-> SL["Slack"]
  subgraph Servidor["Servidor (Docker)"]
    TG["Telegraf<br/>6 entradas MQTT"] --> IX[("InfluxDB 2")]
    IX --> GF["Grafana<br/>9 painéis + alertas"]
    IX --> PT["Portal de dados (Flask)<br/>CSV/Excel padronizado"]
    IX --> G3["Gêmeo 3D<br/>three.js + web-ifc"]
  end
  MQTT --> TG
  GF -. webhook .-> HA
  PT -. login do Grafana .-> GF
```

## Caminho do dado

| Tópico MQTT | Quem publica | Medição no InfluxDB | Tag | Campos |
|---|---|---|---|---|
| `lab/hobo/<serie>` | automação HA | `ambiente` | serie | temp_c, ur_pct, co2_ppm |
| `lab/presenca/<mesa>` | automação HA | `presenca` | pc | presente (0/1) |
| `lab/janela/<NOME>` | automação HA | `janela` | nome | aberta, disponivel, bateria |
| `lab/daikin/<unidade>` | automação HA | `daikin` | unidade | ligado, setpoint, temp_retorno, modo, ventilador, filtro_sujo |
| `zigbee2mqtt/<nome>` | Zigbee2MQTT | `zigbee` | topic | contact, battery, linkquality |
| `zigbee2mqtt/<nome>/availability` | Zigbee2MQTT | `zigbee_disponibilidade` | topic | online/offline |

O Home Assistant republica o estado a cada 10 min, além de publicar a cada mudança. Assim, "sem dado há mais de 30 min" sempre significa sensor ou coleta com problema, e não só "nada mudou".

## Serviços

| Serviço | O que faz |
|---|---|
| InfluxDB 2.7 | Banco de séries temporais (org `LabEEE`, bucket `LabEEE`) |
| Telegraf | Assina os tópicos MQTT e grava no InfluxDB (`telegraf/telegraf.conf`) |
| Grafana 13 | Painéis (`grafana/dashboards/`), alerta "fonte de dados parada" |
| Portal de dados | Exportação padronizada e Gêmeo 3D (`portal-dados/`) |
| Backup | `scripts/backup.sh`, diário: painéis para o git, volumes e `.env` para disco, aviso se falhar |
