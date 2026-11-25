"""Safety tests for scripts/db_backup.sh and scripts/db_restore.sh.

Stub pg_dump, pg_restore, psql, date and docker commands are placed first on PATH,
so no database, Docker or network access is needed. Run with:

    python -m unittest discover -s scripts/tests -v
"""

import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKUP = REPO_ROOT / 'scripts' / 'db_backup.sh'
RESTORE = REPO_ROOT / 'scripts' / 'db_restore.sh'
PASSWORD = 'S3cret-test-password-9f2c'
STAMP = '20300615-120000'

STUBS = {
    # Records its arguments and whether the password arrived via the environment.
    'pg_dump': """
        printf '%s\\n' "$*" >> "$STUB_LOG/pg_dump.args"
        printf '%s\\n' "${PGPASSWORD-<unset>}" > "$STUB_LOG/pg_dump.pgpassword"
        printf '%s\\n' "${PGSSLMODE-<unset>}" > "$STUB_LOG/pg_dump.pgsslmode"
        printf 'PGDMP-fake-archive'
        exit "${FAKE_DUMP_EXIT:-0}"
    """,
    'pg_restore': """
        case " $* " in
          *" --list "*)
            [ "${FAKE_LIST_EXIT:-0}" = 0 ] || { echo 'pg_restore: error: bad archive' >&2; exit 1; }
            printf ';\\n;     dbname: %s\\n;\\n1; 0 0 TABLE DATA public tasks_task u\\n' "${FAKE_ARCHIVE_DB:-taskflow}"
            exit 0 ;;
        esac
        printf '%s\\n' "$*" >> "$STUB_LOG/pg_restore.args"
        [ "${FAKE_RESTORE_EXIT:-0}" = 0 ] || echo 'pg_restore: error: simulated failure' >&2
        exit "${FAKE_RESTORE_EXIT:-0}"
    """,
    'psql': """
        printf '%s\\n' "$*" >> "$STUB_LOG/psql.args"
        [ "${FAKE_PSQL_EXIT:-0}" = 0 ] || { echo 'psql: error: database does not exist' >&2; exit 2; }
        case "$*" in
          *taskflow:empty-check*) echo "${FAKE_OBJECTS:-0}" ;;
          *) echo '11 tables, 1 django_migrations table' ;;
        esac
    """,
    'date': """
        echo "${FAKE_STAMP}"
    """,
    # "docker compose -f FILE exec -T db CMD..." runs CMD locally as the container would.
    'docker': """
        printf '%s\\n' "$*" >> "$STUB_LOG/docker.args"
        shift 3; shift 3
        case "$1" in printenv) echo "${FAKE_LIVE_DB:-taskflow}"; exit 0 ;; esac
        POSTGRES_USER=container_admin exec "$@"
    """,
}


class ScriptTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.bin = self.tmp / 'bin'
        self.log = self.tmp / 'log'
        self.home = self.tmp / 'home'
        for d in (self.bin, self.log, self.home):
            d.mkdir()
        for name, body in STUBS.items():
            path = self.bin / name
            path.write_text('#!/bin/sh\n' + textwrap.dedent(body))
            path.chmod(0o755)
        self.env_file = self.tmp / 'app.env'
        self.env_file.write_text(textwrap.dedent(f"""\
            DJANGO_SECRET_KEY='not-used'
            POSTGRES_DB=taskflow
            POSTGRES_USER=taskflow_user
            POSTGRES_PASSWORD='{PASSWORD}'
            POSTGRES_HOST=127.0.0.1
            POSTGRES_PORT=5432
        """))
        self.backup_dir = self.home / 'taskflow-backups'

    def run_script(self, script, *args, **env):
        base = {
            'PATH': f'{self.bin}:/usr/bin:/bin',
            'HOME': str(self.home),
            'STUB_LOG': str(self.log),
            'FAKE_STAMP': STAMP,
        }
        base.update(env)
        result = subprocess.run(
            ['/bin/bash', str(script), *args],
            cwd=self.tmp, env=base, capture_output=True, text=True, timeout=30,
        )
        # No script output may ever contain the database password.
        self.assertNotIn(PASSWORD, result.stdout + result.stderr)
        return result

    def logged(self, name):
        path = self.log / name
        return path.read_text() if path.exists() else ''

    def make_backup_file(self, name='taskflow-local-x.dump'):
        path = self.tmp / name
        path.write_bytes(b'PGDMP-fake-archive')
        return path


class BackupScriptTests(ScriptTestCase):
    def backup(self, *args, **env):
        return self.run_script(BACKUP, '--env-file', str(self.env_file), *args, **env)

    def test_writes_private_timestamped_archive_and_checksum(self):
        result = self.backup()

        self.assertEqual(result.returncode, 0, result.stderr)
        dump = self.backup_dir / f'taskflow-local-{STAMP}.dump'
        self.assertEqual(dump.read_bytes(), b'PGDMP-fake-archive')
        self.assertEqual(stat.S_IMODE(dump.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.backup_dir.stat().st_mode), 0o700)
        checksum = Path(f'{dump}.sha256')
        self.assertEqual(stat.S_IMODE(checksum.stat().st_mode), 0o600)
        self.assertTrue(checksum.read_text().endswith(f'  {dump.name}\n'))
        # Only the finished files remain; no temporary files.
        self.assertEqual(sorted(p.name for p in self.backup_dir.iterdir()),
                         [dump.name, checksum.name])

    def test_uses_custom_format_and_passes_password_only_through_environment(self):
        self.backup()

        args = self.logged('pg_dump.args')
        self.assertIn('--format=custom', args)
        self.assertIn('--no-password', args)
        self.assertNotIn(PASSWORD, args)
        self.assertEqual(self.logged('pg_dump.pgpassword').strip(), PASSWORD)

    def test_passes_the_tls_mode_to_libpq_only_when_set(self):
        self.backup()
        self.assertEqual(self.logged('pg_dump.pgsslmode').strip(), '<unset>')

        self.backup('--label', 'neon', POSTGRES_SSLMODE='require')
        self.assertEqual(self.logged('pg_dump.pgsslmode').strip(), 'require')

    def test_never_overwrites_an_existing_backup(self):
        self.backup_dir.mkdir(mode=0o700)
        existing = self.backup_dir / f'taskflow-local-{STAMP}.dump'
        existing.write_bytes(b'precious')

        result = self.backup()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not overwriting', result.stderr)
        self.assertEqual(existing.read_bytes(), b'precious')
        self.assertEqual(self.logged('pg_dump.args'), '')

    def test_failed_dump_leaves_no_file(self):
        result = self.backup(FAKE_DUMP_EXIT='1')

        self.assertNotEqual(result.returncode, 0)
        self.assertIn('pg_dump failed', result.stderr)
        self.assertEqual(list(self.backup_dir.iterdir()), [])

    def test_unreadable_archive_leaves_no_file(self):
        result = self.backup(FAKE_LIST_EXIT='1')

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(self.backup_dir.iterdir()), [])

    def test_refuses_a_directory_inside_the_repository(self):
        target = REPO_ROOT / 'backups-should-not-be-created'

        result = self.backup('--dir', str(target))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn('inside the repository', result.stderr)
        self.assertFalse(target.exists())

    def test_compose_mode_dumps_inside_the_db_container(self):
        result = self.run_script(BACKUP, '--compose')

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.backup_dir / f'taskflow-docker-{STAMP}.dump').exists())
        self.assertIn('-U container_admin --format=custom --no-password taskflow',
                      self.logged('pg_dump.args'))


class RestoreScriptTests(ScriptTestCase):
    def restore(self, *args, **env):
        return self.run_script(RESTORE, '--env-file', str(self.env_file), *args, **env)

    def assertRefused(self, result, message):
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(message, result.stderr)
        self.assertEqual(self.logged('pg_restore.args'), '')

    def test_requires_an_explicit_target(self):
        self.assertRefused(self.restore(str(self.make_backup_file())), '--target DBNAME is required')

    def test_refuses_the_live_database(self):
        result = self.restore('--target', 'taskflow', str(self.make_backup_file()))
        self.assertRefused(result, 'live TaskFlow database')

    def test_refuses_the_database_the_backup_came_from(self):
        result = self.restore('--target', 'other_db', str(self.make_backup_file()),
                              FAKE_ARCHIVE_DB='other_db')
        self.assertRefused(result, 'backup was taken from a database with that name')

    def test_refuses_system_databases_and_unsafe_names(self):
        backup = str(self.make_backup_file())
        for name in ('postgres', 'template1'):
            self.assertRefused(self.restore('--target', name, backup), 'system database')
        for name in ('Bad-Name', 'x; DROP DATABASE taskflow', ''):
            result = self.restore('--target', name, backup)
            self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.logged('pg_restore.args'), '')

    def test_refuses_a_target_that_does_not_exist(self):
        result = self.restore('--target', 'restore_check', str(self.make_backup_file()),
                              FAKE_PSQL_EXIT='1')
        self.assertRefused(result, 'cannot connect to target database')

    def test_refuses_a_non_empty_target(self):
        result = self.restore('--target', 'restore_check', str(self.make_backup_file()),
                              FAKE_OBJECTS='53')
        self.assertRefused(result, 'is not empty (53 objects)')

    def test_refuses_a_file_that_fails_its_checksum(self):
        backup = self.make_backup_file()
        Path(f'{backup}.sha256').write_text(f'{"0" * 64}  {backup.name}\n')
        result = self.restore('--target', 'restore_check', str(backup))
        self.assertRefused(result, 'checksum mismatch')

    def test_refuses_an_invalid_archive(self):
        result = self.restore('--target', 'restore_check', str(self.make_backup_file()),
                              FAKE_LIST_EXIT='1')
        self.assertRefused(result, 'not a valid pg_dump custom-format archive')

    def test_restores_in_one_transaction_without_destructive_options(self):
        result = self.restore('--target', 'restore_check', str(self.make_backup_file()))

        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.logged('pg_restore.args')
        for option in ('--dbname=restore_check', '--single-transaction', '--exit-on-error',
                       '--no-owner', '--no-acl', '--no-password'):
            self.assertIn(option, args)
        for option in ('--clean', '--create', '-c ', '-C '):
            self.assertNotIn(option, args)
        self.assertIn('Restore complete', result.stdout)

    def test_reports_failure_when_pg_restore_fails(self):
        result = self.restore('--target', 'restore_check', str(self.make_backup_file()),
                              FAKE_RESTORE_EXIT='1')

        self.assertNotEqual(result.returncode, 0)
        self.assertIn('pg_restore failed', result.stderr)
        self.assertIn('rolled back', result.stderr)
        self.assertNotIn('Restore complete', result.stdout)

    def test_never_drops_or_creates_databases(self):
        self.restore('--target', 'restore_check', str(self.make_backup_file()))

        sql = self.logged('psql.args').upper()
        for statement in ('DROP ', 'CREATE DATABASE', 'TRUNCATE', 'DELETE '):
            self.assertNotIn(statement, sql)

    def test_compose_mode_refuses_the_container_live_database(self):
        result = self.run_script(RESTORE, '--compose', '--target', 'taskflow_live',
                                 str(self.make_backup_file()), FAKE_LIVE_DB='taskflow_live')
        self.assertRefused(result, "live TaskFlow database 'taskflow_live'")


if __name__ == '__main__':
    unittest.main()
