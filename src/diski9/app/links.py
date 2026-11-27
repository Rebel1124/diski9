"""Links into the Match Lab (Phase 8 CP3A-3).

Every link names the fixture **and** the analytical context it was opened from, so the
Match Lab never has to guess: ``ctx=challenge`` (the published Weekly Challenge
snapshot, frozen data; with the round it belongs to) or ``ctx=research`` (the latest
available data). A fixture that appears in both lists is analysed in the context of
the list it was opened from."""

from __future__ import annotations

from urllib.parse import urlencode

CHALLENGE, RESEARCH = "challenge", "research"
CONTEXTS = (CHALLENGE, RESEARCH)


def lab_href(fixture_id: int, context: str, round_id: str | None = None) -> str:
    query = {"fixture": int(fixture_id), "ctx": context}
    if context == CHALLENGE and round_id:
        query["round"] = str(round_id)
    return "/lab?" + urlencode(query)
