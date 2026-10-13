#!/usr/bin/env bash
# =============================================================================
# SerOps quick-start — Postgres backup
# =============================================================================
# Creates a timestamped compressed pg_dump of the serops DB.
# Rotation: keeps the last 7 backups, deletes older ones.
#
# Usage:
#     ./scripts/backup.sh                    # writes to ./backups/
#     ./scripts/backup.sh /var/backups/pg    # custom directory
#
# Runs against the container named ``serops-postgres`` (from
# docker-compose.yml). DB name + user are read from .env — the
# same file the compose stack itself uses. Falls back to the
# defaults baked into the compose (POSTGRES_DB=serops,
# POSTGRES_USER=serops) if .env doesn't set them.
#
# Cron example (2am daily):
#     0 2 * * * cd /path/to/quick-start && ./scripts/backup.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[SerOps]${NC} $*"; }
warn() { echo -e "${YELLOW}[SerOps]${NC} $*"; }

cd "$PROJECT_DIR"
if [ -f .env ]; then
    # Only load env we actually need; avoid `source .env` which
    # would spray every variable into our shell (some values may
    # contain characters that break `source`).
    POSTGRES_DB=$(grep -E '^POSTGRES_DB=' .env | cut -d= -f2- | tr -d '"' || true)
    POSTGRES_USER=$(grep -E '^POSTGRES_USER=' .env | cut -d= -f2- | tr -d '"' || true)
fi
POSTGRES_DB="${POSTGRES_DB:-serops}"
POSTGRES_USER="${POSTGRES_USER:-serops}"

BACKUP_DIR="${1:-${PROJECT_DIR}/backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/serops_db_${TIMESTAMP}.dump"

mkdir -p "$BACKUP_DIR"

log "Backing up database ${POSTGRES_DB} from serops-postgres → ${BACKUP_FILE}"
docker exec serops-postgres pg_dump \
    -U "${POSTGRES_USER}" \
    -d "${POSTGRES_DB}" \
    --format=custom \
    --compress=6 \
    > "${BACKUP_FILE}"

SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
log "Wrote ${BACKUP_FILE} (${SIZE})"

# Rotate — keep last 7
COUNT=$(find "$BACKUP_DIR" -maxdepth 1 -name 'serops_db_*.dump' -type f | wc -l)
if [ "$COUNT" -gt 7 ]; then
    log "Rotating old backups (keeping last 7 of $COUNT)"
    find "$BACKUP_DIR" -maxdepth 1 -name 'serops_db_*.dump' -type f \
        | sort | head -n -7 | xargs -r rm -f
fi

echo
echo "Restore with:"
echo "    docker exec -i serops-postgres pg_restore \\"
echo "        -U ${POSTGRES_USER} -d ${POSTGRES_DB} --clean --if-exists \\"
echo "        < ${BACKUP_FILE}"
