"""Phase 6C.4: timings of representative settlement operations (real PostgreSQL).

Creates its own database ``diski9_perf_test`` on the server of the given URL,
migrates it, builds rounds with N locked entries over 18 fixtures, records final
results, and times: the first settlement run, an idempotent rerun, a preview, a
material correction (preview + execute), a participant's own result, and an
import of 18 fixtures through the by-ID boundary (a local fake client; no network).

    uv run python tools/phase6c4_perf.py postgresql+psycopg://postgres@127.0.0.1:5433/diski9_test
"""

from __future__ import annotations

import statistics
import sys
import time
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "backend"))

from sqlalchemy import create_engine, pool, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from diski9.backend.db import (  # noqa: E402
    BackendDatabaseSettings,
    db_now,
    make_app_engine,
    migrate,
    transaction,  # noqa: E402
)


def timed(fn, n=1):
    out = []
    for _ in range(n):
        t = time.perf_counter()
        value = fn()
        out.append((time.perf_counter() - t) * 1000)
    return value, statistics.median(out)


def main(url: str) -> None:
    base = make_url(url)
    name = "diski9_perf_test"
    admin = create_engine(base.set(database="postgres"), poolclass=pool.NullPool,
                          isolation_level="AUTOCOMMIT")  # fmt: skip
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
        c.execute(text(f"CREATE DATABASE {name}"))
    target = base.set(database=name).render_as_string(hide_password=False)
    with create_engine(target, poolclass=pool.NullPool).begin() as c:
        c.execute(text("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname="
                       "'diski9_app') THEN CREATE ROLE diski9_app NOLOGIN; "
                       "END IF; END $$;"))  # fmt: skip
    migrate.upgrade(target)
    engine = make_app_engine(BackendDatabaseSettings(environment="test"), url=target)

    from settle_helpers import provider_item, settlement_worlds, shifted
    from svc_helpers import principal, wait_until

    from diski9.backend.repositories import results as repo
    from diski9.backend.services import corrections as co
    from diski9.backend.services import results as rs
    from diski9.backend.services import settlement as st
    from diski9.ingestion.results_fetch import (
        canonical_hash,
        evidence_fields,
        fetch_fixtures_by_ids,
    )

    op = principal(engine, role="operator")
    with transaction(engine) as conn:
        now = db_now(conn)
    op = replace(op, authenticated_at=now, reauthenticated_at=now, now=now)
    print(f"{'entries':>8} {'settle':>8} {'rerun':>8} {'preview':>8} {'correct':>8} "
          f"{'own':>6} {'import':>7}  (ms)")  # fmt: skip
    for n in (50, 200, 1000):
        (w,) = settlement_worlds(engine, [[shifted(k % 10) for k in range(n)]],
                                 cutoff_after=timedelta(seconds=4))  # fmt: skip
        ko = w["deadline"] + timedelta(seconds=1)
        items = {f: provider_item(f, "FT", ko=ko, h=1, a=0) for f in w["fixtures"]}
        wait_until(engine, w["deadline"] + timedelta(seconds=2))
        with transaction(engine) as conn:
            at = db_now(conn)
            for f, item in items.items():
                repo.record_evidence(conn, source="api-football", fixture_id=f, observed_at=at,
                                     raw=item, raw_hash=canonical_hash(item),
                                     fields=evidence_fields(item))  # fmt: skip
        wait_until(engine, w["cutoff"] + timedelta(milliseconds=100))
        _, t_settle = timed(lambda w=w: st.settle_round(engine, op, w["round"]))
        _, t_rerun = timed(lambda w=w: st.settle_round(engine, op, w["round"]), 3)
        _, t_prev = timed(lambda w=w: st.preview_settlement(engine, op, w["round"]), 3)
        c = co.CorrectionInput(w["fixtures"][4], "FT", 0, 2)

        def correction(w=w, c=c):
            imp = co.preview_correction(engine, op, w["round"], c)
            return co.correct_result(engine, op, w["round"], c, reason="perf", evidence="perf",
                                     confirmation=imp.token)  # fmt: skip

        _, t_corr = timed(correction)
        me = principal(engine, user_id=w["users"][0])
        _, t_own = timed(lambda w=w, me=me: st.personal_result(engine, me, w["round"]), 5)

        class Client:
            def get(self, endpoint, params, items=items):
                class R:
                    pass

                r = R()
                r.items = [items[int(i)] for i in params["ids"].split("-")]
                return r

        _, t_imp = timed(lambda w=w: rs.import_results(
            engine, op, w["round"], lambda ids: fetch_fixtures_by_ids(Client(), ids),
            full=True))  # fmt: skip
        print(f"{n:>8} {t_settle:>8.0f} {t_rerun:>8.0f} {t_prev:>8.0f} {t_corr:>8.0f} "
              f"{t_own:>6.1f} {t_imp:>7.0f}")  # fmt: skip
    engine.dispose()
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
    admin.dispose()


if __name__ == "__main__":
    main(sys.argv[1])
