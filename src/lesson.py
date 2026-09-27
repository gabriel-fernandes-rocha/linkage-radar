"""Aula do dia: dias desde `curriculum_start`, em loop sobre curriculum/lessons.json."""
from __future__ import annotations

import json
from datetime import date

from common import CURRICULUM


def load() -> list[dict]:
    return json.loads((CURRICULUM / "lessons.json").read_text("utf-8"))


def number_for(cfg: dict, day: date) -> int:
    start = cfg.get("curriculum_start")
    start = start if isinstance(start, date) else date.fromisoformat(str(start))
    return max((day - start).days, 0)


def for_date(cfg: dict, day: date) -> dict | None:
    lessons = load()
    if not lessons:
        return None
    return lessons[number_for(cfg, day) % len(lessons)]
