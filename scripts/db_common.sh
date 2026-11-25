# Shared helpers for db_backup.sh and db_restore.sh. Sourced, not executed.
# Written for bash 3.2 (macOS default) and later.

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
COMPOSE_MODE=0
ENV_FILE="$REPO_ROOT/.env"

die() {
    echo "error: $*" >&2
    exit 1
}

info() {
    echo "$*"
}

# Print KEY's value from a dotenv file. The file is parsed, never sourced, so
# nothing in it is executed. Surrounding single or double quotes are removed.
dotenv_get() {
    local file=$1 key=$2 line value
    line=$(grep -E "^${key}=" "$file" 2>/dev/null | tail -n 1) || return 0
    value=${line#*=}
    case $value in
        \'*\') value=${value#\'}; value=${value%\'} ;;
        \"*\") value=${value#\"}; value=${value%\"} ;;
    esac
    printf '%s' "$value"
}

# Host mode: read POSTGRES_* from the environment, falling back to ENV_FILE (as
# Django does), and hand them to the PostgreSQL tools through libpq variables.
# The password goes only into PGPASSWORD for child processes; it is never
# printed or placed on a command line.
load_host_connection() {
    local name value
    for name in POSTGRES_HOST POSTGRES_PORT POSTGRES_USER POSTGRES_DB POSTGRES_PASSWORD POSTGRES_SSLMODE; do
        eval "value=\${$name:-}"
        if [ -z "$value" ] && [ -f "$ENV_FILE" ]; then
            value=$(dotenv_get "$ENV_FILE" "$name")
        fi
        eval "$name=\$value"
    done
    for name in POSTGRES_HOST POSTGRES_PORT POSTGRES_USER POSTGRES_DB; do
        eval "value=\$$name"
        [ -n "$value" ] || die "$name is not set (environment or $ENV_FILE)."
    done
    export PGHOST=$POSTGRES_HOST PGPORT=$POSTGRES_PORT PGUSER=$POSTGRES_USER
    if [ -n "$POSTGRES_PASSWORD" ]; then
        export PGPASSWORD=$POSTGRES_PASSWORD
    else
        unset PGPASSWORD  # fall back to ~/.pgpass
    fi
    unset POSTGRES_PASSWORD
    # Same TLS mode as Django (e.g. require for Neon).
    if [ -n "$POSTGRES_SSLMODE" ]; then export PGSSLMODE=$POSTGRES_SSLMODE; fi
    export PGCONNECT_TIMEOUT=${PGCONNECT_TIMEOUT:-10}
    LIVE_DB=$POSTGRES_DB
}

compose() {
    docker compose -f "$REPO_ROOT/compose.yaml" "$@"
}

# Compose mode: the tools run inside the db container as its own POSTGRES_USER
# over the local socket, so no credentials pass through the host.
load_compose_connection() {
    command -v docker >/dev/null 2>&1 || die "docker is not installed."
    LIVE_DB=$(compose exec -T db printenv POSTGRES_DB) \
        || die "cannot reach the db service. Start it with: docker compose up -d db"
    [ -n "$LIVE_DB" ] || die "POSTGRES_DB is not set in the db container."
}

load_connection() {
    if [ "$COMPOSE_MODE" = 1 ]; then
        load_compose_connection
    else
        load_host_connection
    fi
}

# Run a PostgreSQL client tool (pg_dump, pg_restore, psql) with the configured
# connection. Standard input and output pass through in both modes.
run_pg() {
    local tool=$1
    shift
    if [ "$COMPOSE_MODE" = 1 ]; then
        # shellcheck disable=SC2016  # expanded inside the container
        compose exec -T db sh -c 'tool=$1; shift; exec "$tool" -U "$POSTGRES_USER" "$@"' \
            sh "$tool" "$@"
    else
        command -v "$tool" >/dev/null 2>&1 \
            || die "$tool not found. Install the PostgreSQL client tools."
        "$tool" "$@"
    fi
}

# Run one SQL statement in DATABASE and print the unaligned result.
psql_query() {
    local database=$1 sql=$2
    run_pg psql -X -w -At -v ON_ERROR_STOP=1 -d "$database" -c "$sql"
}

# Print an archive's table of contents; fails if the file is not a valid archive.
archive_list() {
    local file=$1
    if [ "$COMPOSE_MODE" = 1 ]; then
        run_pg pg_restore --list <"$file"
    else
        run_pg pg_restore --list "$file"
    fi
}

sha256_of() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | cut -d ' ' -f 1
    else
        sha256sum "$1" | cut -d ' ' -f 1
    fi
}
