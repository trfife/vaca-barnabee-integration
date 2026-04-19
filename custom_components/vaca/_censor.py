"""Profanity censoring for STT/TTS/Intent sensor text.

Replaces matched words with same-length asterisks using word-boundary
regex. Matching is case-insensitive and covers common separators
(space, apostrophe, hyphen) between letters to catch trivial bypasses
(e.g. "f u c k"). The list intentionally covers a small set of common
English profanity; extend via VACA_EXTRA_BAD_WORDS env var (comma-
separated, optional).
"""

from __future__ import annotations

import os
import re

_BASE_WORDS: tuple[str, ...] = (
    "fuck",
    "fucker",
    "fucking",
    "shit",
    "shitty",
    "bitch",
    "bastard",
    "asshole",
    "cunt",
    "dick",
    "pussy",
    "cock",
    "slut",
    "whore",
    "motherfucker",
    "nigger",
    "nigga",
    "faggot",
    "retard",
    "retarded",
    "damn",
    "goddamn",
    "crap",
)


def _build_pattern(words: tuple[str, ...]) -> re.Pattern[str]:
    # Allow space / apostrophe / hyphen between each letter so "f u c k" also matches.
    alts = []
    for w in sorted(set(w.lower() for w in words if w), key=len, reverse=True):
        alts.append(r"[\s'\-]*".join(re.escape(ch) for ch in w))
    return re.compile(r"(?<![A-Za-z])(?:" + "|".join(alts) + r")(?![A-Za-z])", re.IGNORECASE)


def _collect_words() -> tuple[str, ...]:
    extra = os.environ.get("VACA_EXTRA_BAD_WORDS", "")
    extras = tuple(w.strip() for w in extra.split(",") if w.strip())
    return _BASE_WORDS + extras


_PATTERN: re.Pattern[str] = _build_pattern(_collect_words())


def censor(text: str | None) -> str | None:
    """Return text with any profanity masked by same-length asterisks.

    Returns the input unchanged when it is falsy or contains no match.
    """
    if not text:
        return text
    return _PATTERN.sub(lambda m: "*" * len(m.group(0)), text)


def contains_profanity(text: str | None) -> bool:
    """Return True if text contains any known profanity token."""
    if not text:
        return False
    return _PATTERN.search(text) is not None
