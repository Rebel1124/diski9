"""Backend database settings and test-database guards (no database needed)."""

from __future__ import annotations

import pytest

from diski9.backend.db import (
    BackendDatabaseError,
    BackendDatabaseSettings,
    require_test_database_url,
)

GOOD = "postgresql+psycopg://diski9:s3cret-pass@127.0.0.1:5432/diski9"


def test_postgres_url_accepted_and_password_hidden():
    s = BackendDatabaseSettings(database_url=GOOD, _env_file=None)
    assert s.url() == GOOD
    assert "s3cret-pass" not in s.safe_url()
    assert "s3cret-pass" not in repr(s)


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///data/diski9.sqlite",
        "mysql://x:y@h/db",
        "postgresql+psycopg2://u:p@h/db",
        "postgresql+psycopg://u:p@h",
        "not a url",
        "mysql://x:y@h/db?secret=1",
    ],
)
def test_non_postgres_or_incomplete_urls_rejected(url):
    with pytest.raises(ValueError) as exc:
        BackendDatabaseSettings(database_url=url, _env_file=None)
    assert ":y@" not in str(exc.value) and "u:p@" not in str(exc.value)


def test_missing_url_has_a_clear_message():
    s = BackendDatabaseSettings(database_url=None, _env_file=None)
    with pytest.raises(BackendDatabaseError, match="DISKI9_APP_DATABASE_URL is not set"):
        s.url()


def test_production_cannot_use_a_test_database():
    with pytest.raises(ValueError, match="_test"):
        BackendDatabaseSettings(
            environment="production",
            database_url="postgresql+psycopg://u:p@h/diski9_test",
            _env_file=None,
        )


@pytest.mark.parametrize(
    ("url", "env", "ok"),
    [
        ("postgresql+psycopg://u:p@h/diski9_test", "test", True),
        ("postgresql+psycopg://u:p@h/diski9", "test", False),  # not a *_test database
        ("postgresql+psycopg://u:p@h/diski9_test", "production", False),
        ("sqlite:///x_test", "test", False),
        (None, "test", False),
    ],
)
def test_tests_only_run_against_a_test_database(url, env, ok):
    if ok:
        assert require_test_database_url(url, env) == url
    else:
        with pytest.raises((BackendDatabaseError, ValueError)):
            require_test_database_url(url, env)
