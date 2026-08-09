"""Shared helpers for ntfy push notifications."""

from __future__ import annotations


def clean_ntfy_topic(raw: str) -> str:
    """Normalise whatever landed in the NTFY_TOPIC secret to a bare topic.

    People paste full URLs ('https://ntfy.sh/mytopic'), host-prefixed
    forms ('ntfy.sh/mytopic') or add stray whitespace — all of which
    make the publish URL a 404. Accept them all: strip scheme and host,
    take the last path segment.
    """
    t = (raw or "").strip()
    if not t:
        return ""
    for scheme in ("https://", "http://"):
        if t.lower().startswith(scheme):
            t = t[len(scheme):]
    t = t.strip("/")
    if "/" in t:
        t = t.rsplit("/", 1)[-1]
    return t.strip()
