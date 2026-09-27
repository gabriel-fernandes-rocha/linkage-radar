"""Envia o resumo do dia no WhatsApp.

Uso:
    python src/main_send.py --dry-run          # só imprime a mensagem
    python src/main_send.py --date 2026-09-28  # reenviar um dia específico
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta

from common import DATA, load_config, log, today

MAX_CHARS = 1500


def _short(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _first_sentence(text: str) -> str:
    return _short((text or "").split(". ")[0].rstrip("."), 140)


def build_message(rep: dict, site_url: str, top: int | None = None) -> str:
    d = date.fromisoformat(rep["data"])
    vagas, eventos, papers, posts = (rep.get(k, []) for k in ("vagas", "eventos", "papers", "linkedin"))
    lines = [
        f"📡 Linkage Radar — {d:%d/%m}",
        f"💼 Vagas: {len(vagas)} | 📅 Eventos: {len(eventos)} | 📄 Papers: {len(papers)} | 🔗 LinkedIn: {len(posts)}",
    ]
    cut = (lambda xs: xs[:top]) if top else (lambda xs: xs)
    for v in cut(vagas):
        where = f" ({v['local']})" if v.get("local") else ""
        lines.append(f"• [Vaga] {_short(v['titulo'], 70)} – {v.get('empresa', '')}{where} {v['url']}")
    for e in cut(eventos):
        when = f" ({e['data']})" if e.get("data") else ""
        lines.append(f"• [Evento] {_short(e['titulo'], 80)}{when} {e['url']}")
    for p in cut(papers):
        resumo = _first_sentence(p.get("resumo", ""))
        lines.append(f"• [Paper] {_short(p['titulo'], 90)}" + (f" – {resumo}" if resumo else "") + f" {p['url']}")
    for p in cut(posts):
        lines.append(f"• [LinkedIn] {_first_sentence(p.get('resumo') or p['titulo'])} {p['url']}")
    if not (vagas or eventos or papers or posts):
        lines.append("Nada novo hoje ✅")
    aula = rep.get("aula")
    if aula:
        hook = _first_sentence(aula.get("explicacao", ""))
        lines.append(f"🎓 Aula {aula['dia']}: {aula['titulo']}" + (f" — {hook}" if hook else ""))
    lines.append(f"Ver tudo: {site_url}")
    msg = "\n".join(lines)
    if len(msg) > MAX_CHARS and top is None:
        return build_message(rep, site_url, top=3)
    if len(msg) > MAX_CHARS and top and top > 1:
        return build_message(rep, site_url, top=top - 1)
    return msg


def load_report(cfg: dict, day: str | None) -> dict:
    now = today(cfg).date()
    candidates = [day] if day else [now.isoformat(), (now - timedelta(days=1)).isoformat()]
    for d in candidates:
        p = DATA / f"{d}.json"
        if p.exists():
            return json.loads(p.read_text("utf-8"))
    raise FileNotFoundError(f"nenhum relatório encontrado para {candidates}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--date")
    args = ap.parse_args()

    cfg = load_config()
    msg = build_message(load_report(cfg, args.date), cfg["site_url"])
    wa = cfg.get("whatsapp", {})
    if args.dry_run or not wa.get("enabled", True):
        print(msg)
        print(f"\n({len(msg)} caracteres)")
        return
    if wa.get("provider") == "twilio":
        from notify import twilio as provider
    else:
        from notify import callmebot as provider
    provider.send(msg)
    log.info("mensagem enviada (%d caracteres)", len(msg))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
