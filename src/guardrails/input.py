"""Input guardrails, all plain code (architecture 8b). Lists are ASSUMPTIONS, owner: operations + safety lead."""
from __future__ import annotations

import re

PHONE_RE = re.compile(r"(?:\+?\d[\d\s\-]{8,}\d)")

SAFETY_CUES = [
    "accident", "crash", "injur", "hurt", "bleed", "fire", "smoke", "tyre burst", "tire burst",
    "tyre damaged", "tire damaged", "brake", "overturn", "unsafe", "not safe", "robbery", "stuck on highway",
    "hit by", "collision", "medical", "ambulance", "police",
    "durghatna", "chot", "aag",
]

INJECTION_CUES = [
    "ignore your rules", "ignore previous", "ignore all previous", "system prompt", "you are now",
    "developer mode", "act as", "pretend to be", "book it anyway", "override", "jailbreak",
]

YES_WORDS = {"yes", "y", "yes please", "haan", "han", "ha", "haa", "ji", "haan ji", "ok", "okay", "confirm",
             "confirmed", "book it", "done", "theek hai", "thik hai", "sure", "go ahead", "yes confirm"}


def mask_pii(text: str) -> str:
    """Replace phone-like numbers before anything is logged or sent to a model."""
    return PHONE_RE.sub("[PHONE]", text or "")


def has_safety_cue(text: str) -> bool:
    t = (text or "").lower()
    return any(c in t for c in SAFETY_CUES)


def looks_like_injection(text: str) -> bool:
    t = (text or "").lower()
    return any(c in t for c in INJECTION_CUES)


def is_explicit_yes(text: str) -> bool:
    """The driver must clearly say yes before confirm_booking runs. Code checks this, not the model."""
    t = re.sub(r"[^\w\s]", " ", (text or "").lower()).strip()
    t = re.sub(r"\s+", " ", t)
    if not t:
        return False
    if t in YES_WORDS:
        return True
    words = t.split()
    return len(words) <= 6 and words[0] in {"yes", "haan", "han", "ok", "okay", "confirm", "ji"} \
        and not any(w in words for w in ("no", "not", "nahi", "mat", "wait"))
