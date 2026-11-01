"""
EduPulse — MySQL Schema Initialisation Script
==============================================
Creates all database tables in a fresh (empty) MySQL database
using the existing SQLAlchemy models. Does NOT seed demo data,
reset existing tables, or alter any existing data.

Usage
-----
    set DATABASE_URL=mysql+pymysql://user:password@host:3306/edupulse
    set FLASK_ENV=production
    python init_db.py

Or for a one-off schema check without touching production data:
    set DATABASE_URL=mysql+pymysql://user:password@host:3306/edupulse_test
    python init_db.py
"""

import os
import sys


def main():
    db_url = os.environ.get('DATABASE_URL', '').strip()
    if not db_url:
        print(
            'ERROR: DATABASE_URL is not set.\n'
            'Set it to your MySQL connection string before running this script.\n'
            'Example:\n'
            '  set DATABASE_URL=mysql+pymysql://user:password@host:3306/edupulse\n'
            '  python init_db.py'
        )
        sys.exit(1)

    # Normalise mysql:// → mysql+pymysql://
    if db_url.startswith('mysql://'):
        db_url = 'mysql+pymysql://' + db_url[len('mysql://'):]
        os.environ['DATABASE_URL'] = db_url

    flask_env = os.environ.get('FLASK_ENV', 'production')
    print(f'EduPulse — Initialising MySQL schema')
    print(f'  Database : {_mask_password(db_url)}')
    print(f'  FLASK_ENV: {flask_env}')
    print()

    try:
        from app import create_app
        from extensions import db

        app = create_app(flask_env)

        with app.app_context():
            # Test connectivity first.
            from sqlalchemy import text
            with db.engine.connect() as conn:
                conn.execute(text('SELECT 1'))
            print('  ✓ Connected to MySQL successfully.')

            # create_all() is safe: it only creates tables that do not already exist.
            # It does NOT drop or alter existing tables.
            db.create_all()
            print('  ✓ Schema created (existing tables untouched).')

            # Report tables created.
            from sqlalchemy import inspect as sa_inspect
            tables = sa_inspect(db.engine).get_table_names()
            print(f'\n  Tables present in database ({len(tables)}):')
            for t in sorted(tables):
                print(f'    - {t}')

        print('\n  ✓ init_db.py completed successfully.')
        print('  Next step: run migrate_sqlite_to_mysql.py to copy existing data.')

    except RuntimeError as exc:
        print(f'\n  ✗ Configuration error: {exc}')
        sys.exit(1)
    except Exception as exc:
        import traceback
        print(f'\n  ✗ Fatal error: {exc}')
        traceback.print_exc()
        sys.exit(1)


def _mask_password(url: str) -> str:
    """Replace the password in a DB URL with ***."""
    import re
    return re.sub(r'(:)[^:@]+(@)', r'\1***\2', url)


if __name__ == '__main__':
    main()
