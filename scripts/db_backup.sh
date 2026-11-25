#!/usr/bin/env bash
# Back up TaskFlow's PostgreSQL database to a timestamped custom-format archive.
#
# Usage: scripts/db_backup.sh [--compose] [--env-file FILE] [--dir DIR] [--label LABEL]
#
#   (default)        Connect from this machine with POSTGRES_* from the environment
#                    or --env-file (default: .env in the repository).
#   --compose        Dump the Docker Compose db service from inside its container.
#   --dir DIR        Where to write backups (default: $TASKFLOW_BACKUP_DIR or
#                    ~/taskflow-backups). Must be outside the repository.
#   --label LABEL    Name part of the file (default: local, or docker with --compose).
#
# Writes taskflow-LABEL-YYYYMMDD-HHMMSS.dump (mode 600) plus a .sha256 checksum,
# never overwrites an existing file, and reads the database only.
set -euo pipefail

# shellcheck source=scripts/db_common.sh
. "$(dirname "${BASH_SOURCE[0]}")/db_common.sh"

usage() {
    sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

BACKUP_DIR=${TASKFLOW_BACKUP_DIR:-$HOME/taskflow-backups}
LABEL=

while [ $# -gt 0 ]; do
    case $1 in
        --compose) COMPOSE_MODE=1 ;;
        --env-file) [ $# -ge 2 ] || usage 2; ENV_FILE=$2; shift ;;
        --dir) [ $# -ge 2 ] || usage 2; BACKUP_DIR=$2; shift ;;
        --label) [ $# -ge 2 ] || usage 2; LABEL=$2; shift ;;
        -h|--help) usage 0 ;;
        *) echo "error: unknown argument: $1" >&2; usage 2 ;;
    esac
    shift
done

if [ -z "$LABEL" ]; then
    if [ "$COMPOSE_MODE" = 1 ]; then LABEL=docker; else LABEL=local; fi
fi
[[ $LABEL =~ ^[A-Za-z0-9_-]+$ ]] || die "label may contain only letters, digits, _ and -."

# Backups hold user data and password hashes: keep everything private to this user.
umask 077
# Never inside the repository, where a dump could be committed or copied into the
# Docker image. Checked before creating the directory, and again on the real path.
REPO_REAL=$(cd "$REPO_ROOT" && pwd -P)
inside_repo() {
    case "$1/" in "$REPO_ROOT/"*|"$REPO_REAL/"*) return 0 ;; esac
    return 1
}
case $BACKUP_DIR in /*) ;; *) BACKUP_DIR="$PWD/$BACKUP_DIR" ;; esac
! inside_repo "$BACKUP_DIR" || die "refusing to write backups inside the repository ($BACKUP_DIR)."
mkdir -p "$BACKUP_DIR"
BACKUP_DIR=$(cd "$BACKUP_DIR" && pwd -P)
! inside_repo "$BACKUP_DIR" || die "refusing to write backups inside the repository ($BACKUP_DIR)."
if [ -n "$(find "$BACKUP_DIR" -maxdepth 0 -perm -o=r 2>/dev/null)" ] \
    || [ -n "$(find "$BACKUP_DIR" -maxdepth 0 -perm -g=r 2>/dev/null)" ]; then
    echo "warning: $BACKUP_DIR is readable by other users; consider: chmod 700 '$BACKUP_DIR'" >&2
fi

load_connection

STAMP=$(date +%Y%m%d-%H%M%S)
FINAL="$BACKUP_DIR/taskflow-$LABEL-$STAMP.dump"
[ ! -e "$FINAL" ] || die "$FINAL already exists; not overwriting it."

# Dump into a private temporary file first, so a failed or interrupted dump never
# leaves a file that looks like a complete backup.
TMP=$(mktemp "$BACKUP_DIR/.taskflow-$LABEL-$STAMP.XXXXXX")
trap 'rm -f "$TMP" "$TMP.toc"' EXIT

info "Backing up database '$LIVE_DB' ($([ "$COMPOSE_MODE" = 1 ] && echo 'Compose db service' || echo "$PGHOST:$PGPORT as $PGUSER"))..."
run_pg pg_dump --format=custom --no-password "$LIVE_DB" >"$TMP" \
    || die "pg_dump failed; no backup was written."
[ -s "$TMP" ] || die "pg_dump produced an empty file; no backup was written."

archive_list "$TMP" >"$TMP.toc" || { die "the new archive is not readable by pg_restore; no backup was written."; }
TABLES=$(grep -c ' TABLE DATA ' "$TMP.toc" || true)
rm -f "$TMP.toc"

# A hard link fails if the name already exists, so this can never overwrite.
ln "$TMP" "$FINAL" || die "$FINAL already exists; not overwriting it."
rm -f "$TMP"
trap - EXIT

SUM=$(sha256_of "$FINAL")
( set -o noclobber; printf '%s  %s\n' "$SUM" "$(basename "$FINAL")" >"$FINAL.sha256" ) \
    || die "$FINAL.sha256 already exists; not overwriting it."

info "Backup written: $FINAL"
info "  size:        $(wc -c <"$FINAL" | tr -d ' ') bytes"
info "  tables:      $TABLES with data"
info "  sha256:      $SUM ($(basename "$FINAL").sha256)"
info "  permissions: $(ls -l "$FINAL" | cut -d ' ' -f 1)"
