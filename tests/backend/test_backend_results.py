"""Phase 6C.4 Stage B: result observations, the provider boundary and development
result modes, on real PostgreSQL."""

from __future__ import annotations

from datetime import timedelta

import pytest
import sqlalchemy as sa
from settle_helpers import grant, provider_item, settlement_world
from svc_helpers import principal

from diski9.backend.auth.permissions import AuthorizationError
from diski9.backend.db import db_now, transaction
from diski9.backend.db.schema import result_observations as RO
from diski9.backend.db.schema import rounds as rounds_t
from diski9.backend.repositories import results as repo
from diski9.backend.services import results as rs
from diski9.backend.services.rounds import SYSTEM
from diski9.ingestion.results_fetch import batches, canonical_hash, evidence_fields


class FakeClient:
    """Records requests; answers ``/fixtures?ids=...`` from a dictionary of items."""

    def __init__(self, items):
        self.items, self.calls = items, []

    def get(self, endpoint, params):
        self.calls.append((endpoint, dict(params)))
        ids = [int(x) for x in params["ids"].split("-")]

        class R:
            pass

        r = R()
        r.items = [self.items[i] for i in ids if i in self.items] + list(self.extra)
        return r

    extra: tuple = ()


def fetch_with(client):
    from diski9.ingestion.results_fetch import fetch_fixtures_by_ids

    return lambda ids: fetch_fixtures_by_ids(client, ids)


@pytest.fixture(scope="module")
def op(engine):
    return principal(engine, role="operator")


@pytest.fixture(scope="module")
def world(engine):
    return settlement_world(engine, cutoff_after=timedelta(hours=6))


def _record(conn, fid, at, status, ko, **kw):
    item = provider_item(fid, status, ko=ko, **kw)
    return repo.record_evidence(
        conn, source="api-football", fixture_id=fid, observed_at=at, raw=item,
        raw_hash=canonical_hash(item), fields=evidence_fields(item),
    )  # fmt: skip


def _rows(conn, fid):
    return list(
        conn.execute(
            sa.select(RO).where(RO.c.fixture_id == fid).order_by(RO.c.observed_at, RO.c.id)
        )
    )


# ------------------------------------------------------------------ provider boundary
def test_batches_of_twenty_ids_and_canonical_hash():
    assert [len(b) for b in batches(range(45))] == [20, 20, 5]
    assert batches([3, 1, 3, 2]) == [[1, 2, 3]]
    assert canonical_hash({"b": 1, "a": [1, 2]}) == canonical_hash({"a": [1, 2], "b": 1})


def test_evidence_fields_read_fulltime_and_keep_first_half_separately(world):
    ko = (world["deadline"] + timedelta(hours=1)).replace(microsecond=0)
    f = evidence_fields(provider_item(5, "AET", ko=ko, h=1, a=1, first_half=ko))
    assert (f["status_short"], f["ft_home"], f["ft_away"]) == ("AET", 1, 1)
    assert f["kickoff_at"] == ko and f["provider_first_half_at"] == ko


# ------------------------------------------------------------------ recorder
def test_identical_repeat_is_idempotent_and_a_b_a_keeps_three_rows(engine, world):
    fid = world["fixtures"][0]
    ko = world["deadline"] + timedelta(minutes=15)
    with transaction(engine) as conn:
        t = db_now(conn) - timedelta(minutes=10)
        assert _record(conn, fid, t, "1H", ko)
        assert _record(conn, fid, t + timedelta(minutes=1), "1H", ko) is None  # identical
        assert _record(conn, fid, t + timedelta(minutes=2), "HT", ko)
        assert _record(conn, fid, t + timedelta(minutes=3), "1H", ko)  # back to A
        statuses = [r.status_short for r in _rows(conn, fid)]
    assert statuses == ["1H", "HT", "1H"]


def test_late_commit_of_an_older_fetch_is_kept_but_never_latest(engine, world):
    fid = world["fixtures"][1]
    ko = world["deadline"] + timedelta(minutes=16)
    with transaction(engine) as conn:
        now = db_now(conn)
        _record(conn, fid, now - timedelta(minutes=1), "FT", ko, h=2, a=0)
        _record(conn, fid, now - timedelta(minutes=20), "2H", ko)  # older fetch, later commit
        latest = repo.latest_evidence_row(conn, fid, mode="real", round_id=world["round"])
    assert latest.status_short == "FT"


def test_receipt_time_can_never_be_after_recording(engine, world):
    fid = world["fixtures"][2]
    with pytest.raises(sa.exc.IntegrityError), transaction(engine) as conn:
        _record(conn, fid, db_now(conn) + timedelta(hours=1), "NS", world["deadline"])


def test_provider_rows_cannot_carry_verified_times_or_scope(engine, world):
    base = dict(fixture_id=world["fixtures"][3], source="api-football", raw_hash="a" * 64)
    with transaction(engine) as conn:
        now = db_now(conn)
    for extra in ({"completed_at": now}, {"actual_kickoff_at": now},
                  {"scope_round_id": world["round"]}):  # fmt: skip
        with pytest.raises(sa.exc.IntegrityError), transaction(engine) as conn:
            conn.execute(sa.insert(RO).values(observed_at=now, **base, **extra))


def test_operator_rows_need_actor_reason_and_evidence(engine, world, op):
    base = dict(fixture_id=world["fixtures"][3], source="operator", raw_hash="b" * 64)
    with transaction(engine) as conn:
        now = db_now(conn)
    bad = [
        {"reason": "x", "evidence": "y"},  # no actor
        {"actor_user_id": op.user_id, "evidence": "y"},  # no reason
        {"actor_user_id": op.user_id, "reason": "x"},  # no evidence
    ]
    for extra in bad:
        with pytest.raises(sa.exc.IntegrityError), transaction(engine) as conn:
            conn.execute(sa.insert(RO).values(observed_at=now, **base, **extra))
    with transaction(engine) as conn:  # an assertion without a provider row is allowed
        conn.execute(sa.insert(RO).values(observed_at=now, actor_user_id=op.user_id,
                                          reason="x", evidence="league site", **base))  # fmt: skip


def test_observations_are_insert_only(engine, world):
    fid = world["fixtures"][0]
    with pytest.raises(sa.exc.DBAPIError), transaction(engine) as conn:
        conn.execute(sa.update(RO).where(RO.c.fixture_id == fid).values(ft_home=9))
    with pytest.raises(sa.exc.DBAPIError), transaction(engine) as conn:
        conn.execute(sa.delete(RO).where(RO.c.fixture_id == fid))


# ------------------------------------------------------------------ import
def test_import_fetches_only_relevant_due_fixtures_in_batches(engine, world, op):
    fids = world["fixtures"]
    ko = world["deadline"] + timedelta(minutes=15)
    items = {f: provider_item(f, "FT", ko=ko, h=1, a=0) for f in fids}
    client = FakeClient(items)
    client.extra = (provider_item(999_999_999, "FT", ko=ko, h=0, a=0),)  # unasked-for item
    stored = []
    res = rs.import_results(engine, op, world["round"], fetch_with(client),
                            football_store=stored.extend)  # fmt: skip
    relevant = sorted(fids[:9])  # the locked entry uses fixtures 0..8; 9..11 unselected
    assert sorted(res.polled) == relevant and res.requests == 1
    assert client.calls[0][1]["ids"] == "-".join(map(str, relevant))
    assert all(int(i["fixture"]["id"]) in relevant for i in stored)
    with transaction(engine) as conn:
        assert not _rows(conn, 999_999_999)
        assert not _rows(conn, fids[10])


def test_repeated_import_records_nothing_new(engine, world, op):
    fids = world["fixtures"]
    ko = world["deadline"] + timedelta(minutes=15)
    client = FakeClient({f: provider_item(f, "FT", ko=ko, h=1, a=0) for f in fids})
    res = rs.import_results(engine, op, world["round"], fetch_with(client), full=True)
    assert res.recorded == 0 and res.unchanged == res.received


def test_poll_plan_skips_distant_and_stable_fixtures(world):
    from types import SimpleNamespace as NS

    now = world["deadline"]
    frozen = {1: now + timedelta(hours=5), 2: now + timedelta(minutes=10), 3: now}
    latest = {
        3: NS(kickoff_at=now, status_short="FT", ft_home=1, observed_at=now - timedelta(hours=7))
    }
    poll, skip = rs.poll_plan(frozen, latest, now)
    assert poll == [2] and skip == [1, 3]
    assert rs.poll_plan(frozen, latest, now, full=True)[0] == [2, 3]


def test_import_requires_an_authorised_actor_and_a_locked_real_round(engine, world):
    participant = principal(engine)
    with pytest.raises(AuthorizationError):
        rs.import_results(engine, participant, world["round"], lambda ids: ([], 0))
    # the explicit scheduled-job actor is allowed for routine collection
    assert rs.import_results(engine, SYSTEM, world["round"], lambda ids: ([], 0)).recorded == 0
    open_world = settlement_world(engine, lock=False, deadline_in=timedelta(hours=1))
    with pytest.raises(rs.ResultsRefused):
        rs.import_results(engine, SYSTEM, open_world["round"], lambda ids: ([], 0))


# ------------------------------------------------------------------ development modes
def test_real_rounds_are_always_real_mode_and_refuse_synthetic(engine, world, op):
    with transaction(engine) as conn:
        mode = conn.execute(
            sa.select(rounds_t.c.result_mode).where(rounds_t.c.id == world["round"])
        ).scalar_one()
    assert mode == "real"
    with pytest.raises(rs.ResultsRefused):
        rs.set_result_mode(engine, op, world["round"], "synthetic")
    with pytest.raises(sa.exc.DBAPIError), transaction(engine) as conn:
        conn.execute(sa.update(rounds_t).where(rounds_t.c.id == world["round"])
                     .values(result_mode="synthetic"))  # fmt: skip


def test_development_mode_is_explicit_and_frozen(engine, op):
    dev = settlement_world(engine, development=True)
    with transaction(engine) as conn:
        assert conn.execute(sa.select(rounds_t.c.result_mode)
                            .where(rounds_t.c.id == dev["round"])).scalar_one() is None  # fmt: skip
    with pytest.raises(rs.ResultsRefused):  # no mode yet: nothing can be recorded
        rs.record_synthetic_observation(engine, op, dev["round"], dev["fixtures"][0],
                                        observed_at=dev["deadline"], status="NS")  # fmt: skip
    assert rs.set_result_mode(engine, op, dev["round"], "synthetic") == "synthetic"
    with pytest.raises(rs.ResultsRefused):
        rs.set_result_mode(engine, op, dev["round"], "real")
    with pytest.raises(sa.exc.DBAPIError), transaction(engine) as conn:
        conn.execute(sa.update(rounds_t).where(rounds_t.c.id == dev["round"])
                     .values(result_mode="real"))  # fmt: skip


def test_synthetic_evidence_is_scoped_and_never_seen_by_real_rounds(engine, op, world):
    dev = settlement_world(engine, development=True)
    rs.set_result_mode(engine, op, dev["round"], "synthetic")
    fid = dev["fixtures"][0]
    new = rs.record_synthetic_observation(
        engine, op, dev["round"], fid, observed_at=dev["deadline"] + timedelta(hours=2),
        status="FT", ft_home=2, ft_away=1,
    )  # fmt: skip
    assert new is not None
    with transaction(engine) as conn:
        synth = repo.observation_rows(conn, [fid], mode="synthetic", round_id=dev["round"])
        real = repo.observation_rows(conn, [fid], mode="real", round_id=world["round"])
    assert [r.source for r in synth] == ["synthetic"] and real == []
    # a synthetic row can never be scoped to a real round or a real-mode development round
    real_dev = settlement_world(engine, development=True)
    rs.set_result_mode(engine, op, real_dev["round"], "real")
    for target in (world["round"], real_dev["round"]):
        with pytest.raises(sa.exc.DBAPIError), transaction(engine) as conn:
            conn.execute(sa.insert(RO).values(
                fixture_id=fid, observed_at=dev["deadline"], source="synthetic",
                raw_hash="c" * 64, scope_round_id=target))  # fmt: skip
    with pytest.raises(rs.ResultsRefused):
        rs.record_synthetic_observation(engine, op, real_dev["round"], fid,
                                        observed_at=dev["deadline"], status="NS")  # fmt: skip
    with pytest.raises(rs.ResultsRefused):  # real-mode development rounds import, never synthesise
        rs.import_results(engine, op, dev["round"], lambda ids: ([], 0))


def test_synthetic_results_are_refused_in_production(engine, op, monkeypatch):
    dev = settlement_world(engine, development=True)
    monkeypatch.setenv("DISKI9_APP_ENVIRONMENT", "production")
    with pytest.raises(rs.ResultsRefused):
        rs.set_result_mode(engine, op, dev["round"], "synthetic")


def test_synthetic_evidence_needs_a_person_with_jobs_permission(engine, op):
    dev = settlement_world(engine, development=True)
    rs.set_result_mode(engine, op, dev["round"], "synthetic")
    with pytest.raises(AuthorizationError):
        rs.record_synthetic_observation(engine, principal(engine), dev["round"],
                                        dev["fixtures"][0], observed_at=dev["deadline"],
                                        status="NS")  # fmt: skip
    _ = grant  # (role helper used by later stages)
