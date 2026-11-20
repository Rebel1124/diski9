"""Stage E building blocks (real PostgreSQL): operator authentication paths with a
provider **mock** (the genuine Supabase Auth path is
``test_backend_operator_cli.py``), the read-only operator reports, the prompt
scenario timeline and development test entries."""

from __future__ import annotations

from datetime import timedelta

import pytest
from auth_helpers import FakeProvider, make_settings
from settle_helpers import settlement_world
from sqlalchemy import func, select, update
from svc_helpers import principal, publish_dev, wait_until

from diski9.backend import settlement_scenarios as sc
from diski9.backend.auth import operator_cli as oc
from diski9.backend.auth.accounts import account
from diski9.backend.auth.permissions import Forbidden
from diski9.backend.db import db_now, transaction
from diski9.backend.db.schema import (
    result_observations,
    selection_verdicts,
    settlement_runs,
    users,
)
from diski9.backend.services import results as rs
from diski9.backend.services import settlement as st
from diski9.backend.services import settlement_ops as ops
from diski9.backend.services.common import ServiceError

SETTINGS = make_settings()


def linked(engine, provider, role=None, password="Pw-123456789"):
    """A provider user (mock) linked to an onboarded database account."""
    import uuid

    from diski9.backend.auth import accounts as acc
    from diski9.backend.auth.provider import ProviderIdentity

    addr = f"u{uuid.uuid4().hex[:8]}@example.com"
    sub = provider.add_user(addr, password)
    with transaction(engine) as conn:
        uid = acc.ensure_app_user(conn, ProviderIdentity("supabase", sub, addr, True))
        acc.complete_onboarding(
            conn, uid, username=f"Op{uuid.uuid4().hex[:8]}", terms_version="beta-2026-11",
            accepted_terms=True, age_confirmed=True,
        )  # fmt: skip
    if role:
        from settle_helpers import grant

        grant(engine, uid, role)
    return addr, uid


def auth(engine, provider, addr, password="Pw-123456789"):
    return oc.authenticate_operator(
        engine, addr, provider=provider, settings=SETTINGS, read_password=lambda _: password
    )


def test_operator_principal_comes_from_the_database(engine):
    from diski9.backend.db.schema import profiles

    fp = FakeProvider()
    addr, uid = linked(engine, fp, role="operator")
    with transaction(engine) as conn:
        assert conn.execute(select(profiles.c.username).where(profiles.c.user_id == uid)).scalar()
    p = auth(engine, fp, addr)
    with transaction(engine) as conn:
        now = db_now(conn)
        assert account(conn, uid).roles == p.roles == frozenset({"operator"})
    assert p.user_id == uid and p.onboarded
    assert p.authenticated_at == p.reauthenticated_at and now - p.reauthenticated_at < timedelta(5)
    assert p.extra["sensitive_recency_minutes"] == 15
    # the provider session was ended straight away
    assert not any(s["alive"] for s in fp.sessions.values())


@pytest.mark.parametrize(
    "case, code",
    [("wrong", "invalid_credentials"), ("down", "provider_unavailable"),
     ("unlinked", "no_account"), ("suspended", "account_inactive"),
     ("unconfirmed", "unconfirmed"), ("blank", "usage")],
)  # fmt: skip
def test_authentication_fails_closed(engine, case, code):
    fp = FakeProvider()
    addr, uid = linked(engine, fp, role="operator")
    password = "Pw-123456789"
    if case == "wrong":
        password = "nope-nope-1"
    elif case == "down":
        fp.down = True
    elif case == "unlinked":
        addr = "stranger@example.com"
        fp.add_user(addr, password)
    elif case == "suspended":
        with transaction(engine) as conn:
            conn.execute(update(users).where(users.c.id == uid).values(status="suspended"))
    elif case == "unconfirmed":
        addr = "pending@example.com"
        fp.add_user(addr, password, confirmed=False)
    elif case == "blank":
        addr = "  "
    with pytest.raises(oc.OperatorAuthFailed) as exc:
        auth(engine, fp, addr, password)
    assert exc.value.code == code
    assert password not in exc.value.message


def test_a_forged_provider_subject_is_refused(engine):
    fp = FakeProvider()
    addr, _ = linked(engine, fp, role="operator")
    fp.verify_access_token = lambda token: {"sub": "00000000-0000-0000-0000-000000000000"}
    with pytest.raises(oc.OperatorAuthFailed) as exc:
        auth(engine, fp, addr)
    assert exc.value.code == "invalid_token"


def test_password_prompt_refuses_without_a_terminal(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(oc.OperatorAuthFailed) as exc:
        oc.read_password_from_terminal()
    assert exc.value.code == "no_terminal"


def test_unconfigured_provider_fails_closed():
    with pytest.raises(oc.OperatorAuthFailed) as exc:
        oc.default_provider(make_settings(supabase_auth_url=None))
    assert exc.value.code == "auth_not_configured"


# ------------------------------------------------------------------ prompt timeline
def test_prompt_timeline_places_evidence_minutes_after_the_deadline():
    from datetime import UTC, datetime

    deadline = datetime(2026, 11, 28, 12, tzinfo=UTC)
    cutoff = deadline + timedelta(hours=50)
    legs = [[sc.ScenarioLeg(i, "1X2", "HOME", "ABC"[min(i // 4, 2)]) for i in range(9)]]
    obs = sc.build("all-correct", deadline=deadline, cutoff=cutoff, entries=legs,
                   horizon=sc.PROMPT_HORIZON)  # fmt: skip
    assert max(o.observed_at for o in obs) == deadline + timedelta(minutes=4)
    assert all(o.kickoff_at > deadline for o in obs)
    late = sc.build("late-notification", deadline=deadline, cutoff=cutoff, entries=legs,
                    horizon=sc.PROMPT_HORIZON)  # fmt: skip
    assert max(o.observed_at for o in late) == cutoff + timedelta(hours=1)  # cutoff never moves
    standard = sc.build("all-correct", deadline=deadline, cutoff=cutoff, entries=legs)
    assert max(o.observed_at for o in standard) == deadline + (cutoff - deadline) / 2
    assert set(sc.DESCRIPTIONS) == set(sc.SCENARIOS)


# ------------------------------------------------------------------ reports
def _counts(engine, rid):
    with transaction(engine) as conn:
        return tuple(
            conn.execute(select(func.count()).select_from(t).where(t.c.round_id == rid)).scalar()
            for t in (selection_verdicts, settlement_runs)
        ) + (conn.execute(select(func.count()).select_from(result_observations)).scalar(),)


def test_reports_are_read_only_and_match_settlement(engine):
    op = principal(engine, role="operator")
    w = settlement_world(engine, development=True, cutoff_after=timedelta(seconds=5))
    rs.set_result_mode(engine, op, w["round"], "synthetic")
    sc.apply_scenario(engine, op, w["round"], "pending", horizon=sc.PROMPT_HORIZON)
    wait_until(engine, w["deadline"] + timedelta(seconds=3))
    st.settle_round(engine, op, w["round"])
    before = _counts(engine, w["round"])
    fx = ops.fixture_report(engine, op, w["round"])
    rel = [f for f in fx if f.relevant]
    assert len(rel) == 9 and {f.rule for f in rel} == {"settle", "pending"}
    assert all(f.observations for f in rel)
    one = ops.fixture_report(engine, op, w["round"], w["fixtures"][0])
    assert len(one) == 1 and one[0].observations[-1]["status"] == "FT"
    r = ops.round_report(engine, op, w["round"])
    assert r.status == "settling" and r.pending_predictions > 0 and not r.eligible_to_finalise
    assert any("pending" in why for why in r.reasons)
    assert ops.alerts_report(engine, op, w["round"]) == []
    assert _counts(engine, w["round"]) == before  # nothing written by any report
    with pytest.raises(ServiceError):
        ops.fixture_report(engine, op, w["round"], 1)


def test_reports_need_an_operator(engine):
    w = settlement_world(engine, development=True)
    with pytest.raises(Forbidden):
        ops.round_report(engine, principal(engine), w["round"])


def test_finalisation_eligibility_matches_finalise(engine):
    from diski9.backend.services import corrections as co

    op = principal(engine, role="operator")
    w = settlement_world(engine, development=True, cutoff_after=timedelta(seconds=5))
    rs.set_result_mode(engine, op, w["round"], "synthetic")
    sc.apply_scenario(engine, op, w["round"], "all-correct", horizon=sc.PROMPT_HORIZON)
    wait_until(engine, w["deadline"] + timedelta(seconds=3))
    res = st.settle_round(engine, op, w["round"])
    early = ops.round_report(engine, op, w["round"])
    assert not early.eligible_to_finalise and early.reasons == (
        "The correction window has not ended yet.",
    )
    ready = ops.round_report(engine, op, w["round"], as_of=res.earliest_finalisation)
    assert ready.eligible_to_finalise
    assert co.finalise_round(engine, op, w["round"], as_of=res.earliest_finalisation).finalised


# ------------------------------------------------------------------ test entries
def test_test_entries_use_the_ordinary_services(engine):
    op = principal(engine, role="operator")
    view, snap = publish_dev(engine, op)
    keys = {tuple(sorted((s["fixture_id"], s["outcome"]) for s in sc.test_selections(snap, v)))
            for v in range(5)}  # fmt: skip
    assert len(keys) == 5  # five different portfolios
    a, b = principal(engine), principal(engine)
    assert sc.submit_test_entry(engine, a, view.id, 0).active
    assert sc.submit_test_entry(engine, a, view.id, 1).active  # replacement
    assert sc.submit_test_entry(engine, b, view.id, 2).current is not None


def test_test_entries_refuse_real_rounds(engine):
    w = settlement_world(engine, lock=False)
    with pytest.raises(ServiceError, match="development rounds"):
        sc.submit_test_entry(engine, principal(engine), w["round"])
