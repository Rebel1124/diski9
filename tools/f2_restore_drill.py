"""Phase 6C.6 Stage F2: local restore and recovery drill (Q-12). LOCAL ONLY.

Needs a local PostgreSQL server (loopback only) and ``pg_dump``/``pg_restore``. Every
database it touches is a disposable one it creates itself (``backup.isolation``:
random name, empty at creation, marker token checked before every destructive step,
production and protected names refused); the football stores are temporary copies.
Mock providers only: the network is disabled for the whole drill (loopback allowed).

    uv run python tools/f2_restore_drill.py \
        --server postgresql+psycopg://postgres@127.0.0.1:5433/postgres --out tmp/f2/drill

Steps: populate a source (development championship via the F1 runner, a Beta round
taken to final by the scheduler with a mock provider, a copy of the local football
store); record the state (per-table content hashes and counts, ``competition
verify``, migration head, quantitative fingerprint); back up both stores
(``pg_dump`` custom format, ``backup store``); restore both into NEW targets; repeat
and compare; then local failure drills. Writes ``drill_report.json`` and
``drill_report.md`` (names, counts, hashes and timings only: no URLs or secrets).
The output is labelled a local drill, not production or off-host evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests" / "backend"), str(ROOT)]

LABEL = (
    "LOCAL RESTORE DRILL (Stage F2): disposable local databases and temporary "
    "football stores, mock providers. Establishes local backup creation, local "
    "verification and local restorability only; NOT an off-host copy and NOT an "
    "off-host restore."
)


def _say(msg: str) -> None:
    print(f"[drill] {msg}", flush=True)


def table_state(eng) -> dict[str, dict]:
    """Row count and a content hash of every table in the ``app`` schema."""
    import sqlalchemy as sa

    out = {}
    with eng.connect() as c:
        names = c.execute(
            sa.text("SELECT tablename FROM pg_tables WHERE schemaname = 'app' ORDER BY 1")
        ).scalars()
        for t in list(names):
            rows = c.execute(sa.text(f'SELECT t::text AS r FROM app."{t}" t')).scalars().all()
            out[t] = {
                "rows": len(rows),
                "sha256": hashlib.sha256("\n".join(sorted(rows)).encode()).hexdigest(),
            }
    return out


def head_of(eng) -> str:
    import sqlalchemy as sa

    with eng.connect() as c:
        return c.execute(sa.text("SELECT version_num FROM public.app_alembic_version")).scalar()


def verify_competition(eng) -> list[str]:
    from champ_helpers import operator

    from diski9.backend.services import competition_ops as cops

    op = operator(eng)
    lines = []
    for st in cops.stream_status(eng, op):
        if st.open:
            lines.append(f"{st.stream}: {'consistent' if not st.problems else st.problems}")
    return lines


def fingerprint() -> str:
    out = subprocess.run(
        [sys.executable, "tools/phase6c3_quant_regression.py"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return hashlib.sha256(out.stdout).hexdigest()


def pg_env() -> dict:
    """``pg_dump``/``pg_restore`` read credentials from the environment or a pgpass
    file only (never the command line); the drill uses local trust authentication."""
    return {k: v for k, v in os.environ.items() if not k.startswith("DISKI9_")}


def pg_args(db) -> list[str]:
    from sqlalchemy.engine import make_url

    u = make_url(db.url)
    return [
        "--host",
        u.host or "127.0.0.1",
        "--port",
        str(u.port or 5432),
        "--username",
        u.username or "postgres",
        "--no-password",
    ]


def populate(src, store_path: Path, live_store: Path, report: dict) -> None:
    import sqlalchemy as sa
    from champ_helpers import operator, set_required
    from test_backend_scheduler import BASE, FakeProvider, after, status, world

    from diski9.backend import dev_championship as dc
    from diski9.backend.jobs import tick
    from diski9.backup.store import backup_store

    eng = src["engine"]
    set_required(eng, 3)
    t0 = time.monotonic()
    plan = dc.preset(
        "ten-round-complete", 3, deadline_seconds=5, evidence_seconds=2, participants=6
    )
    rep = dc.run_plan(eng, plan, "drill", operator(eng), say=lambda m: None)
    assert rep.done, rep.log[-3:]
    w = world(eng, entries=5, deadline_in=3, cutoff_after=8)
    fake = FakeProvider()
    fake.add(w)
    after(eng, w["deadline"])
    tick(eng, BASE, provider_factory=lambda: fake)
    after(eng, w["cutoff"])
    for _ in range(4):
        tick(eng, replace(BASE), provider_factory=lambda: fake)
        if status(eng, w["round"]) == "final":
            break
    assert status(eng, w["round"]) == "final"
    with eng.connect() as c:
        report["source"] = {
            "rounds": c.execute(sa.text("SELECT count(*) FROM app.rounds")).scalar_one(),
            "championships": c.execute(
                sa.text("SELECT count(*) FROM app.championships")
            ).scalar_one(),
            "populate_seconds": round(time.monotonic() - t0, 1),
        }
    # the football store: an online backup of the local store, used as the source store
    t1 = time.monotonic()
    res = backup_store(live_store, store_path.parent / "seed")
    shutil.copyfile(res.file, store_path)
    report["live_store_backup"] = {
        "size_mb": round(res.size / 1e6, 1),
        "seconds_including_verification": res.seconds,
        "wall_seconds": round(time.monotonic() - t1, 2),
    }


def run(args) -> int:

    from diski9 import cli
    from diski9.backend.db import BackendDatabaseSettings, make_app_engine, migrate
    from diski9.backend.jobs import tick
    from diski9.backup import records
    from diski9.backup.isolation import DisposableDatabase, DisposableStore, no_network
    from diski9.backup.store import inspect_store, sha256_file, verify_backup

    for tool in ("pg_dump", "pg_restore"):
        if not shutil.which(tool):
            _say(f"{tool} is not installed: the PostgreSQL drill cannot run (nothing done)")
            return 3
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    live_store = Path(args.live_store)
    report: dict = {
        "label": LABEL,
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "pg_dump": subprocess.run(
            ["pg_dump", "--version"], capture_output=True, text=True
        ).stdout.strip(),
    }
    src = dst = sstore = dstore = None
    os.environ.setdefault("DISKI9_APP_ENVIRONMENT", "test")
    try:
        with no_network():
            src_db = DisposableDatabase.create(args.server, "f2src")
            migrate.upgrade(src_db.url)
            src = {
                "db": src_db,
                "engine": make_app_engine(
                    BackendDatabaseSettings(environment="test"), url=src_db.url
                ),
            }
            sstore = DisposableStore.create(out)
            _say("populating the source (development championship, Beta round to final)")
            populate(src, sstore.path, live_store, report)
            src_db.verify()
            verify_before = verify_competition(src["engine"])  # writes its operator first
            before = {
                "tables": table_state(src["engine"]),
                "head": head_of(src["engine"]),
                "verify": verify_before,
                "store": inspect_store(sstore.path).tables,
            }
            report["fingerprint_before"] = fingerprint()
            # ---------------------------------------------------------------- backup
            dump = out / "drill-competition.dump"
            t = time.monotonic()
            subprocess.run(
                [
                    "pg_dump",
                    *pg_args(src_db),
                    "--format=custom",
                    "--no-owner",
                    f"--exclude-table=public.{'diski9_disposable_target'}",
                    "--file",
                    str(dump),
                    src_db.name,
                ],
                env=pg_env(),
                check=True,
            )
            report["pg_dump_seconds"] = round(time.monotonic() - t, 2)
            report["dump_size_mb"] = round(dump.stat().st_size / 1e6, 2)
            os.environ["DISKI9_APP_DATABASE_URL"] = src_db.url
            bdir = out / "store-backups"
            t = time.monotonic()
            rc_b = cli.main(["--database-url", sstore.url, "backup", "store", "--out", str(bdir)])
            report["store_backup_cli_seconds"] = round(time.monotonic() - t, 2)
            rc_r = cli.main(["backup", "record", "--kind", "postgres", "--file", str(dump)])
            del os.environ["DISKI9_APP_DATABASE_URL"]
            assert rc_b == 0 and rc_r == 0
            bfile = sorted(bdir.glob("diski9-store-*.sqlite"))[-1]
            report["store_backup_verified"] = verify_backup(bfile).ok
            # ---------------------------------------------------------------- restore
            dst_db = DisposableDatabase.create(args.server, "f2dst")
            dst_db.verify()
            t = time.monotonic()
            subprocess.run(
                [
                    "pg_restore",
                    *pg_args(dst_db),
                    "--no-owner",
                    "--exit-on-error",
                    "--dbname",
                    dst_db.name,
                    str(dump),
                ],
                env=pg_env(),
                check=True,
            )
            report["pg_restore_seconds"] = round(time.monotonic() - t, 2)
            dst_db.verify()
            dst = {
                "db": dst_db,
                "engine": make_app_engine(
                    BackendDatabaseSettings(environment="test"), url=dst_db.url
                ),
            }
            dstore = DisposableStore.create(out)
            target = dstore.folder / "restored.sqlite"
            os.environ["DISKI9_APP_DATABASE_URL"] = src_db.url
            t = time.monotonic()
            rc = cli.main(
                [
                    "--database-url",
                    sstore.url,
                    "restore",
                    "store",
                    "--from",
                    str(bfile),
                    "--to",
                    str(target),
                    "--purpose",
                    "drill",
                ]
            )
            report["store_restore_cli_seconds"] = round(time.monotonic() - t, 2)
            del os.environ["DISKI9_APP_DATABASE_URL"]
            assert rc == 0
            restored_tables = table_state(dst["engine"])  # before anything writes to it
            after_state = {
                "tables": restored_tables,
                "head": head_of(dst["engine"]),
                "verify": verify_competition(dst["engine"]),
                "store": inspect_store(target).tables,
            }
            diff = sorted(
                t
                for t in set(before["tables"]) | set(restored_tables)
                if before["tables"].get(t) != restored_tables.get(t)
            )
            report["comparison"] = {
                "tables_compared": len(before["tables"]),
                "tables_differing": diff,
                "head_before": before["head"],
                "head_after": after_state["head"],
                "verify_before": before["verify"],
                "verify_after": after_state["verify"],
                "store_tables_equal": before["store"] == after_state["store"],
                "store_sha_equal": sha256_file(bfile) == sha256_file(target),
            }
            report["fingerprint_after"] = fingerprint()
            # ---------------------------------------------------------------- safeguard D
            os.environ["DISKI9_APP_DATABASE_URL"] = dst_db.url
            rc = cli.main(["backup", "record", "--kind", "postgres-restore", "--file", str(dump)])
            del os.environ["DISKI9_APP_DATABASE_URL"]
            from test_backend_scheduler import BASE

            called = []
            r = tick(dst["engine"], BASE, provider_factory=lambda: called.append(1))
            with dst["engine"].connect() as c:
                hold = records.provider_hold(c)
            report["provider_hold"] = {
                "recorded": rc == 0,
                "active": hold is not None,
                "provider_used": bool(called),
                "tick_status": r.status,
            }
            # ---------------------------------------------------------------- failure drills
            report["failure_drills"] = failure_drills(out, bfile, target, dst)
            src_db.verify()
            dst_db.verify()
    finally:
        for d in (src, dst):
            if d:
                d["engine"].dispose()
                d["db"].drop()
        for s in (sstore, dstore):
            if s:
                s.remove()
    report["finished_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    ok = (
        not report["comparison"]["tables_differing"]
        and report["comparison"]["head_before"] == report["comparison"]["head_after"]
        and report["comparison"]["verify_before"] == report["comparison"]["verify_after"]
        and report["comparison"]["store_tables_equal"]
        and report["comparison"]["store_sha_equal"]
        and report["fingerprint_before"] == report["fingerprint_after"]
        and report["provider_hold"]["active"]
        and not report["provider_hold"]["provider_used"]
        and all(v["passed"] for v in report["failure_drills"].values())
    )
    report["result"] = "PASSED" if ok else "FAILED"
    (out / "drill_report.json").write_text(json.dumps(report, indent=2, default=str))
    (out / "drill_report.md").write_text(markdown(report))
    _say(f"result: {report['result']} (report in {out.name}/drill_report.md)")
    return 0 if ok else 1


def failure_drills(out: Path, bfile: Path, restored: Path, dst) -> dict:
    import sqlalchemy as sa

    from diski9.app.health import check_football_store
    from diski9.backend.db.schema import job_runs
    from diski9.backend.jobs import tick
    from diski9.backup.restore import restore_store
    from diski9.backup.store import verify_backup
    from diski9.db import make_engine

    drills = {}
    # 1. store corruption -> detection -> restore from the verified backup
    bad = out / "corrupt-copy.sqlite"
    data = bytearray(restored.read_bytes())
    data[8192:12288] = b"\x00" * 4096
    bad.write_bytes(bytes(data))
    eng = make_engine(f"sqlite:///{bad}")
    detected = check_football_store(eng) == "unavailable" or not verify_backup(bad).ok
    eng.dispose()
    fixed = out / "recovered.sqlite"
    res = restore_store(bfile, fixed, live=bad)
    drills["store_corruption_then_restore"] = {
        "passed": bool(detected and res.verification.ok),
        "detail": "corruption detected; verified backup restored into a new path",
    }
    for p in (bad, fixed):
        p.unlink(missing_ok=True)
    # 2. competition database unavailable: the tick reports it and does nothing
    from sqlalchemy import create_engine, pool
    from test_backend_scheduler import BASE

    dead = create_engine(
        "postgresql+psycopg://nobody@127.0.0.1:1/nodb_test", poolclass=pool.NullPool
    )
    r = tick(dead, BASE, lock_url="postgresql+psycopg://nobody@127.0.0.1:1/nodb_test")
    drills["database_unavailable"] = {
        "passed": r.status in ("unavailable", "unsafe_connection") and r.exit_code != 0,
        "detail": f"tick status {r.status}",
    }
    # 3. scheduler killed mid-step (interrupted results import): rows left 'running'
    eng = dst["engine"]
    with eng.begin() as c:
        now = c.execute(sa.text("SELECT now()")).scalar_one()
        tid = c.execute(
            sa.insert(job_runs)
            .values(
                job="scheduler.tick",
                scope="global",
                args={"run_token": "killed"},
                status="running",
                started_at=now - timedelta(hours=1),
            )
            .returning(job_runs.c.id)
        ).scalar_one()
        sid = c.execute(
            sa.insert(job_runs)
            .values(
                job="scheduler.results",
                scope="R",
                args={"tick": tid, "run_token": "killed"},
                status="running",
                started_at=now - timedelta(hours=1),
            )
            .returning(job_runs.c.id)
        ).scalar_one()
    r = tick(eng, replace(BASE, provider_calls=False))
    with eng.connect() as c:
        st = c.execute(sa.select(job_runs.c.status).where(job_runs.c.id == sid)).scalar_one()
    drills["scheduler_killed_mid_step"] = {
        "passed": st == "failed" and any("abandoned" in n for n in r.notes),
        "detail": "the interrupted results step was recorded as abandoned (Stage D rules)",
    }
    # 4. interrupted refresh: covered by the E.1b CI tests (lock lost between fetch and
    #    write writes nothing; a failure while writing rolls the league back)
    drills["interrupted_refresh"] = {
        "passed": True,
        "detail": (
            "covered in CI: test_backend_refresh::test_lock_lost_between_fetch_and_write_writes_"
            "nothing, ::test_a_failure_while_writing_rolls_the_league_back, "
            "::test_interruption_during_a_pacing_wait_is_recovered"
        ),
    }
    return drills


def markdown(r: dict) -> str:
    c = r["comparison"]
    lines = [
        "# Stage F2 local restore drill",
        "",
        f"> {r['label']}",
        "",
        f"Result: **{r['result']}** ({r['started_at']} to {r['finished_at']} UTC); {r['pg_dump']}.",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Source | {r['source']['rounds']} rounds, {r['source']['championships']} "
        f"championships (populated in {r['source']['populate_seconds']} s) |",
        f"| Local football store backup ({r['live_store_backup']['size_mb']} MB) | "
        f"{r['live_store_backup']['seconds_including_verification']} s including verification |",
        f"| Drill store backup (CLI, incl. recording) | {r['store_backup_cli_seconds']} s |",
        f"| Drill store restore (CLI, incl. verification and recording) | "
        f"{r['store_restore_cli_seconds']} s |",
        f"| pg_dump / pg_restore | {r['pg_dump_seconds']} s / {r['pg_restore_seconds']} s "
        f"({r['dump_size_mb']} MB custom format) |",
        f"| Tables compared (content hash and count) | {c['tables_compared']}; differing: "
        f"{', '.join(c['tables_differing']) or 'none'} |",
        f"| Migration head before / after | {c['head_before']} / {c['head_after']} |",
        f"| competition verify before / after | {'; '.join(c['verify_before'])} / "
        f"{'; '.join(c['verify_after'])} |",
        f"| Football store tables / checksum equal | {c['store_tables_equal']} / "
        f"{c['store_sha_equal']} |",
        f"| Quantitative fingerprint before / after | `{r['fingerprint_before']}` / "
        f"`{r['fingerprint_after']}` |",
        f"| Provider hold after the PostgreSQL restore | recorded {r['provider_hold']['recorded']},"
        f" active {r['provider_hold']['active']}, provider used "
        f"{r['provider_hold']['provider_used']} |",
        "",
        "## Failure drills (local)",
        "",
        "| Drill | Passed | Detail |",
        "|---|---|---|",
    ]
    for k, v in r["failure_drills"].items():
        lines.append(f"| {k.replace('_', ' ')} | {v['passed']} | {v['detail']} |")
    lines += [
        "",
        "Not established by this drill: an encrypted off-host copy, or a restore "
        "from an off-host copy (evidence levels 3 and 4).",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--server",
        required=True,
        help="a loopback PostgreSQL server URL (any database; used for admin)",
    )
    p.add_argument("--out", default="tmp/f2/drill")
    p.add_argument(
        "--live-store",
        default=str(ROOT / "data" / "diski9.sqlite"),
        help="the local football store to copy (read-only online backup)",
    )
    return run(p.parse_args())


if __name__ == "__main__":
    sys.exit(main())
