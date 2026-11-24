# Decisões técnicas

## 1. O Home Assistant publica no MQTT, em vez de o servidor ler o HA
Os sensores já estavam no Home Assistant (HOBO via Shelly BLU, Zigbee, Daikin via Modbus). Em vez de o servidor consultar a API do HA, as automações publicam tópicos simples (`lab/<tipo>/<id>`) com JSON plano. O Telegraf só assina. Com isso o servidor não depende do modelo de entidades do HA, e trocar um sensor é mudar uma automação.

## 2. Republicar o estado a cada 10 min
Janelas, presença e ar só mudam de vez em quando. Se só a mudança fosse publicada, "sem dado" não distinguiria "nada mudou" de "sensor morto". Republicando a cada 10 min, a regra "30 min sem dado = problema" vale para todos os sensores, e o alerta de "fonte de dados parada" fica simples.

## 3. Portal de dados com padrão de exportação próprio
O CSV do Grafana não serve para pesquisa: formato diferente em cada painel, presença como "sim/não", fuso ambíguo. O portal entrega:
- CSV (UTF-8, vírgula, ponto decimal) ou Excel;
- horário ISO 8601, em Florianópolis ou UTC;
- resolução de 10 min, 1 h ou bruta. Nas agregadas, `data_hora` é o **início** do intervalo, e estados viram **fração do tempo** (0–1);
- tabela de **períodos** (início, fim, duração) para presença, janelas e ar. Interrupções de menos de 5 min são juntadas;
- Leia-me, dicionário de dados, `sensores.csv` e `datapackage.json` ([Frictionless Data](https://frictionlessdata.io/)).

O login é o mesmo do Grafana: o portal pergunta ao Grafana quem é o dono do cookie de sessão, sem segundo cadastro.

## 4. Gêmeo 3D: pré-processamento do modelo no build
O modelo BIM do laboratório tem 304 sólidos com superfícies NURBS (cadeiras, divisórias). No navegador, o web-ifc levava **~60 s** para transformá-los em triângulos e gerava **8,9 milhões** de triângulos (8,5 milhões só nas 36 cadeiras), o que tornava a página inutilizável.

Solução, em `portal-dados/app/static/cozinhar.mjs` (o mesmo código roda no Node e no navegador):
1. geometria repetida (as 36 cadeiras são a mesma) é lida uma vez só;
2. peças com mais de 1500 triângulos são simplificadas por agrupamento de vértices numa grade de 3 cm;
3. tudo o que não muda de cor vira uma malha por material: de 3.442 para ~250 chamadas de desenho;
4. o resultado vai para um binário compacto (`.bin.gz`), gerado numa etapa Node do `Dockerfile`.

Resultado: **~430 mil triângulos e carregamento em menos de 1 s**. A tela só é redesenhada quando algo muda, e o mouse só testa objetos com sensor.

O IFC continua sendo a fonte. Cada objeto é ligado ao sensor pelo **nome** (`Mesa 11`, `3A`, número de série do HOBO, `Daikin 1-04`). Trocar o modelo é substituir o arquivo e refazer o build.

## 5. Alertas com quem pode agir
Os alertas vão ao Slack da equipe, com o **lugar** do problema: "Daikin 1-02 (Salão, bancada B1)", "HOBO 20589761 (bancada B4)". Há também avisos de "voltou". A cobertura inclui sensor sem dado, gateway offline, servidor fora do ar, desperdício (ar ligado com janela aberta, sem ninguém embaixo ou fora do horário) e CO₂ alto.
