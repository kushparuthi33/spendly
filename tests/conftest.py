"""
Shared fixtures for the Spendly test suite.

Key design decisions:
- get_db() in database/db.py hard-codes "spendly.db", so we monkeypatch it to
  return a connection to a temporary on-disk SQLite file (one per test via tmp_path).
  This avoids touching the real database while still exercising the full SQL layer.
- init_db() is called explicitly inside each fixture that needs a fresh schema.
- seed_db() is intentionally NOT called here; tests that need data create it
  themselves so test state is deterministic.
- The Flask app is reconfigured with TESTING=True and a known SECRET_KEY so
  session cookies are verifiable.
"""

import sqlite3
import pytest
from werkzeug.security import generate_password_hash

import database.db as db_module
from app import app as flask_app


# ---------------------------------------------------------------------------
# Core fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """
    Patch get_db() so every database call in this test goes to an isolated
    temporary SQLite file, not spendly.db.  Returns the path so individual
    tests can open extra connections for setup.
    """
    db_path = str(tmp_path / "test.db")

    def _get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    monkeypatch.setattr(db_module, "get_db", _get_db)
    return db_path


@pytest.fixture()
def app(tmp_db):
    """Flask app configured for testing, with schema initialised and seed skipped."""
    flask_app.config.update(
        TESTING=True,
        SECRET_KEY="test-secret-spendly",
        WTF_CSRF_ENABLED=False,
    )

    with flask_app.app_context():
        db_module.init_db()   # create tables in the tmp DB
        yield flask_app


@pytest.fixture()
def client(app):
    """Unauthenticated test client."""
    return app.test_client()


@pytest.fixture()
def registered_user(tmp_db):
    """
    Insert a test user directly into the tmp DB and return (user_id, email, password).
    Called *after* tmp_db is set up but before the app fixture has run init_db, so
    we rely on app fixture ordering — app already ran init_db by the time a test body runs.
    """
    # We can't use db_module helpers here before app fixture runs, so this is a
    # plain helper; tests import it as a fixture dependency together with `app`.
    return {"name": "Test User", "email": "test@spendly.com", "password": "testpassword1"}


@pytest.fixture()
def auth_client(client, app, registered_user):
    """
    A test client that has a registered account and is already logged in.
    Registration is done via the /register route so the full auth flow is exercised.
    Returns (client, user_id).
    """
    u = registered_user
    with app.app_context():
        user_id = db_module.create_user(
            u["name"], u["email"], generate_password_hash(u["password"])
        )

    # Log in via session injection — avoids depending on the login route's
    # exact form field names for fixtures used by unrelated tests.
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = u["name"]

    return client, user_id
