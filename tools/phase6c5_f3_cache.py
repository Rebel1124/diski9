"""Phase 6C.5 Stage F3: how long a multi-worker app keeps showing the previous current
round after a new round is published (the 3-second published-round cache in
``app.challenge.persist.Backend``, one per worker process). Local development only.

    uv run python tools/phase6c5_f3_cache.py BASE DATA_DIR DB

Four signed-in sessions poll the My Challenge route callback (as the browser does) as
fast as they can; a development round is then published through the services with a
deadline earlier than the current one, so it becomes the current round. Reported: the
time from the publication's commit until every response names the new round, and the
number of stale responses (each must still be a complete, consistent page).
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase6c5_f3_load as ld  # noqa: E402

PUBLISH = r"""
import sys, json
sys.path.insert(0, "tests/backend")
from datetime import timedelta
import champ_helpers as h
from svc_helpers import publish_dev
from sqlalchemy.engine import make_url
from diski9.backend.db import BackendDatabaseSettings, make_app_engine
url = make_url("postgresql+psycopg://postgres@127.0.0.1:5433/postgres").set(database=sys.argv[1])
eng = make_app_engine(BackendDatabaseSettings(environment="development"),
                      url=url.render_as_string(hide_password=False))
v, _ = publish_dev(eng, h.operator(eng), deadline_in=timedelta(hours=6), seed=99, fixtures=40)
print(json.dumps({"code": v.code}))
"""


def main(base, data_dir, db):
    import subprocess

    readers = ld.setup(base, data_dir, 4, db)
    route = next(c for c in readers[0].calls if c["name"] == "my challenge page"
                 and "ch-root.children" in c["output"])  # fmt: skip
    log, stop = [], threading.Event()

    def poll(rd):
        while not stop.is_set():
            r = rd.s.post(
                base + "/_dash-update-component",
                data=route["body"],
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            log.append((time.time(), r.status_code, r.text))

    ts = [threading.Thread(target=poll, args=(rd,)) for rd in readers]
    for t in ts:
        t.start()
    time.sleep(3)
    out = subprocess.run(["uv", "run", "python", "-c", PUBLISH, db], capture_output=True,
                         text=True, cwd=ld.ROOT, timeout=300)  # fmt: skip
    committed = time.time()
    code = json.loads(out.stdout.strip().splitlines()[-1])["code"]
    time.sleep(8)
    stop.set()
    for t in ts:
        t.join()
    after = [(t, s, code in body) for t, s, body in log if t >= committed]
    stale = [t for t, s, new in after if not new]
    errors = [s for _, s, _ in log if s != 200]
    res = {"new_round": code, "responses_after_commit": len(after), "stale_responses": len(stale),
           "last_stale_after_commit_s": round(max(stale) - committed, 2) if stale else 0.0,
           "errors": len(errors)}  # fmt: skip
    print(json.dumps(res, indent=1))
    (ld.OUT / "cache.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:4])
