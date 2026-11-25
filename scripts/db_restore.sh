#!/usr/bin/env bash
# Restore a TaskFlow backup into an existing, EMPTY, non-live database.
#
# Usage: scripts/db_restore.sh --target DBNAME [--compose] [--env-file FILE] BACKUP.dump
#
#   --target DBNAME  Required. The database to restore into. It must already exist,
#                    contain no objects, and differ from the live TaskFlow database.
#   --compose        Restore into the Docker Compose db service, from inside it.
#   --env-file FILE  Connection settings for host mode (default: .env).
#
# This script never creates or drops databases and never uses --clean or --create.
# The restore runs in a single transaction and stops at the first error, so a failed
# restore leaves the target database as empty as it was.
set -euo pipefail

# shellcheck source=scripts/db_common.sh
. "$(dirname "${BASH_SOURCE[0]}")/db_common.sh"

usage() {
    sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

TARGET=
BACKUP=

while [ $# -gt 0 ]; do
    case $1 in
        --target) [ $# -ge 2 ] || usage 2; TARGET=$2; shift ;;
        --compose) COMPOSE_MODE=1 ;;
        --env-file) [ $# -ge 2 ] || usage 2; ENV_FILE=$2; shift ;;
        -h|--help) usage 0 ;;
        -*) echo "error: unknown option: $1" >&2; usage 2 ;;
        *) [ -z "$BACKUP" ] || usage 2; BACKUP=$1 ;;
    esac
    shift
done

[ -n "$TARGET" ] || die "--target DBNAME is required; the target database is never guessed."
[ -n "$BACKUP" ] || die "the backup file argument is required."

# Plain lowercase identifiers only, so the name never needs quoting.
[[ $TARGET =~ ^[a-z_][a-z0-9_]{0,62}$ ]] \
    || die "target name must be lowercase letters, digits and _ (max 63), starting with a letter or _."
case $TARGET in
    postgres|template0|template1) die "refusing to restore into the system database '$TARGET'." ;;
esac

[ -f "$BACKUP" ] && [ -r "$BACKUP" ] || die "backup file not found or not readable: $BACKUP"

# Integrity: compare with the checksum written by db_backup.sh, when present.
if [ -f "$BACKUP.sha256" ]; then
    expected=$(cut -d ' ' -f 1 <"$BACKUP.sha256")
    [ "$(sha256_of "$BACKUP")" = "$expected" ] \
        || die "checksum mismatch for $BACKUP; the file may be damaged. Not restoring."
    info "Checksum OK ($BACKUP.sha256)."
else
    echo "warning: no $BACKUP.sha256 checksum file; skipping the checksum check." >&2
fi

load_connection

# Refuse the live database, by the configured name and by the name recorded in
# the archive (so a backup is never restored over the database it came from).
[ "$TARGET" != "$LIVE_DB" ] \
    || die "refusing to restore into the live TaskFlow database '$LIVE_DB'. Use a separate, empty database."

TOC=$(archive_list "$BACKUP") || die "$BACKUP is not a valid pg_dump custom-format archive."
SOURCE_DB=$(printf '%s\n' "$TOC" | sed -n 's/^;[[:space:]]*dbname: //p' | head -n 1)
[ "$TARGET" != "$SOURCE_DB" ] \
    || die "refusing to restore into '$TARGET': the backup was taken from a database with that name."

# The target must exist and be empty (no tables, sequences, views, functions,
# types, extra schemas or extensions).
OBJECTS=$(psql_query "$TARGET" "/* taskflow:empty-check */
    SELECT
      (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
          AND n.nspname NOT LIKE 'pg\\_toast%' AND n.nspname NOT LIKE 'pg\\_temp%')
    + (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname NOT IN ('pg_catalog', 'information_schema'))
    + (SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
          AND t.typtype IN ('d', 'e', 'r', 'm'))
    + (SELECT count(*) FROM pg_namespace
        WHERE nspname NOT IN ('public', 'pg_catalog', 'information_schema')
          AND nspname NOT LIKE 'pg\\_toast%' AND nspname NOT LIKE 'pg\\_temp%')
    + (SELECT count(*) FROM pg_extension WHERE extname <> 'plpgsql')") \
    || die "cannot connect to target database '$TARGET'. Create it first (see README, 'Backup and Restore')."
[[ $OBJECTS =~ ^[0-9]+$ ]] || die "unexpected answer while checking that '$TARGET' is empty."
[ "$OBJECTS" -eq 0 ] \
    || die "target database '$TARGET' is not empty ($OBJECTS objects). Restore only into an empty database."

info "Restoring $BACKUP (from database '${SOURCE_DB:-unknown}') into empty database '$TARGET'..."

# --single-transaction: all or nothing.  --exit-on-error: stop at the first error.
# --no-owner/--no-acl: objects belong to the restoring role, and roles or grants
# from the source server are not required on this one.
RESTORE_ARGS=(--dbname="$TARGET" --single-transaction --exit-on-error --no-owner --no-acl --no-password)
if [ "$COMPOSE_MODE" = 1 ]; then
    run_pg pg_restore "${RESTORE_ARGS[@]}" <"$BACKUP" && status=0 || status=$?
else
    run_pg pg_restore "${RESTORE_ARGS[@]}" "$BACKUP" && status=0 || status=$?
fi
if [ "$status" -ne 0 ]; then
    die "pg_restore failed (exit $status). The single transaction was rolled back, so nothing was restored into '$TARGET'."
fi

SUMMARY=$(psql_query "$TARGET" "/* taskflow:summary */
    SELECT (SELECT count(*) FROM information_schema.tables
             WHERE table_schema = 'public' AND table_type = 'BASE TABLE')
        || ' tables, '
        || (SELECT count(*) FROM pg_class WHERE relname = 'django_migrations' AND relkind = 'r')
        || ' django_migrations table'") \
    || die "restore finished but '$TARGET' could not be queried afterwards."
info "Restore complete: $SUMMARY in '$TARGET'."
info "Verify it before relying on it (see README, 'Verifying a restore')."
