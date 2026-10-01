"""Espera, dentro do GitHub Actions, até o horário de envio (send_time) e decide o que fazer.

O agendamento grátis do GitHub atrasa horas, mas um job que JÁ está rodando acorda na hora certa.
Saída (GITHUB_OUTPUT acao=...):
  enviar      -> chegou o horário e a edição do dia está pronta (ou já passou das 09h)
  pular       -> já enviado hoje
  reagendar   -> faltava mais que o limite de um job (6h): dorme o máximo e pede um novo job
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
MAX_SLEEP = 5 * 3600 + 20 * 60   # o job tem limite de 6h; deixamos folga


def output(acao: str) -> None:
    print(f"acao={acao}")
    if os.getenv("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"acao={acao}\n")


def main():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text("utf-8"))
    tz = ZoneInfo(cfg.get("timezone", "America/Sao_Paulo"))
    now = datetime.now(tz)
    h, m = map(int, str(cfg.get("send_time", "07:00")).split(":"))
    target = now.replace(hour=h, minute=m, second=5, microsecond=0)
    if now - target > timedelta(hours=12):  # já passou bastante do horário de hoje: mira o de amanhã
        target += timedelta(days=1)
    sent = ROOT / "data" / "sent.json"
    if sent.exists() and json.loads(sent.read_text("utf-8")).get("data") == target.date().isoformat():
        return output("pular")

    wait = (target - now).total_seconds()
    if wait > MAX_SLEEP:
        print(f"faltam {wait / 3600:.1f}h; dormindo {MAX_SLEEP / 3600:.1f}h e reagendando")
        time.sleep(MAX_SLEEP)
        return output("reagendar")
    if wait > 0:
        print(f"esperando {wait / 60:.0f} min até {target:%H:%M}")
        time.sleep(wait)

    # chegou a hora: se a edição do dia ainda não existe, espera a coleta até as 09h
    day = target.date().isoformat()
    deadline = target.replace(hour=9, minute=0)
    while not (ROOT / "data" / f"{day}.json").exists() and datetime.now(tz) < deadline:
        print("edição do dia ainda não coletada; aguardando 5 min")
        time.sleep(300)
        subprocess.run(["git", "pull", "--quiet", "--rebase"], cwd=ROOT, check=False)
    output("enviar")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
