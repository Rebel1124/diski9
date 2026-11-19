"""Local demonstration of Phase 6C.3 Stages C and D (drafts and Your View) before the
pages are connected in Stage F. Development databases only.

    uv run python tools/phase6c3_demo.py --email you@example.test --code dev-...

It acts as the given (onboarded) account through the same services the pages will
use: it saves a partial draft, reads it back through a separate connection pool
(a second "device"), shows the stale-edit conflict, saves numerical Your View
adjustments for one fixture against the round's frozen baseline, and reads them
back. Nothing is confirmed or submitted. Run it again to see the saved state
persist across processes.
"""

from __future__ import annotations

import argparse
import sys

from diski9.backend.auth import privileged as pv
from diski9.backend.db import BackendDatabaseSettings, db_now, make_app_engine, transaction
from diski9.backend.services import drafts
from diski9.backend.services import rounds as svc
from diski9.backend.services import your_view as yv
from diski9.backend.services.common import ServiceError, VersionConflict, cli_principal
from diski9.challenge.config import DEFAULT_CONFIG
from diski9.challenge.structured import selection_blocks


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--email", required=True, help="an onboarded local test account")
    ap.add_argument("--code", required=True, help="an open development round (dev-...)")
    args = ap.parse_args()
    settings = BackendDatabaseSettings()
    if settings.environment == "production" or not args.code.startswith("dev-"):
        print("error: development rounds and non-production databases only", file=sys.stderr)
        return 2
    laptop, phone = make_app_engine(settings), make_app_engine(settings)
    try:
        with transaction(laptop) as conn:
            me = cli_principal(conn, pv.find_user_by_email(conn, args.email), db_now(conn))
        rid = svc.round_id_for_code(laptop, args.code)
        rnd = svc.get_round(laptop, rid)
        snap = svc.published_snapshot(laptop, rid)
        print(f"Round {rnd.code}: {rnd.status}, deadline {rnd.deadline_at:%Y-%m-%d %H:%M} UTC")

        saved = drafts.get_draft(laptop, me, rid)
        print(f"Saved draft found: {len(saved.selections)} selection(s), version {saved.version}")
        chosen = []
        for o in snap.outcomes:
            if len(chosen) == 3:
                break
            if (
                selection_blocks(chosen, snap.outcomes, snap.snapshot_at, DEFAULT_CONFIG).get(o.key)
                is None
            ):
                chosen.append(o)
        keys = [f"{o.fixture_id}|{o.market}|{o.outcome}" for o in chosen]
        d = drafts.save_draft(laptop, me, rid, keys, expected_version=saved.version)
        print(f"Laptop saved a partial draft: {len(d.selections)}/9, version {d.version}")
        seen = drafts.get_draft(phone, me, rid)
        print(f"Phone reads the same draft: {seen.keys == d.keys} (version {seen.version})")
        newer = drafts.save_draft(phone, me, rid, keys[:2], expected_version=seen.version)
        print(f"Phone removes one prediction: version {newer.version}")
        try:
            drafts.save_draft(laptop, me, rid, keys, expected_version=d.version)
        except VersionConflict as exc:
            print(f"Laptop (stale) is stopped: {exc.message}")

        f = snap.fixtures[0]
        ctx = yv.frozen_context(snap, f.fixture_id, rnd.model_version)
        current = yv.get_your_view(laptop, me, f.fixture_id, ctx)
        state = yv.zero_state()
        state["context"]["home"] = 0.25
        state["cats"]["squad"]["away"] = -0.4
        stored = yv.save_your_view(
            laptop, me, f.fixture_id, ctx, state, expected_version=current.version
        )
        back = yv.get_your_view(phone, me, f.fixture_id, ctx)
        print(
            f"Your View for {f.home} v {f.away} ({ctx}): saved version {stored.version}, "
            f"read back on the phone: {back.status}, identical: {back.state == state}"
        )
        print("Nothing was confirmed or submitted.")
        return 0
    except (ServiceError, pv.PrivilegeError) as exc:
        print(f"error: {getattr(exc, 'message', exc)}", file=sys.stderr)
        return 2
    finally:
        laptop.dispose()
        phone.dispose()


if __name__ == "__main__":
    sys.exit(main())
