#!/usr/bin/env bash
# Backup diario do Gemeo Digital LabEEE (cron 3h): paineis do Grafana -> GitLab,
# volumes InfluxDB/Grafana/NPM -> ~/backups/<data>, copia do .env, mantem 7 dias.
set -uo pipefail
BASE=${BASE:-$HOME/gemeo-digital}; DEST=${DEST:-$HOME/backups}
HOJE=$(date +%F); D="$DEST/$HOJE"; MANTER_DIAS=7; ERRO=0
log() { echo "$(date '+%F %T') $*"; }
falha() { log "ERRO: $*"; ERRO=1; }
cd "$BASE" || exit 1
set -a; . ./.env; set +a
mkdir -p "$D" grafana/dashboards
log "=== Backup $HOJE ==="
G="http://localhost:3000/api"; A="Authorization: Bearer $GRAFANA_TOKEN"
UIDS=$(curl -sf -H "$A" "$G/search?type=dash-db&limit=5000" | jq -r '.[].uid') || falha "Grafana"
for u in $UIDS; do
  curl -sf -H "$A" "$G/dashboards/uid/$u" | jq '.dashboard|del(.id,.version)' > "grafana/dashboards/$u.json" || falha "painel $u"
done
log "Paineis exportados: $(echo $UIDS | wc -w)"
copia() { docker run --rm -v "$1":/v:ro -v "$D":/b alpine tar czf "/b/$1.tgz" -C /v . || falha "volume $1"; }
trap 'docker start influxdb_sensor_data >/dev/null 2>&1' EXIT
docker stop influxdb_sensor_data >/dev/null || falha "parar InfluxDB"
copia teste_influx_data; copia teste_influx_config
docker start influxdb_sensor_data >/dev/null || falha "InfluxDB nao voltou"
copia teste_grafana_data; copia teste_npm_data; copia teste_npm_letsencrypt
install -m 600 .env "$D/env"; cp -r docker-compose.yaml telegraf scripts "$D/" 2>/dev/null
git pull -q --rebase --autostash || falha "git pull"
git add grafana/dashboards
if ! git diff --cached --quiet -- grafana/dashboards; then
  git commit -q -m "Backup automatico: paineis do Grafana ($HOJE)" -- grafana/dashboards && git push -q || falha "git push"
fi
find "$DEST" -mindepth 1 -maxdepth 1 -type d -name '20*' -mtime +$MANTER_DIAS -exec rm -rf {} +
log "Backup de hoje: $(du -sh "$D" | cut -f1) | livre: $(df -h / | awk 'NR==2{print $4}')"
[ $ERRO -ne 0 ] && curl -s -X POST -H 'Content-Type: application/json' "$HA_WEBHOOK_URL" -d "{\"status\":\"firing\",\"title\":\"Backup do servidor falhou ($HOJE)\",\"alerts\":[{\"status\":\"firing\",\"annotations\":{\"summary\":\"Veja ~/backups/backup.log no servidor\"}}]}" >/dev/null
log "=== Fim (erro=$ERRO) ==="; exit $ERRO
