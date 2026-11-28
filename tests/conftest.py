from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from diski9.api_football import ApiFootballClient
from diski9.api_football.ratelimit import RateLimiter

FIXTURES = Path(__file__).parent / "fixtures"

DEFAULT_HEADERS = {
    "x-ratelimit-requests-limit": "7500",
    "x-ratelimit-requests-remaining": "7000",
    "X-RateLimit-Limit": "300",
    "X-RateLimit-Remaining": "299",
}


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def envelope(
    response: Any, *, errors: Any = None, current: int = 1, total: int = 1
) -> dict[str, Any]:
    items = response if isinstance(response, list) else [response]
    return {
        "get": "x",
        "parameters": {},
        "errors": errors if errors is not None else [],
        "results": len(items),
        "paging": {"current": current, "total": total},
        "response": response,
    }


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def make_client(
    clock: FakeClock,
) -> Callable[..., tuple[ApiFootballClient, list[httpx.Request]]]:
    """Build a client backed by a MockTransport handler; returns (client, requests)."""

    def _make(handler: Callable[[httpx.Request], httpx.Response], **kwargs: Any):
        seen: list[httpx.Request] = []

        def wrapped(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        limiter = RateLimiter(min_interval_seconds=0.0, clock=clock, sleep=clock.sleep)
        client = ApiFootballClient(
            transport=httpx.MockTransport(wrapped),
            sleep=clock.sleep,
            rate_limiter=limiter,
            backoff_seconds=1.0,
            **kwargs,
        )
        return client, seen

    return _make


def json_response(
    body: dict[str, Any], status: int = 200, headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(status, json=body, headers={**DEFAULT_HEADERS, **(headers or {})})


# ---------------------------------------------------------------- database
@pytest.fixture
def db_url(tmp_path) -> str:
    return f"sqlite:///{tmp_path / 'test.sqlite'}"


@pytest.fixture
def engine(db_url):
    """A fresh database built by running the real Alembic migrations."""
    from diski9.db import make_engine, upgrade

    upgrade(db_url)
    eng = make_engine(db_url)
    yield eng
    eng.dispose()


@pytest.fixture
def conn(engine):
    with engine.begin() as c:
        yield c


def pytest_report_header(config):  # noqa: ARG001 - reporting only (Phase 8 R2, CI #180)
    """Record the CPU and the OpenBLAS kernel in the run header: a few numerical
    reconciliation tests depend on the floating-point kernel (record §15.22)."""
    model = "unknown"
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                model = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    blas = "unknown"
    try:  # SciPy's bundled OpenBLAS (used by the optimiser): its runtime kernel
        import ctypes
        import glob
        import os

        import scipy

        libs = os.path.join(os.path.dirname(os.path.dirname(scipy.__file__)), "scipy.libs")
        found = glob.glob(os.path.join(libs, "libscipy_openblas*.so*"))
        if found:
            get = ctypes.CDLL(found[0]).scipy_openblas_get_corename
            get.restype = ctypes.c_char_p
            blas = f"scipy OpenBLAS kernel {get().decode()}"
    except Exception:  # noqa: BLE001 - a header must never fail the run
        pass
    return f"cpu: {model} | blas: {blas}"
