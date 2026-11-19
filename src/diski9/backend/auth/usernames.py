"""Username rules (D-05): 3-24 characters, letters, digits, spaces, dot, underscore
and hyphen, starting and ending with a letter or digit; unique ignoring case;
reserved and offensive names refused (including common character substitutions).

The database repeats the length, character and case-key rules as CHECK and
UNIQUE constraints, so concurrent claims of the same name cannot both succeed.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass

PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]*[A-Za-z0-9]$")
ALIAS_PATTERN = re.compile(r"^Anonymous [0-9]{4,8}$")

RESERVED = frozenset(
    {
        "admin",
        "administrator",
        "anonymous",
        "diski",
        "diski9",
        "diskinine",
        "help",
        "lucy",
        "mod",
        "moderator",
        "null",
        "official",
        "operator",
        "owner",
        "root",
        "staff",
        "support",
        "system",
        "team",
        "undefined",
        "deleted",
        "formerparticipant",
        "privateparticipant",
        "superuser",
        "sysadmin",
    }
)
# A short starter list; the full moderation list is maintained outside the code
# before launch (operators can also rename abusive names, D-05).
OFFENSIVE = frozenset(
    {
        "fuck",
        "shit",
        "cunt",
        "bitch",
        "nigger",
        "nigga",
        "faggot",
        "retard",
        "whore",
        "slut",
        "rape",
        "nazi",
        "hitler",
        "kaffir",
        "kaffer",
        "porn",
        "dick",
        "pussy",
    }
)
# matched anywhere in the name (no legitimate name contains them)
SLURS = frozenset({"nigger", "nigga", "faggot", "cunt", "kaffir", "kaffer"})
_LEET = str.maketrans(
    {
        "0": "o",
        "1": "i",
        "3": "e",
        "4": "a",
        "5": "s",
        "7": "t",
        "8": "b",
        "@": "a",
        "$": "s",
        "!": "i",
    }
)


class UsernameError(ValueError):
    """``str(exc)`` is safe to show to the user."""


@dataclass(frozen=True)
class Username:
    display: str
    key: str  # lower-cased, used for uniqueness


def _skeleton(value: str) -> str:
    return re.sub(r"[ ._-]", "", value.lower().translate(_LEET))


def validate(raw: str) -> Username:
    value = " ".join((raw or "").split())  # trim and collapse inner whitespace
    if not 3 <= len(value) <= 24:
        raise UsernameError("Usernames must be 3 to 24 characters long.")
    if not PATTERN.match(value):
        raise UsernameError(
            "Use letters, digits, spaces, dots, underscores or hyphens, starting and "
            "ending with a letter or digit."
        )
    if re.search(r"[ ._-]{2,}", value):
        raise UsernameError("Avoid repeated separators.")
    skeleton = _skeleton(value)
    if skeleton in RESERVED or any(skeleton.startswith(r) for r in ("diski9", "admin", "lucy")):
        raise UsernameError("That username is reserved. Please choose another.")
    words = {w.translate(_LEET) for w in re.split(r"[ ._-]", value.lower()) if w}
    if any(w in skeleton for w in SLURS) or words & OFFENSIVE or skeleton in OFFENSIVE:
        raise UsernameError("That username is not allowed. Please choose another.")
    if ALIAS_PATTERN.match(value):
        raise UsernameError("That username is reserved. Please choose another.")
    return Username(value, value.lower())


def new_alias() -> str:
    """A random anonymous alias, unrelated to any account data."""
    return f"Anonymous {secrets.randbelow(900_000) + 100_000}"
