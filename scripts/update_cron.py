"""Atualiza o cron (UTC) dos workflows a partir de send_time / collect_time do config.yaml.

Uso: python scripts/update_cron.py   → depois faça commit e push.
"""
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import sys

import yaml

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
cfg = yaml.safe_load((ROOT / "config.yaml").read_text("utf-8"))
tz = ZoneInfo(cfg.get("timezone", "America/Sao_Paulo"))


def to_utc(hhmm: str) -> tuple[int, int]:
    h, m = map(int, hhmm.split(":"))
    local = datetime.now(tz).replace(hour=h, minute=m, second=0, microsecond=0)
    utc = local.astimezone(ZoneInfo("UTC"))
    return utc.hour, utc.minute


def patch(workflow: str, hhmm: str):
    h, m = to_utc(hhmm)
    path = ROOT / ".github" / "workflows" / workflow
    text = path.read_text("utf-8")
    text = re.sub(r'cron: "[^"]*"(\s*#.*)?',
                  f'cron: "{m} {h} * * *"   # {hhmm} local — gerado por scripts/update_cron.py', text, count=1)
    path.write_text(text, "utf-8")
    print(f"{workflow}: {hhmm} local → {h:02d}:{m:02d} UTC")


patch("send.yml", str(cfg.get("send_time", "06:00")))
patch("collect.yml", str(cfg.get("collect_time", "23:00")))
