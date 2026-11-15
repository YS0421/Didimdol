"""data/ 폴더의 고정 설정(6축, 계획 가정값)을 읽는다."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@lru_cache(maxsize=None)
def load_axes() -> dict:
    with open(DATA_DIR / "axes.json", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=None)
def load_planning() -> dict:
    with open(DATA_DIR / "planning.json", encoding="utf-8") as f:
        return json.load(f)


def axis_ids() -> list[str]:
    return [a["id"] for a in load_axes()["axes"]]


def axis_names() -> dict[str, str]:
    return {a["id"]: a["name"] for a in load_axes()["axes"]}
