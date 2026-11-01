"""
EduPulse — MySQL Configuration Unit Tests
==========================================
Tests the database configuration selection logic WITHOUT a live MySQL server.

Run:
    python test_mysql_config.py
"""

import os
import sys
import unittest


class TestConfigSelection(unittest.TestCase):
    """Verify that config.py selects the correct database dialect and engine options."""

    def _reload_config(self):
        """Force a fresh re-import of config so env var changes take effect."""
        import importlib
        import config as cfg_module
        importlib.reload(cfg_module)
        return cfg_module

    def setUp(self):
        # Stash and clear relevant environment variables before each test.
        self._orig_env = {
            'DATABASE_URL': os.environ.pop('DATABASE_URL', None),
            'FLASK_ENV': os.environ.pop('FLASK_ENV', None),
        }

    def tearDown(self):
        # Restore original environment.
        for k, v in self._orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # ------------------------------------------------------------------
    # Test 1: Development config with no DATABASE_URL → SQLite fallback
    # ------------------------------------------------------------------
    def test_development_defaults_to_sqlite(self):
        cfg = self._reload_config()
        dev_cfg = cfg.config['development']
        uri = dev_cfg.SQLALCHEMY_DATABASE_URI
        self.assertTrue(
            uri.startswith('sqlite:///'),
            f'Expected SQLite URI in development, got: {uri}'
        )
        # SQLite engine options must include check_same_thread.
        opts = dev_cfg.SQLALCHEMY_ENGINE_OPTIONS
        self.assertIn('connect_args', opts, 'SQLite config must have connect_args')
        self.assertIn('check_same_thread', opts['connect_args'])

    # ------------------------------------------------------------------
    # Test 2: Development config with DATABASE_URL set → MySQL selected
    # ------------------------------------------------------------------
    def test_development_with_database_url_uses_mysql(self):
        os.environ['DATABASE_URL'] = 'mysql+pymysql://user:pass@localhost:3306/testdb'
        cfg = self._reload_config()
        dev_cfg = cfg.config['development']
        uri = dev_cfg.SQLALCHEMY_DATABASE_URI
        self.assertTrue(
            uri.startswith('mysql+pymysql://'),
            f'Expected MySQL URI when DATABASE_URL set, got: {uri}'
        )
        opts = dev_cfg.SQLALCHEMY_ENGINE_OPTIONS
        self.assertNotIn('connect_args', opts, 'MySQL config must NOT have SQLite connect_args')
        self.assertIn('pool_recycle', opts)
        self.assertIn('pool_pre_ping', opts)

    # ------------------------------------------------------------------
    # Test 3: bare mysql:// URL normalised to mysql+pymysql://
    # ------------------------------------------------------------------
    def test_mysql_url_normalisation(self):
        os.environ['DATABASE_URL'] = 'mysql://user:pass@localhost:3306/testdb'
        cfg = self._reload_config()
        dev_cfg = cfg.config['development']
        uri = dev_cfg.SQLALCHEMY_DATABASE_URI
        self.assertTrue(
            uri.startswith('mysql+pymysql://'),
            f'bare mysql:// should be normalised to mysql+pymysql://, got: {uri}'
        )

    # ------------------------------------------------------------------
    # Test 4: Production config without DATABASE_URL → _resolve() raises RuntimeError
    # ------------------------------------------------------------------
    def test_production_without_database_url_raises(self):
        cfg = self._reload_config()
        prod_cfg = cfg.config['production']
        self.assertTrue(
            hasattr(prod_cfg, '_resolve'),
            'ProductionConfig must have a _resolve() classmethod'
        )
        with self.assertRaises(RuntimeError) as ctx:
            prod_cfg._resolve()
        self.assertIn('DATABASE_URL', str(ctx.exception))

    # ------------------------------------------------------------------
    # Test 5: Production config WITH DATABASE_URL → _resolve() returns normalised URL
    # ------------------------------------------------------------------
    def test_production_with_database_url_resolves(self):
        os.environ['DATABASE_URL'] = 'mysql+pymysql://prod_user:secret@db.host:3306/edupulse'
        cfg = self._reload_config()
        prod_cfg = cfg.config['production']
        resolved = prod_cfg._resolve()
        self.assertTrue(
            resolved.startswith('mysql+pymysql://'),
            f'Expected mysql+pymysql:// URL, got: {resolved}'
        )

    # ------------------------------------------------------------------
    # Test 6: SQLite engine options do NOT leak into MySQL config
    # ------------------------------------------------------------------
    def test_sqlite_connect_args_not_in_mysql_config(self):
        os.environ['DATABASE_URL'] = 'mysql+pymysql://u:p@h/db'
        cfg = self._reload_config()
        opts = cfg.config['development'].SQLALCHEMY_ENGINE_OPTIONS
        connect_args = opts.get('connect_args', {})
        self.assertNotIn(
            'check_same_thread', connect_args,
            '`check_same_thread` must NOT appear in MySQL engine options'
        )
        self.assertNotIn(
            'timeout', connect_args,
            '`timeout` (pysqlite-only) must NOT appear in MySQL engine options'
        )

    # ------------------------------------------------------------------
    # Test 7: Testing config with no DATABASE_URL → SQLite (no RuntimeError)
    # ------------------------------------------------------------------
    def test_testing_config_falls_back_to_sqlite(self):
        cfg = self._reload_config()
        test_cfg = cfg.config['testing']
        uri = test_cfg.SQLALCHEMY_DATABASE_URI
        self.assertTrue(
            uri.startswith('sqlite:///'),
            f'Testing config should fall back to SQLite, got: {uri}'
        )
        self.assertTrue(test_cfg.TESTING)
        self.assertFalse(test_cfg.WTF_CSRF_ENABLED)

    # ------------------------------------------------------------------
    # Test 8: create_app() with development config starts without error
    # ------------------------------------------------------------------
    def test_create_app_development_starts(self):
        cfg = self._reload_config()
        # Remove any DATABASE_URL to ensure SQLite path.
        os.environ.pop('DATABASE_URL', None)
        from app import create_app
        try:
            app = create_app('development')
            self.assertIsNotNone(app)
            uri = app.config['SQLALCHEMY_DATABASE_URI']
            self.assertTrue(uri.startswith('sqlite:///'), f'Expected SQLite, got: {uri}')
        except RuntimeError as exc:
            self.fail(f'create_app(development) raised RuntimeError: {exc}')


def main():
    print('=' * 60)
    print('  EduPulse — MySQL Configuration Unit Tests')
    print('=' * 60)
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestConfigSelection)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        sys.exit(1)
    print('\n  All configuration tests passed.')
    sys.exit(0)


if __name__ == '__main__':
    main()
