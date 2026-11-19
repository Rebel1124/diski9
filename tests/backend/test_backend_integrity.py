"""Database-level integrity of the competition schema on real PostgreSQL:
identity and username rules, ownership, snapshot consistency, history protection,
set-once columns, deferred keys, approved-rule CHECKs and runtime privileges.

These are the 6C.1 foundations. Business validation (4/3/2 composition, the
30-day rename rule, sign-in) is service-layer work in later stages."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from pg_helpers import (
    confirm,
    make_round,
    make_user,
    selections_for,
    submission_values,
    unique,
)
from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from diski9.backend.db import db_now, transaction
from diski9.backend.db.schema import (
    designations,
    entries,
    entry_settlements,
    profiles,
    round_evaluations,
    rounds,
    settlement_runs,
    submissions,
    username_history,
)
from diski9.backend.repositories import accounts, ops, portfolios


def raises_db(engine, fn, match: str | None = None):
    with pytest.raises(DBAPIError) as exc, transaction(engine) as conn:
        fn(conn)
    if match:
        assert match in str(exc.value)
    return exc.value


# ---------------------------------------------------------------- identity and profiles
def test_identity_mapping_is_unique(engine):
    sub = unique("sub-")
    with transaction(engine) as conn:
        a = accounts.create_user(conn)
        accounts.link_identity(conn, a, "supabase", sub)
        assert accounts.find_user_by_identity(conn, "supabase", sub) == a

    def again(conn):
        b = accounts.create_user(conn)
        accounts.link_identity(conn, b, "supabase", sub)

    raises_db(engine, again, "user_identities_provider_subject_key")


def test_usernames_are_unique_ignoring_case(engine):
    name = unique("Ace")
    with transaction(engine) as conn:
        make_user(conn, username=name)
    raises_db(engine, lambda c: make_user(c, username=name.upper()), "profiles_username_key")


@pytest.mark.parametrize("bad", ["ab", "x" * 25, " lead", "trail ", "bad!name", "two__ok?"])
def test_username_format_is_enforced(engine, bad):
    raises_db(engine, lambda c: make_user(c, username=bad), "check")


def test_username_key_must_match_username(engine):
    def mismatch(conn):
        uid = accounts.create_user(conn)
        conn.execute(
            insert(profiles).values(
                user_id=uid,
                username="Alpha1",
                username_key="other",
                anonymous_alias="Anonymous 1234",
            )
        )

    raises_db(engine, mismatch, "check")


def test_username_history_allows_only_anonymisation(engine):
    with transaction(engine) as conn:
        uid = make_user(conn)
        hid = conn.execute(
            select(username_history.c.id).where(username_history.c.user_id == uid)
        ).scalar_one()
    raises_db(
        engine,
        lambda c: c.execute(
            update(username_history)
            .where(username_history.c.id == hid)
            .values(username="SomeoneElse")
        ),
        "only anonymisation",
    )
    raises_db(
        engine,
        lambda c: c.execute(
            update(username_history)
            .where(username_history.c.id == hid)
            .values(username="[deleted]", reason="sneaky")
        ),
        "only anonymisation",
    )
    with transaction(engine) as conn:  # account deletion (D-36)
        conn.execute(
            update(username_history)
            .where(username_history.c.id == hid)
            .values(username="[deleted]")
        )
    raises_db(
        engine,
        lambda c: c.execute(username_history.delete().where(username_history.c.id == hid)),
        "only anonymisation",
    )


def test_roles_and_entitlements_are_independent(engine):
    with transaction(engine) as conn:
        owner, member = make_user(conn), make_user(conn)
        accounts.grant_role(conn, owner, "owner", None)
        for f in ("lucy.research", "lucy.voice", "lucy.presenter"):
            accounts.grant_feature(conn, owner, f, "owner", owner)
        accounts.grant_feature(conn, member, "lucy.research", "manual", owner, "premium pilot")
        assert accounts.roles_of(conn, owner) == {"participant", "owner"}
        assert accounts.roles_of(conn, member) == {"participant"}  # no operator powers
        assert accounts.live_features(conn, member) == {"lucy.research"}
    raises_db(
        engine,
        lambda c: accounts.grant_feature(c, member, "lucy.research", "manual", owner),
        "uq_entitlement_live",
    )
    raises_db(
        engine,
        lambda c: accounts.grant_feature(c, member, "unknown.feature", "manual", owner),
        "foreign key",
    )
    with transaction(engine) as conn:
        assert accounts.revoke_feature(conn, member, "lucy.research", owner, "pilot ended")
        assert accounts.live_features(conn, member) == frozenset()
        # a new grant is possible after revocation; the old row stays as history
        accounts.grant_feature(conn, member, "lucy.research", "manual", owner, "again")
    with pytest.raises(ValueError), transaction(engine) as conn:
        accounts.grant_role(conn, member, "admin", owner)


def test_revoked_grant_cannot_be_changed_again(engine):
    with transaction(engine) as conn:
        a, b = make_user(conn), make_user(conn)
        gid = accounts.grant_feature(conn, a, "lucy.voice", "owner", b)
        accounts.revoke_feature(conn, a, "lucy.voice", b, "done")
    raises_db(
        engine,
        lambda c: c.execute(
            text("UPDATE app.entitlement_grants SET revoked_at = now() WHERE id = :i"), {"i": gid}
        ),
        "insert-only apart from one revocation",
    )


def test_terms_acceptance_requires_age_confirmation(engine):
    with transaction(engine) as conn:
        conn.execute(
            text(
                "INSERT INTO app.terms_versions (version, published_at, content_hash)"
                " VALUES ('t-1', now(), repeat('a', 64)) ON CONFLICT DO NOTHING"
            )
        )
        uid = make_user(conn)
        accounts.record_terms_acceptance(conn, uid, "t-1")
        assert accounts.has_accepted(conn, uid, "t-1")
    raises_db(
        engine,
        lambda c: c.execute(
            text(
                "INSERT INTO app.terms_acceptances (user_id, terms_version, age_confirmed) "
                "VALUES (:u, 't-1', false)"
            ),
            {"u": make_user(c)},
        ),
        "check",
    )


# ---------------------------------------------------------------- portfolios
def test_one_entry_per_user_per_round(engine, world):
    with transaction(engine) as conn:
        portfolios.create_entry(conn, world["round"], world["user"])
    raises_db(
        engine,
        lambda c: portfolios.create_entry(c, world["round"], world["user"]),
        "entries_round_id_user_id_key",
    )


def test_submission_cannot_use_another_users_entry(engine, world):
    with transaction(engine) as conn:
        entry_id = portfolios.create_entry(conn, world["round"], world["user"])
        intruder = make_user(conn)

    def steal(conn):
        portfolios.insert_submission(
            conn,
            submission_values(entry_id, world["round"], intruder, world["snapshot"]),
            selections_for(world["fixtures"]),
        )

    raises_db(engine, steal, "foreign key")


def test_submission_must_use_its_rounds_snapshot(engine, world):
    with transaction(engine) as conn:
        _, other_snap, _ = make_round(conn)
        entry_id = portfolios.create_entry(conn, world["round"], world["user"])
    raises_db(
        engine,
        lambda c: portfolios.insert_submission(
            c,
            submission_values(entry_id, world["round"], world["user"], other_snap),
            selections_for(world["fixtures"]),
        ),
        "foreign key",
    )


def test_selections_must_be_offers_on_the_snapshot_and_distinct(engine, world):
    with transaction(engine) as conn:
        entry_id = portfolios.create_entry(conn, world["round"], world["user"])
    values = submission_values(entry_id, world["round"], world["user"], world["snapshot"])
    bad = selections_for(world["fixtures"])
    bad[0] = dict(bad[0], outcome="AWAY")  # not offered
    raises_db(engine, lambda c: portfolios.insert_submission(c, values, bad), "foreign key")
    dup = selections_for(world["fixtures"])
    dup[1] = dict(dup[1], fixture_id=dup[0]["fixture_id"])  # same fixture twice
    raises_db(
        engine,
        lambda c: portfolios.insert_submission(
            c, submission_values(entry_id, world["round"], world["user"], world["snapshot"]), dup
        ),
    )


def test_current_submission_must_belong_to_the_entry(engine, world):
    with transaction(engine) as conn:
        other = make_user(conn)
        e1, s1 = confirm(conn, world["round"], world["snapshot"], world["fixtures"], world["user"])
        e2, s2 = confirm(conn, world["round"], world["snapshot"], world["fixtures"], other)
    # pointing entry 1 at entry 2's submission fails when the deferred key is checked
    raises_db(
        engine,
        lambda c: c.execute(
            update(entries).where(entries.c.id == e1).values(current_submission_id=s2)
        ),
        "foreign key",
    )


def test_idempotency_key_is_unique_per_user(engine, world):
    key = unique("click-") + "-0000000000"
    with transaction(engine) as conn:
        confirm(conn, world["round"], world["snapshot"], world["fixtures"], world["user"], key=key)
        assert portfolios.find_submission_by_key(conn, world["user"], key) is not None
    with transaction(engine) as conn:
        entry_id = portfolios.lock_entry(conn, world["round"], world["user"]).id

    raises_db(
        engine,
        lambda c: portfolios.insert_submission(
            c,
            submission_values(
                entry_id, world["round"], world["user"], world["snapshot"], version=2, key=key
            ),
            selections_for(world["fixtures"]),
        ),
        "submissions_user_id_idempotency_key_key",
    )


def test_optimistic_version_detects_concurrent_change(engine, world):
    with transaction(engine) as conn:
        entry_id, sub = confirm(
            conn, world["round"], world["snapshot"], world["fixtures"], world["user"]
        )
        assert not portfolios.set_current_submission(conn, entry_id, sub, expected_version=0)
        assert portfolios.set_current_submission(conn, entry_id, sub, expected_version=1)


def test_withdrawn_entry_has_no_current_submission(engine, world):
    with transaction(engine) as conn:
        entry_id, _ = confirm(
            conn, world["round"], world["snapshot"], world["fixtures"], world["user"]
        )
    raises_db(
        engine,
        lambda c: c.execute(
            update(entries).where(entries.c.id == entry_id).values(state="withdrawn")
        ),
        "check",
    )
    with transaction(engine) as conn:
        assert portfolios.set_current_submission(conn, entry_id, None, 1, state="withdrawn")
        portfolios.add_event(conn, entry_id, "withdrawn", actor=world["user"])


# ---------------------------------------------------------------- deadlines (database clock)
def test_no_submission_after_the_deadline(engine):
    with transaction(engine) as conn:
        uid = make_user(conn)
        rid, snap, fids = make_round(conn, deadline_in=timedelta(seconds=-1))
        entry_id = portfolios.create_entry(conn, rid, uid)
    raises_db(
        engine,
        lambda c: portfolios.insert_submission(
            c, submission_values(entry_id, rid, uid, snap), selections_for(fids)
        ),
        "not open for submissions",
    )


def test_no_submission_when_round_is_not_open(engine, world):
    with transaction(engine) as conn:
        conn.execute(update(rounds).where(rounds.c.id == world["round"]).values(status="locked"))
        entry_id = portfolios.create_entry(conn, world["round"], world["user"])
    raises_db(
        engine,
        lambda c: portfolios.insert_submission(
            c,
            submission_values(entry_id, world["round"], world["user"], world["snapshot"]),
            selections_for(world["fixtures"]),
        ),
        "not open for submissions",
    )


def test_submitted_at_is_the_database_clock(engine, world):
    with transaction(engine) as conn:
        now = db_now(conn)
        _, sub = confirm(conn, world["round"], world["snapshot"], world["fixtures"], world["user"])
        at = conn.execute(select(submissions.c.submitted_at).where(submissions.c.id == sub))
        assert at.scalar_one() == now


# ---------------------------------------------------------------- history and set-once
def test_confirmed_portfolios_are_immutable(engine, world):
    with transaction(engine) as conn:
        _, sub = confirm(conn, world["round"], world["snapshot"], world["fixtures"], world["user"])
    raises_db(
        engine,
        lambda c: c.execute(
            update(submissions).where(submissions.c.id == sub).values(max_gross=Decimal("9999.99"))
        ),
        "insert-only",
    )
    raises_db(
        engine,
        lambda c: c.execute(submissions.delete().where(submissions.c.id == sub)),
        "insert-only",
    )
    raises_db(
        engine,
        lambda c: c.execute(text("TRUNCATE app.submission_selections CASCADE")),
        "insert-only",
    )


def test_snapshots_are_immutable(engine, world):
    raises_db(
        engine,
        lambda c: c.execute(
            text("UPDATE app.snapshot_offers SET consensus_odds = 9.99 WHERE snapshot_id = :s"),
            {"s": world["snapshot"]},
        ),
        "insert-only",
    )


def test_published_round_fields_are_set_once(engine, world):
    with transaction(engine) as conn:
        later = db_now(conn) + timedelta(days=1)
    raises_db(
        engine,
        lambda c: c.execute(
            update(rounds).where(rounds.c.id == world["round"]).values(deadline_at=later)
        ),
        "set once",
    )
    raises_db(
        engine,
        lambda c: c.execute(
            update(rounds).where(rounds.c.id == world["round"]).values(rules_version="settle/v2")
        ),
        "set once",
    )


def test_entry_lock_is_set_once(engine, world):
    with transaction(engine) as conn:
        entry_id, sub = confirm(
            conn, world["round"], world["snapshot"], world["fixtures"], world["user"]
        )
        now = db_now(conn)
        conn.execute(
            update(entries)
            .where(entries.c.id == entry_id)
            .values(
                locked_at=now,
                locked_submission_id=sub,
                public_name_at_lock="Ace",
                privacy_mode_at_lock="public",
            )
        )
    raises_db(
        engine,
        lambda c: c.execute(
            update(entries).where(entries.c.id == entry_id).values(public_name_at_lock="Renamed")
        ),
        "set once",
    )


def test_audit_records_are_immutable(engine):
    with transaction(engine) as conn:
        aid = ops.record_audit(
            conn, action="round.void", target_type="round", target_id="x", reason="test"
        )
    raises_db(
        engine,
        lambda c: c.execute(
            text("UPDATE app.audit_log SET reason = 'x' WHERE id = :i"), {"i": aid}
        ),
        "insert-only",
    )


def test_operator_actions_need_actor_and_reason(engine):
    raises_db(
        engine,
        lambda c: ops.record_audit(
            c, action="round.void", target_type="round", target_id="x", actor_role="operator"
        ),
        "check",
    )


# ---------------------------------------------------------------- approved rules as CHECKs
def _run(conn, round_id):
    return conn.execute(
        insert(settlement_runs)
        .values(round_id=round_id, trigger="manual")
        .returning(settlement_runs.c.id)
    ).scalar_one()


def test_d32b_exactly_half_played_cannot_pass(engine, world):
    def half(conn):
        run = _run(conn, world["round"])
        conn.execute(
            insert(round_evaluations).values(
                run_id=run,
                round_id=world["round"],
                rule="d32b-competitive",
                total_predictions=90,
                played_predictions=45,
                void_predictions=45,
                pending_predictions=0,
                ranked_entries=10,
                outcome="pass",
            )
        )

    raises_db(engine, half, "check")
    with transaction(engine) as conn:
        run = _run(conn, world["round"])
        conn.execute(
            insert(round_evaluations).values(
                run_id=run,
                round_id=world["round"],
                rule="d32b-competitive",
                total_predictions=90,
                played_predictions=46,
                void_predictions=44,
                pending_predictions=0,
                ranked_entries=10,
                outcome="pass",
            )
        )


def test_d32b_pending_predictions_mean_not_evaluated(engine, world):
    def pending(conn):
        run = _run(conn, world["round"])
        conn.execute(
            insert(round_evaluations).values(
                run_id=run,
                round_id=world["round"],
                rule="d32b-competitive",
                total_predictions=90,
                played_predictions=40,
                void_predictions=45,
                pending_predictions=5,
                ranked_entries=10,
                outcome="fail_majority",
            )
        )

    raises_db(engine, pending, "check")


def test_d32b_practice_rounds_have_no_ranked_entry_rule(engine, world):
    def practice(conn):
        run = _run(conn, world["round"])
        conn.execute(
            insert(round_evaluations).values(
                run_id=run,
                round_id=world["round"],
                rule="d32b-practice",
                total_predictions=27,
                played_predictions=20,
                void_predictions=7,
                pending_predictions=0,
                ranked_entries=2,
                outcome="fail_ranked",
            )
        )

    raises_db(engine, practice, "check")


def test_entry_settlement_net_and_all_void_refund(engine, world):
    with transaction(engine) as conn:
        entry_id, sub = confirm(
            conn, world["round"], world["snapshot"], world["fixtures"], world["user"]
        )
        run = _run(conn, world["round"])
    raises_db(
        engine,
        lambda c: c.execute(
            insert(entry_settlements).values(
                run_id=run,
                entry_id=entry_id,
                submission_id=sub,
                revision=1,
                gross=Decimal("120.00"),
                net=Decimal("21.00"),
                legs={},
                basis="settled",
                complete=True,
            )
        ),
        "check",
    )
    raises_db(
        engine,
        lambda c: c.execute(
            insert(entry_settlements).values(
                run_id=run,
                entry_id=entry_id,
                submission_id=sub,
                revision=1,
                gross=Decimal("90.00"),
                net=Decimal("-10.00"),
                legs={},
                basis="all_void",
                complete=True,
            )
        ),
        "check",
    )
    with transaction(engine) as conn:
        conn.execute(
            insert(entry_settlements).values(
                run_id=run,
                entry_id=entry_id,
                submission_id=sub,
                revision=1,
                gross=Decimal("123.45"),
                net=Decimal("23.45"),
                legs={"A": "won"},
                basis="settled",
                complete=True,
            )
        )
        got = conn.execute(
            select(entry_settlements.c.gross).where(entry_settlements.c.entry_id == entry_id)
        ).scalar_one()
        assert got == Decimal("123.45")  # exact numeric, no float rounding


def test_operator_designation_requires_actor_and_reason(engine, world):
    raises_db(
        engine,
        lambda c: c.execute(
            insert(designations).values(
                round_id=world["round"], designation="void", basis="operator"
            )
        ),
        "check",
    )
    with transaction(engine) as conn:
        conn.execute(
            insert(designations).values(
                round_id=world["round"], designation="championship", basis="deadline"
            )
        )
    raises_db(
        engine,
        lambda c: c.execute(
            insert(designations).values(
                round_id=world["round"], designation="practice", basis="deadline"
            )
        ),
        "uq_designation_deadline",
    )


def test_points_must_come_from_the_approved_schedule(engine, world):
    with transaction(engine) as conn:
        entry_id, _ = confirm(
            conn, world["round"], world["snapshot"], world["fixtures"], world["user"]
        )
        run = _run(conn, world["round"])
        des = conn.execute(
            insert(designations)
            .values(round_id=world["round"], designation="championship", basis="deadline")
            .returning(designations.c.id)
        ).scalar_one()
        sset = conn.execute(
            text(
                "INSERT INTO app.score_sets (round_id, revision, run_id, designation_id, kind) "
                "VALUES (:r, 1, :run, :d, 'championship') RETURNING id"
            ),
            {"r": world["round"], "run": run, "d": des},
        ).scalar_one()

    def score(points, gross="150.00", rank=1, recovered=True, top=True):
        return lambda c: c.execute(
            text(
                "INSERT INTO app.round_scores (score_set_id, kind, entry_id, user_id, gross, rank,"
                " points, recovered, qualifying_top10, status) VALUES (:s, 'championship', :e,"
                " :u, :g, :rk, :p, :rec, :top, 'ranked')"
            ),
            {
                "s": sset,
                "e": entry_id,
                "u": world["user"],
                "g": Decimal(gross),
                "rk": rank,
                "p": points,
                "rec": recovered,
                "top": top,
            },
        )

    raises_db(engine, score(140), "check")  # not in the schedule
    raises_db(engine, score(150, gross="99.99", recovered=False, top=True), "check")
    with transaction(engine) as conn:
        score(150)(conn)


# ---------------------------------------------------------------- privileges and rollback
def test_runtime_role_cannot_rewrite_history(engine, world):
    with transaction(engine) as conn:
        _, sub = confirm(conn, world["round"], world["snapshot"], world["fixtures"], world["user"])

    def as_app(conn):
        conn.execute(text("SET LOCAL ROLE diski9_app"))
        conn.execute(text("DELETE FROM app.submissions WHERE id = :i"), {"i": sub})

    raises_db(engine, as_app, "permission denied")


def test_runtime_role_can_insert_history(engine):
    with transaction(engine) as conn:
        conn.execute(text("SET LOCAL ROLE diski9_app"))
        ops.record_audit(conn, action="test.insert", target_type="t", target_id="1")


def test_failed_transaction_leaves_nothing_behind(engine):
    marker = unique("rollback-")
    with pytest.raises(IntegrityError), transaction(engine) as conn:
        uid = make_user(conn, username=marker)
        accounts.grant_role(conn, uid, "operator", None)
        accounts.grant_role(conn, uid, "operator", None)  # duplicate: fails
    with transaction(engine) as conn:
        assert not accounts.username_taken(conn, marker)


def test_users_table_never_holds_contact_data():
    from diski9.backend.db.schema import users

    assert {c.name for c in users.columns} == {"id", "status", "created_at", "deleted_at"}


def test_unknown_round_cannot_be_referenced(engine):
    raises_db(
        engine, lambda c: portfolios.create_entry(c, uuid.uuid4(), make_user(c)), "foreign key"
    )
