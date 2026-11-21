"""Phase 6C.5 Stage F3: HTTP load and consistency test against a running app (for
example ``gunicorn -w N`` on ``tools/f3_wsgi.py``) on an isolated F3 database.
Local development only; no odds-provider requests are made (the app reads the local
football store only).

    uv run python tools/phase6c5_f3_load.py idle    BASE DATA_DIR SECONDS [READERS]
    uv run python tools/phase6c5_f3_load.py publish BASE DATA_DIR DB ROUND_CODE
    uv run python tools/phase6c5_f3_load.py correct BASE DATA_DIR DB ROUND_CODE

Each reader is a separate signed-in session (the local test accounts in
DATA_DIR/accounts.json, signed in through /auth/sign-in) that repeatedly loads the
leaderboards page and My Challenge exactly as the browser does: the page GET, then
the recorded Dash callbacks (DATA_DIR/callbacks.json from ``f3_capture.js``),
including the Screener callbacks every page fires, the weekly board (default round
and page 2), the championship tab, the History tab, statistics and a drill-down.
Requests are timed with ``time.perf_counter`` (full HTTP response time); PostgreSQL
connections of the database are sampled every 0.5 s.

``publish`` and ``correct`` run the readers while another process finalises
ROUND_CODE (weekly publication and championship processing), or reopens it with
corrections and re-finalises it. Every championship-tab response is fingerprinted
(SHA-256 of the response body); for each reader the fingerprints observed must be
the complete states measured before, between and after the write, never anything
else (a mixed or partial publication would produce a different body).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp" / "f3"


def p95(xs):
    s = sorted(xs)
    return s[max(0, math.ceil(0.95 * len(s)) - 1)] if s else None


class Reader:
    def __init__(self, base, acct, calls):
        self.base, self.calls = base, calls
        self.s = requests.Session()
        self.s.headers.update({"Origin": base, "Referer": base + "/"})
        html = self.s.get(base + "/auth/sign-in", timeout=30).text
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        r = self.s.post(base + "/auth/sign-in", data={"csrf_token": token,
                        "email": acct["email"], "password": acct["password"]},
                        allow_redirects=False, timeout=30)  # fmt: skip
        if r.status_code not in (302, 303):
            raise SystemExit(f"sign-in failed: {r.status_code}")
        self.samples, self.pages, self.errors, self.champ = [], [], [], []

    def post(self, call):
        t = time.perf_counter()
        r = self.s.post(self.base + "/_dash-update-component", data=call["body"],
                        headers={"Content-Type": "application/json"}, timeout=60)  # fmt: skip
        ms = (time.perf_counter() - t) * 1000
        self.samples.append((call["name"], ms, r.status_code))
        if r.status_code not in (200, 204):
            self.errors.append(f"{call['name']}: HTTP {r.status_code}")
        return r

    def page(self, path, names):
        t0 = time.perf_counter()
        t = time.perf_counter()
        r = self.s.get(self.base + path, timeout=60)
        self.samples.append((f"GET {path}", (time.perf_counter() - t) * 1000, r.status_code))
        if r.status_code != 200:
            self.errors.append(f"GET {path}: HTTP {r.status_code}")
        for c in self.calls:
            if c["name"] in names:
                resp = self.post(c)
                if c["name"] == "championship tab" and resp.status_code == 200:
                    self.champ.append((time.time(), hashlib.sha256(resp.content).hexdigest()))
        self.pages.append((path, (time.perf_counter() - t0) * 1000))

    def champ_state(self):
        c = next(c for c in self.calls if c["name"] == "championship tab")
        return hashlib.sha256(self.post(c).content).hexdigest()


LB = ("leaderboards page", "weekly development (default round)", "weekly page 2",
      "championship tab")  # fmt: skip
ME = ("my challenge page", "history tab", "history development", "history drill-down")


def connections(db, stop, out):
    while not stop.is_set():
        try:
            n = subprocess.check_output(
                ["psql", "-h", "127.0.0.1", "-p", "5433", "-U", "postgres", "-Atc",
                 f"SELECT count(*) FROM pg_stat_activity WHERE datname = '{db}'"],
                timeout=5).decode().strip()  # fmt: skip
            out.append(int(n))
        except Exception:  # noqa: BLE001 - sampling only
            pass
        stop.wait(0.5)


def run_readers(readers, seconds, stop=None):
    stop = stop or threading.Event()
    deadline = time.monotonic() + seconds

    def loop(rd, k):
        i = k
        while not stop.is_set() and time.monotonic() < deadline:
            try:
                if i % 2 == 0:
                    rd.page("/leaderboards", LB)
                else:
                    rd.page("/challenge/me", ME)
            except Exception as exc:  # noqa: BLE001
                rd.errors.append(repr(exc)[:200])
            i += 1

    ts = [threading.Thread(target=loop, args=(rd, k)) for k, rd in enumerate(readers)]
    t0 = time.perf_counter()
    for t in ts:
        t.start()
    return ts, t0, stop


def summary(readers, wall_s, conns):
    s = [x for rd in readers for x in rd.samples]
    by = {}
    for name, ms, _ in s:
        by.setdefault(name, []).append(ms)
    lb_cb = [ms for n, ms, _ in s if n in ("weekly development (default round)",
                                           "weekly page 2", "championship tab")]  # fmt: skip
    pages = {}
    for rd in readers:
        for path, ms in rd.pages:
            pages.setdefault(path, []).append(ms)
    return {
        "readers": len(readers), "seconds": round(wall_s, 1), "requests": len(s),
        "throughput_rps": round(len(s) / wall_s, 1),
        "errors": [e for rd in readers for e in rd.errors][:20],
        "error_count": sum(len(rd.errors) for rd in readers),
        "all_requests_ms": {"median": round(statistics.median(x[1] for x in s), 1),
                            "p95": round(p95([x[1] for x in s]), 1)},
        "leaderboard_callbacks_ms": {"median": round(statistics.median(lb_cb), 1),
                                     "p95": round(p95(lb_cb), 1), "n": len(lb_cb)},
        "page_loads_ms": {p: {"median": round(statistics.median(v), 1), "p95": round(p95(v), 1),
                              "n": len(v)} for p, v in pages.items()},
        "per_request_ms": {k: {"median": round(statistics.median(v), 1), "p95": round(p95(v), 1),
                               "n": len(v)} for k, v in sorted(by.items())},
        "db_connections": {"max": max(conns) if conns else None,
                           "median": statistics.median(conns) if conns else None},
    }  # fmt: skip


def clear_rate_limits(db):
    """The app rate-limits sign-ins (HTTP 429 after a burst, as it should); like the
    browser helpers, clear the isolated F3 database's counter before each test sign-in."""
    if not db.startswith(("diski9_f3_", "diski9_f4_")):
        raise SystemExit("refused: F3/F4 databases only")
    subprocess.run(["psql", "-h", "127.0.0.1", "-p", "5433", "-U", "postgres", "-d", db, "-qc",
                    "DELETE FROM app.auth_rate_events"], check=True)  # fmt: skip


def setup(base, data_dir, n, db):
    accts = list(json.loads((Path(data_dir) / "accounts.json").read_text()).values())[:n]
    calls = json.loads((Path(data_dir) / "callbacks.json").read_text())
    readers = []
    for a in accts:
        clear_rate_limits(db)
        readers.append(Reader(base, a, calls))
    return readers


def idle(base, data_dir, seconds, n=20, db=None, label="idle"):
    readers = setup(base, data_dir, n, db)
    for rd in readers:  # warm-up: one of each page per reader
        rd.page("/leaderboards", LB)
        rd.page("/challenge/me", ME)
        rd.samples, rd.pages, rd.champ = [], [], []
    stop_c, conns = threading.Event(), []
    if db:
        threading.Thread(target=connections, args=(db, stop_c, conns), daemon=True).start()
    ts, t0, _ = run_readers(readers, seconds)
    for t in ts:
        t.join()
    stop_c.set()
    out = summary(readers, time.perf_counter() - t0, conns)
    print(json.dumps({k: v for k, v in out.items() if k != "per_request_ms"}, indent=1))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"load_{label}.json").write_text(json.dumps(out, indent=1))
    return out


WRITER = r"""
import sys, time, json
sys.path.insert(0, "tests/backend")
import champ_helpers as h
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from diski9.backend.db import BackendDatabaseSettings, make_app_engine, transaction
from diski9.backend.services import corrections as co
url = make_url("postgresql+psycopg://postgres@127.0.0.1:5433/postgres").set(database=sys.argv[1])
eng = make_app_engine(BackendDatabaseSettings(environment="development", lock_timeout_ms=10000),
                      url=url.render_as_string(hide_password=False))
with transaction(eng) as conn:
    r = conn.execute(sa.text("SELECT id, deadline_at FROM app.rounds WHERE code = :c"),
                     {"c": sys.argv[3]}).one()
    fids = sorted(conn.execute(sa.text(
        "SELECT DISTINCT s.fixture_id FROM app.submission_selections s JOIN app.entries e "
        "ON e.locked_submission_id = s.submission_id WHERE e.round_id = :r"),
        {"r": r.id}).scalars())[:9]
w = {"round": r.id, "fixtures": fids, "deadline": r.deadline_at}
op, own = h.operator(eng), h.owner(eng)
t = time.perf_counter()
if sys.argv[2] == "publish":
    h.finalise(eng, op, w)
elif sys.argv[2] == "reopen":
    h.reopen_correct(eng, own, op, w, [co.CorrectionInput(f, "FT", 2, 2) for f in fids])
else:
    h.finalise(eng, h.fresh(eng, op), w)
print(json.dumps({"step": sys.argv[2], "ms": round((time.perf_counter() - t) * 1000, 1)}))
"""


def write_step(db, step, code):
    r = subprocess.run(["uv", "run", "python", "-c", WRITER, db, step, code], cwd=ROOT,
                       capture_output=True, text=True, timeout=600)  # fmt: skip
    if r.returncode != 0:
        raise SystemExit(r.stderr[-2000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def during(base, data_dir, db, code, steps, label):
    readers = setup(base, data_dir, 20, db)
    for rd in readers:
        rd.page("/leaderboards", LB)
        rd.samples, rd.pages, rd.champ = [], [], []
    states = [{i: rd.champ_state() for i, rd in enumerate(readers)}]
    phases, writes = [], []
    stop_c, conns = threading.Event(), []
    threading.Thread(target=connections, args=(db, stop_c, conns), daemon=True).start()
    t_all = time.perf_counter()
    for step in steps:
        for rd in readers:
            rd.champ = []
        stop = threading.Event()
        ts, _, _ = run_readers(readers, 600, stop)
        time.sleep(3)  # readers running before the write starts
        writes.append(write_step(db, step, code))
        time.sleep(3)  # and after it committed
        stop.set()
        for t in ts:
            t.join()
        states.append({i: rd.champ_state() for i, rd in enumerate(readers)})
        seen = {i: {h for _, h in rd.champ} for i, rd in enumerate(readers)}
        bad = {i: len(seen[i] - {states[-2][i], states[-1][i]}) for i in seen}
        phases.append({"step": step, "write": writes[-1],
                       "championship_responses": sum(len(rd.champ) for rd in readers),
                       "readers_seeing_unexpected_state": sum(1 for v in bad.values() if v),
                       "state_changed": sum(1 for i in seen
                                            if states[-2][i] != states[-1][i])})  # fmt: skip
    stop_c.set()
    out = {"label": label, "phases": phases,
           "load": summary(readers, time.perf_counter() - t_all, conns)}  # fmt: skip
    print(json.dumps({"phases": phases, "errors": out["load"]["error_count"],
                      "leaderboard_callbacks_ms": out["load"]["leaderboard_callbacks_ms"]},
                     indent=1))  # fmt: skip
    (OUT / f"load_{label}_{db}.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "idle":
        idle(a[1], a[2], float(a[3]), int(a[4]) if len(a) > 4 else 20,
             a[5] if len(a) > 5 else None, a[6] if len(a) > 6 else "idle")  # fmt: skip
    elif a[0] == "publish":
        during(a[1], a[2], a[3], a[4], ["publish"], "publish")
    elif a[0] == "correct":
        during(a[1], a[2], a[3], a[4], ["reopen", "refinalise"], "correct")
