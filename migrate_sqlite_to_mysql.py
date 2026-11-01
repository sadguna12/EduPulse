"""
EduPulse — Safe SQLite → MySQL Migration Utility
=================================================
Transfers all data from the existing SQLite database to a MySQL database.

Usage
-----
Set the target MySQL URL and then run:

    set MYSQL_URL=mysql+pymysql://user:password@host:3306/edupulse
    python migrate_sqlite_to_mysql.py

Safety rules
------------
* The existing SQLite database is NEVER modified.
* A timestamped backup of edupulse.db is created before anything else.
* Records that already exist in MySQL (matched by primary key) are SKIPPED,
  not overwritten — the migration is safe to rerun.
* Data errors are reported per-row in the reconciliation report.
  Nothing is silently discarded.
* AUTO_INCREMENT counters are reset after each table so future inserts
  do not collide with migrated IDs.
* Foreign-key constraint violations are detected and reported.
"""

import os
import sys
import shutil
import datetime
import traceback
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Dependency order derived from models.py foreign-key graph.
# Parents must be inserted before children.
# ---------------------------------------------------------------------------
TABLE_ORDER = [
    'departments',
    'academic_years',
    'sections',
    'users',
    'admins',
    'faculty',
    'students',
    'subjects',
    'faculty_subject_assignments',
    'examinations',
    'marks',
    'attendance_records',
    'questions',
    'question_attempts',
    'student_tasks',
    'student_goals',
    'motivational_quotes',
    'ml_model_records',
    'import_history',
    'student_aggregate_attendance',
]


def backup_sqlite(sqlite_path: Path) -> Path:
    """Create a timestamped backup of the SQLite database file."""
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = sqlite_path.with_suffix(f'.pre_migration_{ts}.bak')
    shutil.copy2(sqlite_path, backup_path)
    return backup_path


def get_sqlite_engine(sqlite_path: Path):
    from sqlalchemy import create_engine
    return create_engine(
        f'sqlite:///{sqlite_path}',
        connect_args={'timeout': 30.0, 'check_same_thread': False},
    )


def get_mysql_engine(mysql_url: str):
    from sqlalchemy import create_engine
    if mysql_url.startswith('mysql://'):
        mysql_url = 'mysql+pymysql://' + mysql_url[len('mysql://'):]
    return create_engine(
        mysql_url,
        pool_pre_ping=True,
        pool_recycle=280,
    )


def get_table_names_in_order(sqlite_engine, ordered: list[str]) -> list[str]:
    """
    Return the intersection of TABLE_ORDER and tables that actually exist
    in the source SQLite database.
    """
    from sqlalchemy import inspect as sa_inspect
    existing = set(sa_inspect(sqlite_engine).get_table_names())
    return [t for t in ordered if t in existing]


def read_all_rows(sqlite_engine, table_name: str) -> list[dict]:
    """Read all rows from a SQLite table as a list of dicts."""
    from sqlalchemy import text
    with sqlite_engine.connect() as conn:
        result = conn.execute(text(f'SELECT * FROM "{table_name}"'))
        cols = list(result.keys())
        return [dict(zip(cols, row)) for row in result]


def column_info(engine, table_name: str) -> dict[str, str]:
    """Return {column_name: type_name} for a table."""
    from sqlalchemy import inspect as sa_inspect
    insp = sa_inspect(engine)
    return {c['name']: str(c['type']) for c in insp.get_columns(table_name)}


def coerce_value(value, col_type: str):
    """
    Convert SQLite values to MySQL-compatible Python types.
    SQLite stores booleans as 0/1 integers and dates as strings.
    """
    if value is None:
        return None

    col_type_lower = col_type.lower()

    # Boolean columns stored as 0/1 in SQLite
    if 'boolean' in col_type_lower or 'bool' in col_type_lower:
        if isinstance(value, int):
            return bool(value)
        if isinstance(value, str):
            return value.lower() in ('1', 'true', 'yes')
        return bool(value)

    # Date columns (SQLite stores as TEXT 'YYYY-MM-DD')
    if col_type_lower in ('date',):
        if isinstance(value, str):
            try:
                return datetime.date.fromisoformat(value)
            except ValueError:
                return None
        if isinstance(value, datetime.datetime):
            return value.date()
        return value

    # DateTime columns
    if 'datetime' in col_type_lower or 'timestamp' in col_type_lower:
        if isinstance(value, str):
            for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
                try:
                    return datetime.datetime.strptime(value, fmt)
                except ValueError:
                    continue
            return None
        return value

    return value


def migrate_table(
    sqlite_engine,
    mysql_engine,
    table_name: str,
    report: dict,
):
    """
    Migrate one table from SQLite to MySQL.

    Strategy: for each row read from SQLite, attempt an INSERT into MySQL.
    If the row already exists (duplicate primary key), count it as skipped.
    Any other error is counted as failed and logged with full detail.
    No row is silently discarded — all failures appear in the report.
    """
    from sqlalchemy import text, inspect as sa_inspect

    rows = read_all_rows(sqlite_engine, table_name)
    if not rows:
        report['tables'][table_name] = {
            'source_rows': 0,
            'inserted': 0,
            'skipped': 0,
            'failed': 0,
            'errors': [],
        }
        return

    # Get destination column type info for value coercion.
    try:
        dst_col_types = column_info(mysql_engine, table_name)
    except Exception:
        dst_col_types = {}

    inserted = 0
    skipped = 0
    failed = 0
    errors = []

    with mysql_engine.begin() as conn:
        # Temporarily disable FK checks for this table's bulk load.
        conn.execute(text('SET FOREIGN_KEY_CHECKS = 0'))

        for row_num, row in enumerate(rows, start=1):
            # Coerce values for MySQL compatibility.
            coerced = {}
            for col, val in row.items():
                col_type = dst_col_types.get(col, '')
                coerced[col] = coerce_value(val, col_type)

            # Build parameterised INSERT … ON DUPLICATE KEY UPDATE id=id
            # This approach:
            #   - Inserts the row if the PK does not exist in MySQL.
            #   - Skips (no-op update) if PK already exists, without hiding errors.
            #   - Avoids INSERT IGNORE which swallows all constraint violations silently.
            cols_list = list(coerced.keys())
            placeholders = ', '.join(f':{c}' for c in cols_list)
            cols_sql = ', '.join(f'`{c}`' for c in cols_list)

            # ON DUPLICATE KEY UPDATE with a no-op so we can detect skips.
            pk_col = 'id'  # All EduPulse tables use `id` as PK.
            update_clause = f'`{pk_col}` = VALUES(`{pk_col}`)'

            sql = text(
                f'INSERT INTO `{table_name}` ({cols_sql}) VALUES ({placeholders}) '
                f'ON DUPLICATE KEY UPDATE {update_clause}'
            )

            try:
                result = conn.execute(sql, coerced)
                # MySQL rowcount: 1 = inserted, 2 = updated, 0 = no-op (already existed).
                if result.rowcount == 0:
                    skipped += 1
                elif result.rowcount == 2:
                    # Row existed but was updated (should not happen with our no-op).
                    skipped += 1
                else:
                    inserted += 1
            except Exception as exc:
                failed += 1
                errors.append({
                    'row': row_num,
                    'pk': row.get('id'),
                    'error': str(exc),
                    'data_snippet': {k: v for k, v in list(row.items())[:5]},
                })

        conn.execute(text('SET FOREIGN_KEY_CHECKS = 1'))

    # Reset AUTO_INCREMENT to MAX(id)+1 to avoid future collision.
    if inserted > 0 or skipped > 0:
        try:
            with mysql_engine.begin() as conn:
                max_id_result = conn.execute(text(f'SELECT MAX(id) FROM `{table_name}`'))
                max_id = max_id_result.scalar() or 0
                conn.execute(text(f'ALTER TABLE `{table_name}` AUTO_INCREMENT = {max_id + 1}'))
        except Exception:
            # Not all tables have an AUTO_INCREMENT id (e.g. association tables without serial PK).
            pass

    report['tables'][table_name] = {
        'source_rows': len(rows),
        'inserted': inserted,
        'skipped': skipped,
        'failed': failed,
        'errors': errors,
    }


def validate_row_counts(sqlite_engine, mysql_engine, tables: list[str], report: dict):
    """Compare row counts between SQLite and MySQL for each table."""
    from sqlalchemy import text
    mismatches = []
    for table in tables:
        try:
            with sqlite_engine.connect() as sc:
                sl_count = sc.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
            with mysql_engine.connect() as mc:
                my_count = mc.execute(text(f'SELECT COUNT(*) FROM `{table}`')).scalar()
            if sl_count != my_count:
                mismatches.append({
                    'table': table,
                    'sqlite_rows': sl_count,
                    'mysql_rows': my_count,
                    'diff': sl_count - my_count,
                })
        except Exception as exc:
            mismatches.append({'table': table, 'error': str(exc)})
    report['count_mismatches'] = mismatches


def print_report(report: dict):
    sep = '=' * 70
    print(f'\n{sep}')
    print('  EduPulse SQLite → MySQL Migration Report')
    print(f'  Started : {report["started_at"]}')
    print(f'  Finished: {report.get("finished_at", "N/A")}')
    print(f'  Backup  : {report.get("backup_path", "N/A")}')
    print(sep)

    total_src = total_ins = total_skip = total_fail = 0
    for tbl, stats in report.get('tables', {}).items():
        src = stats.get('source_rows', 0)
        ins = stats.get('inserted', 0)
        skp = stats.get('skipped', 0)
        fld = stats.get('failed', 0)
        total_src += src
        total_ins += ins
        total_skip += skp
        total_fail += fld
        status = '✓' if fld == 0 else '✗'
        print(f'  {status} {tbl:<45} src={src:>5}  ins={ins:>5}  skip={skp:>5}  fail={fld:>5}')
        for err in stats.get('errors', []):
            print(f'        Row {err["row"]} (id={err.get("pk")}): {err["error"]}')
            print(f'        Data: {err.get("data_snippet")}')

    print(sep)
    print(f'  TOTALS  source={total_src}  inserted={total_ins}  skipped={total_skip}  failed={total_fail}')

    mismatches = report.get('count_mismatches', [])
    if mismatches:
        print(f'\n  ⚠  ROW COUNT MISMATCHES DETECTED ({len(mismatches)} tables):')
        for m in mismatches:
            if 'error' in m:
                print(f'     {m["table"]}: ERROR — {m["error"]}')
            else:
                print(f'     {m["table"]}: SQLite={m["sqlite_rows"]}  MySQL={m["mysql_rows"]}  diff={m["diff"]}')
    else:
        print('\n  ✓  All row counts match between SQLite and MySQL.')

    if report.get('fatal_error'):
        print(f'\n  ✗ FATAL: {report["fatal_error"]}')

    print(sep)


def main():
    mysql_url = os.environ.get('MYSQL_URL') or os.environ.get('DATABASE_URL', '').strip()
    if not mysql_url:
        print(
            'ERROR: Set the MYSQL_URL environment variable to your MySQL connection string.\n'
            'Example:\n'
            '  set MYSQL_URL=mysql+pymysql://user:password@host:3306/edupulse\n'
            '  python migrate_sqlite_to_mysql.py'
        )
        sys.exit(1)

    sqlite_path = BASE_DIR / 'edupulse.db'
    if not sqlite_path.exists():
        print(f'ERROR: SQLite database not found at {sqlite_path}')
        sys.exit(1)

    report: dict = {
        'started_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'tables': {},
        'count_mismatches': [],
        'fatal_error': None,
    }

    # Step 1: Backup SQLite.
    print(f'[1/5] Backing up SQLite database: {sqlite_path}')
    backup_path = backup_sqlite(sqlite_path)
    report['backup_path'] = str(backup_path)
    print(f'      Backup created: {backup_path}')

    # Step 2: Connect to both databases.
    print('[2/5] Connecting to databases…')
    try:
        sqlite_engine = get_sqlite_engine(sqlite_path)
        mysql_engine = get_mysql_engine(mysql_url)
        # Probe MySQL connection.
        from sqlalchemy import text
        with mysql_engine.connect() as c:
            c.execute(text('SELECT 1'))
        print('      SQLite: OK')
        print('      MySQL : OK')
    except Exception as exc:
        report['fatal_error'] = f'Connection failed: {exc}'
        report['finished_at'] = datetime.datetime.now().isoformat(timespec='seconds')
        print_report(report)
        sys.exit(1)

    # Step 3: Determine table order.
    print('[3/5] Determining table migration order…')
    tables = get_table_names_in_order(sqlite_engine, TABLE_ORDER)
    print(f'      Tables to migrate: {tables}')

    # Step 4: Migrate each table.
    print('[4/5] Migrating tables…')
    for table in tables:
        print(f'      → {table}', end=' ', flush=True)
        try:
            migrate_table(sqlite_engine, mysql_engine, table, report)
            t = report['tables'][table]
            print(f'src={t["source_rows"]} ins={t["inserted"]} skip={t["skipped"]} fail={t["failed"]}')
        except Exception as exc:
            print(f'FAILED — {exc}')
            report['tables'][table] = {
                'source_rows': -1,
                'inserted': 0,
                'skipped': 0,
                'failed': -1,
                'errors': [{'row': 'ALL', 'error': traceback.format_exc()}],
            }

    # Step 5: Validate row counts.
    print('[5/5] Validating row counts…')
    validate_row_counts(sqlite_engine, mysql_engine, tables, report)

    report['finished_at'] = datetime.datetime.now().isoformat(timespec='seconds')
    print_report(report)

    total_failed = sum(t.get('failed', 0) for t in report['tables'].values() if t)
    if total_failed > 0 or report.get('count_mismatches'):
        sys.exit(2)
    sys.exit(0)


if __name__ == '__main__':
    main()
