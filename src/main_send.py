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


def _line(kind: str, it: dict) -> str:
    if kind == "vagas":
        where = f" ({it['local']})" if it.get("local") else ""
        return f"• [Vaga] {_short(it['titulo'], 70)} – {it.get('empresa', '')}{where} {it['url']}"
    if kind == "eventos":
        when = f" ({it['data']})" if it.get("data") else ""
        return f"• [Evento] {_short(it['titulo'], 80)}{when} {it['url']}"
    if kind == "papers":
        resumo = _short(_first_sentence(it.get("resumo", "")), 90)
        return f"• [Paper] {_short(it['titulo'], 80)}" + (f" – {resumo}" if resumo else "") + f" {it['url']}"
    return f"• [LinkedIn] {_short(_first_sentence(it.get('resumo') or it['titulo']), 90)} {it['url']}"


def build_message(rep: dict, site_url: str) -> str:
    d = date.fromisoformat(rep["data"])
    kinds = ("vagas", "eventos", "papers", "linkedin")
    sections = {k: rep.get(k, []) for k in kinds}
    header = [
        f"📡 Linkage Radar — {d:%d/%m}",
        "💼 Vagas: {} | 📅 Eventos: {} | 📄 Papers: {} | 🔗 LinkedIn: {}".format(*(len(sections[k]) for k in kinds)),
    ]
    footer = []
    aula = rep.get("aula")
    if aula:
        hook = _short(_first_sentence(aula.get("explicacao", "")), 110)
        footer.append(f"🎓 Aula {aula['dia']}: {aula['titulo']}" + (f" — {hook}" if hook else ""))
    footer.append(f"Ver tudo: {site_url}")

    total = sum(len(v) for v in sections.values())
    if not total:
        return "\n".join(header + ["Nada novo hoje ✅"] + footer)

    # Preenche alternando entre seções (1º de cada, depois 2º de cada...) enquanto couber
    chosen = {k: [] for k in kinds}
    budget = MAX_CHARS - len("\n".join(header + footer)) - 40  # reserva para "(+N no site)"
    for rank in range(max(len(v) for v in sections.values())):
        for k in kinds:
            if rank < len(sections[k]):
                line = _line(k, sections[k][rank])
                if len(line) + 1 <= budget:
                    chosen[k].append(line)
                    budget -= len(line) + 1
    body = [line for k in kinds for line in chosen[k]]
    hidden = total - len(body)
    if hidden:
        body.append(f"(+{hidden} no site)")
    return "\n".join(header + body + footer)


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
