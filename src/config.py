"""Reads policy values from config/policy.toml (assumptions live there, not in code)."""
from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = ROOT / "config" / "policy.toml"
ORIGINAL_DB = ROOT / "data" / "setuhaul_original.db"


@lru_cache(maxsize=1)
def policy() -> dict:
    with open(POLICY_PATH, "rb") as f:
        return tomllib.load(f)
