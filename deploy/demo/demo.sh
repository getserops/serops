#!/usr/bin/env bash
# SerOps local demo, one command:
#   deploy/demo/demo.sh          start it (first run: writes random secrets)
#   deploy/demo/demo.sh down     stop it and delete its data
# Needs Docker with the Compose plugin. Nothing leaves your machine: the
# example analyses are part of the seed and no AI provider is called.
set -euo pipefail

cd "$(dirname "$0")"
PORT="${SEROPS_DEMO_PORT:-8080}"

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker with the Compose plugin is required: https://docs.docker.com/compose/install/" >&2
  exit 1
fi

if [ "${1:-up}" = "down" ]; then
  docker compose down -v --remove-orphans
  exit 0
fi

# Random secrets, written once, readable only by you.
if [ ! -f .env ]; then
  rand() { head -c 48 /dev/urandom | base64 | tr -d '\n/+=' | cut -c1-48; }
  umask 077
  {
    echo "DJANGO_SECRET_KEY=$(rand)$(rand)"
    echo "SEROPS_ENCRYPTION_KEY=$(head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '\n')"
    echo "POSTGRES_PASSWORD=$(rand)"
    echo "REDIS_PASSWORD=$(rand)"
  } > .env
fi

start=$(date +%s)
echo "Starting SerOps (the first run downloads about 1 GB of images)..."
docker compose up -d --quiet-pull

printf "Waiting for the API"
for _ in $(seq 1 120); do
  if docker compose exec -T backend python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health/', timeout=5)" >/dev/null 2>&1; then
    break
  fi
  printf "."
  sleep 5
done
echo
if ! docker compose exec -T backend python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health/', timeout=5)" >/dev/null 2>&1; then
  echo "The API did not come up within 10 minutes. Logs: docker compose -f deploy/demo/docker-compose.yml logs backend" >&2
  exit 1
fi

echo "Loading the Acme Cloud example organisation..."
docker compose exec -T backend python manage.py seed_demo_org

elapsed=$(( $(date +%s) - start ))
cat <<EOF

SerOps demo ready in $((elapsed / 60)) min $((elapsed % 60)) s.

  Open http://localhost:${PORT} and click "Try the live demo".

  Read-only, example data. Stop and delete it: deploy/demo/demo.sh down
EOF
