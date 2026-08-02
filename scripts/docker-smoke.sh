#!/usr/bin/env bash
# Container smoke test for agent-html-drop (design §15.7).
#
# Requires docker. Builds the image, runs it, and probes:
#   - GET /api/health  -> 200 {"status":"ok"}
#   - GET /files/<name> -> 200 + body (daemon serves /files/* itself)
#   - token bootstrap   -> 64-hex token retrievable in-container
#
# Run: bash scripts/docker-smoke.sh
set -euo pipefail

IMG=ahd-smoke:latest
HOST_PORT=18765
CID=ahd-smoke
DATA_DIR="$(mktemp -d)"
trap 'docker rm -f "$CID" >/dev/null 2>&1 || true; rm -rf "$DATA_DIR"' EXIT

echo ">> building image"
docker build -q -t "$IMG" .

echo ">> running container (root, to side-step bind-mount uid in a throwaway test)"
docker run -d --name "$CID" \
  --user root \
  -p "127.0.0.1:${HOST_PORT}:8765" \
  -e "PUBLIC_BASE_URL=http://localhost:${HOST_PORT}" \
  -v "${DATA_DIR}:/data" \
  "$IMG" >/dev/null

echo ">> waiting for /api/health"
for _ in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:${HOST_PORT}/api/health" >/dev/null 2>&1; then break; fi
  sleep 0.5
done
curl -sf "http://127.0.0.1:${HOST_PORT}/api/health" | grep -q '"status":"ok"'
echo "   health OK"

echo ">> probing daemon-served /files/<name>"
mkdir -p "${DATA_DIR}/docroot"
printf '<html><body>smoke</body></html>' > "${DATA_DIR}/docroot/smoke.html"
curl -sf "http://127.0.0.1:${HOST_PORT}/files/smoke.html" | grep -q 'smoke'
echo "   /files/smoke.html OK"

echo ">> token bootstrap"
docker exec "$CID" agent-html-drop token show | grep -Eq '^[0-9a-f]{64}$'
echo "   token OK"

echo "SMOKE OK"
