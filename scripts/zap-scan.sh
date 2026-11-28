#!/usr/bin/env bash
# OWASP ZAP against the staging stack: a passive baseline of the web app and
# an active scan of every API operation from its OpenAPI description.
#
#   docker compose -f docker-compose.prod.yml --env-file .env.staging up -d --build
#   bash scripts/zap-scan.sh
#
# Free: ZAP runs from its official image, nothing is installed or signed up
# for. Point it only at a stack you run yourself; the API scan sends attack
# payloads.
#
# ZAP's Java client sends no server name for a bare "localhost", and Caddy
# cannot pick a certificate without one, so for the scan Caddy is restarted
# under khazana.internal, which it certifies from its own local authority,
# and put back afterwards. Reports land in ./zap-report (git ignored).
#
# Exits non zero when either scan raises a warning not accepted in
# deploy/zap/*.tsv, where each accepted one carries its reason.

set -uo pipefail

ENV_FILE="${ENV_FILE:-.env.staging}"
OUT="${ZAP_OUT:-zap-report}"
IMAGE="zaproxy/zap-stable:2.17.0"
compose=(docker compose -f docker-compose.prod.yml --env-file "$ENV_FILE")

DOMAIN=khazana.internal "${compose[@]}" up -d caddy
ip=""
for _ in $(seq 1 30); do
  ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' khazana-prod-caddy-1 2>/dev/null)
  [ -n "$ip" ] && docker run --rm --network khazana-prod_default --add-host "khazana.internal:$ip" \
    curlimages/curl:8.17.0 -fsk -o /dev/null https://khazana.internal/api/health && break
  sleep 2
done

mkdir -p "$OUT"
chmod 777 "$OUT"
zap() {
  MSYS_NO_PATHCONV=1 docker run --rm --network khazana-prod_default \
    --add-host "khazana.internal:$ip" \
    -v "$(pwd)/$OUT:/zap/wrk:rw" -v "$(pwd)/deploy/zap:/zap/rules:ro" \
    "$IMAGE" "$@"
}

status=0
zap zap-baseline.py -t https://khazana.internal -m 3 -j \
  -c /zap/rules/baseline-rules.tsv -r baseline.html -J baseline.json || status=1
zap zap-api-scan.py -t https://khazana.internal/api/openapi.json -f openapi \
  -O https://khazana.internal/api \
  -c /zap/rules/api-rules.tsv -r api.html -J api.json || status=1

# Back to the normal address.
"${compose[@]}" up -d caddy

if [ "$status" -ne 0 ]; then
  echo "ZAP raised something not accepted in deploy/zap. Reports: $OUT/"
else
  echo "ZAP: nothing beyond the accepted findings. Reports: $OUT/"
fi
exit "$status"
