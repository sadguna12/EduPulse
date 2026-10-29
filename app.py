import os
import tempfile
from flask import Flask
import sqlite3
from sqlalchemy import event
from sqlalchemy.engine import Engine
from config import config
from extensions import db, login_manager, csrf
from models import User


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA busy_timeout = 30000;")
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.close()


def configure_sqlite_wal(app):
    """
    Ensure SQLite database uses Write-Ahead Logging (WAL) mode.
    Only runs if using a file-based SQLite database.
    Operates outside active transactions using autocommit mode.
    """
    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if db_uri.startswith('sqlite:///') and not db_uri.startswith('sqlite:///:memory:'):
        db_path = db_uri.replace('sqlite:///', '')
        if os.path.exists(db_path):
            try:
                conn = sqlite3.connect(db_path, timeout=30.0, isolation_level=None)
                cur = conn.cursor()
                cur.execute("PRAGMA journal_mode;")
                row = cur.fetchone()
                if row and row[0].lower() != 'wal':
                    cur.execute("PRAGMA journal_mode = WAL;")
                cur.execute("PRAGMA synchronous = NORMAL;")
                cur.close()
                conn.close()
            except Exception:
                pass


def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Ensure upload and model directories exist on writable paths
    upload_folder = app.config.get('UPLOAD_FOLDER')
    if not upload_folder:
        upload_folder = os.path.join(tempfile.gettempdir(), 'edupulse_uploads')
        app.config['UPLOAD_FOLDER'] = upload_folder

    try:
        os.makedirs(upload_folder, exist_ok=True)
    except OSError:
        # Fallback to temp directory if configured directory is read-only (e.g. Vercel)
        upload_folder = os.path.join(tempfile.gettempdir(), 'edupulse_uploads')
        os.makedirs(upload_folder, exist_ok=True)
        app.config['UPLOAD_FOLDER'] = upload_folder

    model_folder = app.config.get('MODEL_FOLDER')
    if model_folder:
        try:
            os.makedirs(model_folder, exist_ok=True)
        except OSError:
            pass

    # Initialize extensions
    db.init_app(app)
    configure_sqlite_wal(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'warning'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Register blueprints
    from routes.auth import auth_bp
    from routes.admin import admin_bp
    from routes.faculty import faculty_bp
    from routes.student import student_bp
    from routes.api import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(faculty_bp, url_prefix='/faculty')
    app.register_blueprint(student_bp, url_prefix='/student')
    app.register_blueprint(api_bp, url_prefix='/api')

    # Error handlers
    @app.errorhandler(403)
    def forbidden(e):
        from flask import render_template
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found(e):
        from flask import render_template
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        from flask import render_template
        return render_template('errors/500.html'), 500

    return app


# Top-level WSGI / Vercel entrypoint
app = create_app()


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000, use_reloader=False)
