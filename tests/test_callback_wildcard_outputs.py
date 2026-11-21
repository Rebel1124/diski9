"""Phase 6C.5 Stage F2: a callback whose outputs are pattern-matching wildcards
(``ALL``) must never return a bare ``no_update`` per output. Dash rejects that
with HTTP 500 ("output 0 is a wildcard multi-output"), which the F2 browser
journeys caught as console errors when pager or history buttons were re-rendered
without a click. Such callbacks raise ``PreventUpdate`` (or return lists)."""

from __future__ import annotations

import ast
from pathlib import Path

CALLBACKS = Path(__file__).resolve().parents[1] / "src/diski9/app/challenge/callbacks.py"


def _wildcard_outputs(fn: ast.FunctionDef) -> bool:
    for dec in fn.decorator_list:
        if not (isinstance(dec, ast.Call) and getattr(dec.func, "attr", "") == "callback"):
            continue
        outs = [a for a in dec.args if isinstance(a, ast.Call) and getattr(a.func, "id", "")
                == "Output"]  # fmt: skip
        if any(isinstance(n, ast.Name) and n.id == "ALL" for o in outs for n in ast.walk(o)):
            return True
    return False


def _bare(node: ast.Return) -> bool:
    v = node.value
    items = v.elts if isinstance(v, ast.Tuple) else [v]
    return bool(items) and all(isinstance(x, ast.Name) and x.id == "no_update" for x in items)


def test_wildcard_callbacks_never_return_bare_no_update():
    tree = ast.parse(CALLBACKS.read_text())
    offenders, checked = [], 0
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and _wildcard_outputs(fn):
            checked += 1
            for node in ast.walk(fn):
                if isinstance(node, ast.Return) and node.value is not None and _bare(node):
                    offenders.append(f"{fn.name}:{node.lineno}")
    assert checked >= 4  # leaderboard, history, history detail, My Challenge tabs
    assert offenders == []
