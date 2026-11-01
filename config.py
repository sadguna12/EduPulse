import os
import tempfile

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
IS_VERCEL = bool(os.environ.get('VERCEL') or os.environ.get('VERCEL_ENV') or os.environ.get('AWS_LAMBDA_FUNCTION_NAME'))


def _normalise_mysql_url(url: str) -> str:
    """Ensure mysql:// URLs use the PyMySQL driver by prefixing with +pymysql."""
    if url.startswith('mysql://'):
        return 'mysql+pymysql://' + url[len('mysql://'):]
    return url


def _build_engine_options(db_url: str) -> dict:
    """
    Return SQLAlchemy engine options appropriate for the detected database dialect.

    SQLite and MySQL require fundamentally different connection arguments:
    - timeout / check_same_thread  are pysqlite (SQLite) only — NOT valid for MySQL.
    - pool_recycle / pool_size / max_overflow are needed for persistent MySQL connections.
    """
    if db_url.startswith('sqlite'):
        return {
            'connect_args': {
                'timeout': 30.0,
                'check_same_thread': False,
            },
            'pool_pre_ping': True,
        }
    # MySQL / serverless configuration.
    # pool_recycle: recycle connections before managed MySQL server's wait_timeout (~8 h).
    # pool_pre_ping: test each connection before use.
    # pool_size / max_overflow: conservative for Vercel serverless concurrency.
    return {
        'pool_pre_ping': True,
        'pool_recycle': 280,
        'pool_size': 5,
        'max_overflow': 10,
    }


_SQLITE_FALLBACK = 'sqlite:///' + os.path.join(BASE_DIR, 'edupulse.db')


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'edupulse-dev-secret-key-2024-change-in-production'
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max upload
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER') or (
        os.path.join(tempfile.gettempdir(), 'edupulse_uploads') if IS_VERCEL
        else os.path.join(BASE_DIR, 'uploads')
    )
    MODEL_FOLDER = os.environ.get('MODEL_FOLDER') or os.path.join(BASE_DIR, 'ml_models')
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = 3600 * 8  # 8 hours
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class DevelopmentConfig(Config):
    DEBUG = True
    _raw_url = _normalise_mysql_url(os.environ.get('DATABASE_URL', '').strip()) or _SQLITE_FALLBACK
    SQLALCHEMY_DATABASE_URI = _raw_url
    SQLALCHEMY_ENGINE_OPTIONS = _build_engine_options(_raw_url)


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True

    @classmethod
    def _resolve(cls):
        """Called by create_app() to validate and resolve production DB URL at startup time."""
        url = os.environ.get('DATABASE_URL', '').strip()
        if not url:
            raise RuntimeError(
                "DATABASE_URL is not set. "
                "EduPulse requires an explicit MySQL connection string in production. "
                "Set the DATABASE_URL environment variable, e.g.:\n"
                "  mysql+pymysql://user:password@host:3306/edupulse"
            )
        return _normalise_mysql_url(url)

    # Class-level attributes are populated at import; production guard runs at startup via create_app().
    # If DATABASE_URL is set at import time (e.g. during testing), use it. Otherwise defer.
    _raw_url = _normalise_mysql_url(os.environ.get('DATABASE_URL', '').strip()) or _SQLITE_FALLBACK
    SQLALCHEMY_DATABASE_URI = _raw_url
    SQLALCHEMY_ENGINE_OPTIONS = _build_engine_options(_raw_url)


class TestingConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    _raw_url = _normalise_mysql_url(os.environ.get('DATABASE_URL', '').strip()) or _SQLITE_FALLBACK
    SQLALCHEMY_DATABASE_URI = _raw_url
    SQLALCHEMY_ENGINE_OPTIONS = _build_engine_options(_raw_url)


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig,
}
