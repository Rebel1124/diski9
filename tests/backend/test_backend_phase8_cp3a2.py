"""Phase 8 CP3A-2 on real PostgreSQL: the Domestic Weekly Challenge card reads a
real published round (open, then locked after the lock step) with its stored code,
fixture window, deadline and frozen time; the next publication target comes from the
active weekend schedule (Friday 08:00 SAST); and, with accounts enabled, Portfolio
Build renders the same card for a guest and a signed-in participant."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from auth_helpers import FakeProvider, make_settings
from svc_helpers import principal, publish_dev, wait_until
from test_backend_auth_web import cookie, register

from diski9.app import ScreenerData, create_app
from diski9.app.challenge import home
from diski9.backend.auth.web import AuthRuntime
from diski9.backend.db import db_now, transaction
from diski9.backend.services import rounds as svc
from diski9.db import make_engine, upgrade

SAST = ZoneInfo("Africa/Johannesburg")


@pytest.fixture(scope="module")
def op(engine):
    return principal(engine, role="operator")


def _local(dt, fmt="%a %d %b, %H:%M"):
    return dt.astimezone(SAST).strftime(fmt)


def _service(engine, round_id):
    """A service whose backend returns this round as the published one (the real
    record and snapshot), independent of other tests' rounds in the database."""
    found = (svc.get_round(engine, round_id), svc.published_snapshot(engine, round_id))
    backend = SimpleNamespace(published=lambda: found, error=False, engine=engine,
                              show_development=True)  # fmt: skip
    with transaction(engine) as conn:
        now = db_now(conn)
    return SimpleNamespace(backend=backend, now=lambda: now)


def test_card_status_from_a_real_round(engine, op):
    v, _ = publish_dev(engine, op, deadline_in=timedelta(seconds=4), seed=8301)
    rv = svc.get_round(engine, v.id)
    st = home.challenge_status(_service(engine, v.id), _local)
    assert st.state == home.OPEN and not st.default_research
    assert st.round_code == rv.code and st.deadline == rv.deadline_at
    assert st.window == (rv.window_start_at, rv.window_end_at)
    assert st.frozen_at == rv.snapshot_at
    assert st.message == f"Entries close {_local(rv.deadline_at)} SAST."
    wait_until(engine, rv.deadline_at)
    st = home.challenge_status(_service(engine, v.id), _local)
    assert st.state == home.LOCKED  # deadline passed, lock step not yet run
    svc.lock_round(engine, svc.SYSTEM, v.id)
    st = home.challenge_status(_service(engine, v.id), _local)
    assert st.state == home.LOCKED and st.message == "Entries closed. Awaiting match results."
    assert not st.default_research  # locked rounds stay on the challenge list by default


def test_publication_target_comes_from_the_weekend_schedule(engine):
    now, target = home.schedule_target(SimpleNamespace(engine=engine))
    local = target.astimezone(SAST)
    assert (local.strftime("%A"), local.hour, local.minute) == ("Friday", 8, 0)
    assert abs(target - now) < timedelta(days=8)  # the competition week now belongs to


@pytest.fixture
def store(tmp_path):
    url = f"sqlite:///{tmp_path / 'store.sqlite'}"
    upgrade(url)
    eng = make_engine(url)
    yield eng
    eng.dispose()


def test_portfolio_home_for_guest_and_member(engine, store):
    provider = FakeProvider()
    rt = AuthRuntime.create(engine, make_settings(), provider)
    app = create_app(ScreenerData(store), auth=rt)
    server = app.server
    server.config["TESTING"] = True
    route = next(v["callback"].__wrapped__ for v in app.callback_map.values()
                 if "callback" in v and v["callback"].__wrapped__.__name__ == "route")  # fmt: skip
    member = server.test_client()
    register(member, provider)
    for headers in ({}, {"Cookie": f"d9_session={cookie(member)}"}):
        with server.test_request_context("/", headers=headers):
            server.preprocess_request()
            pb, content, _, _ = route("/", None, None, None)
        text = str(pb)
        assert "Domestic Weekly Challenge" in text and "Research only" in text
        assert "European" not in text
        assert content is not None  # the builder is rendered beneath, as before
