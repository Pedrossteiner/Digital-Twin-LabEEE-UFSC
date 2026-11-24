# Home Assistant

Configuração do Home Assistant usada pelo Gêmeo Digital. Os IDs do Slack, o webhook e os IPs foram trocados por marcadores (`SLACK_ID_PESSOA_1`, `TROQUE_POR_UM_ID_SECRETO`, `IP_DO_SERVIDOR`).

| Arquivo | Conteúdo |
|---|---|
| `automations.yaml` | Publicação no MQTT (HOBO, presença, janelas/portas, Daikin) e alertas no Slack |
| `templates.yaml` | Presença por mesa (PC respondendo) e médias usadas pelos alertas |
| `scripts.yaml` | Notificação de Daikin indisponível |
| `configuration_gemeo.yaml` | Sensores `rest` que verificam se Grafana e InfluxDB estão respondendo |

## Automações

**Publicação (a cada 10 min e a cada mudança):**
- Publicar HOBO no MQTT
- Publicar presença dos PCs no MQTT
- Publicar janelas e portas no MQTT
- Publicar Daikin no MQTT

**Alertas (Slack, via `notify.<seu_slack>`):**
- ar ligado com janela aberta (salão, 10 min)
- ar ligado sem ninguém embaixo, por zona da evaporadora (20 min)
- ar ligado fora do horário
- CO₂ acima de 1000 ppm (15 min)
- filtro do Daikin para limpar (toda segunda)
- HOBO sem dados há 30 min, com aviso de "voltou"
- gateway Shelly BLU offline
- servidor do Gêmeo Digital fora do ar (ping, Grafana e InfluxDB)
- janela/porta indisponível por 24 h
- Daikin indisponível (diz qual unidade e onde fica)
- alertas do Grafana repassados ao Slack (webhook)

Os nomes das entidades (`sensor.onset…`, `binary_sensor.<janela>_contact`, `sensor.daikin_1_0x_state`) são os do LabEEE. Em outro lugar, ajuste os nomes às suas integrações.
