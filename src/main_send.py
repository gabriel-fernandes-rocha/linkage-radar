"""Envia o resumo do dia no WhatsApp.

Uso:
    python src/main_send.py --dry-run          # só imprime a mensagem
    python src/main_send.py --date 2026-09-28  # reenviar um dia específico
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, timedelta

from common import DATA, load_config, log, today

MAX_CHARS = 2600  # o envio é dividido em partes pelo limite do CallMeBot
TOP_OPEN = 5


def _short(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _first_sentence(text: str) -> str:
    return _short((text or "").split(". ")[0].rstrip("."), 140)


def _compat(it: dict) -> str:
    return f"🎯 {round(it['encaixe'] * 100)}% compatível · " if it.get("encaixe") else ""


def _by_compat(jobs: list[dict]) -> list[dict]:
    return sorted(jobs, key=lambda j: j.get("encaixe", 0), reverse=True)


def _line(kind: str, it: dict) -> str:
    if kind in ("vagas", "abertas"):
        where = f" ({it['local']})" if it.get("local") else ""
        return f"• {_compat(it)}{_short(it['titulo'], 70)} – {it.get('empresa', '')}{where} {it['url']}"
    if kind == "eventos":
        when = f" ({it['data']})" if it.get("data") else ""
        return f"• [Evento] {_short(it['titulo'], 80)}{when} {it['url']}"
    if kind == "papers":
        resumo = _short(_first_sentence(it.get("resumo", "")), 90)
        return f"• [Paper] {_short(it['titulo'], 80)}" + (f" – {resumo}" if resumo else "") + f" {it['url']}"
    return f"• [LinkedIn] {_short(_first_sentence(it.get('resumo') or it['titulo']), 90)} {it['url']}"


TITLES = {
    "vagas": "💼 VAGAS NOVAS (mais compatíveis primeiro)",
    "abertas": "📋 VAGAS ABERTAS MAIS COMPATÍVEIS COM VOCÊ",
    "eventos": "📅 EVENTOS NO BRASIL",
    "papers": "📄 PUBLICAÇÕES",
    "linkedin": "🔗 NO LINKEDIN",
}


def build_message(rep: dict, site_url: str, open_jobs: list[dict] | None = None) -> str:
    """Mensagem 1: vagas, eventos, papers e LinkedIn (a aula vai numa mensagem própria)."""
    d = date.fromisoformat(rep["data"])
    new_urls = {j["url"] for j in rep.get("vagas", [])}
    sections = {
        "vagas": _by_compat(rep.get("vagas", [])),
        # as abertas mais compatíveis que NÃO são de hoje (as de hoje já aparecem acima)
        "abertas": [j for j in _by_compat(open_jobs or []) if j["url"] not in new_urls][:TOP_OPEN],
        "eventos": rep.get("eventos", []),
        "papers": rep.get("papers", []),
        "linkedin": rep.get("linkedin", []),
    }
    abertas = rep.get("vagas_abertas_total", len(open_jobs or []))
    header = [
        f"📡 Linkage Radar — {d:%d/%m}",
        f"💼 Vagas novas: {len(sections['vagas'])} | 📋 Abertas no seu perfil: {abertas}",
        f"📅 Eventos: {len(sections['eventos'])} | 📄 Papers: {len(sections['papers'])} | "
        f"🔗 LinkedIn: {len(sections['linkedin'])}",
        "🎯 = compatibilidade da vaga com o seu perfil (stack, senioridade, idioma e local)",
    ]
    footer = [f"Ver tudo: {site_url}"]
    total = sum(len(v) for v in sections.values())
    if not total:
        return "\n".join(header + ["", "Nada novo hoje ✅"] + footer)

    budget = MAX_CHARS - len("\n".join(header + footer))
    body = []
    for kind, items in sections.items():
        if not items:
            continue
        block = ["", TITLES[kind]]
        shown = 0
        for it in items:
            line = _line(kind, it)
            cost = len(line) + 1 + (len("\n".join(block)) + 1 if not shown else 0)
            if cost > budget:
                break
            if not shown:
                budget -= len("\n".join(block)) + 1
            block.append(line)
            budget -= len(line) + 1
            shown += 1
        if shown:
            if shown < len(items) and kind != "abertas":
                block.append(f"(+{len(items) - shown} no site)")
            body += block
    return "\n".join(header + body + ["", *footer])


def build_lesson_message(rep: dict, site_url: str) -> str | None:
    """Mensagem 2: a aula do dia completa, para ler no próprio WhatsApp."""
    a = rep.get("aula")
    if not a or not a.get("explicacao"):
        return None
    parts = [
        f"🎓 Aula {a['dia']} de 365 — {a['titulo']}",
        f"📚 {a['modulo']}",
        "",
        a["explicacao"].strip(),
    ]
    if a.get("exemplo"):
        parts += ["", "💡 Exemplo:", a["exemplo"].strip()]
    if a.get("pergunta_reflexao"):
        parts += ["", "🤔 Para pensar:", a["pergunta_reflexao"].strip()]
    parts += ["", f"Aulas anteriores: {site_url}"]
    return "\n".join(parts)


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
    rep = load_report(cfg, args.date)
    import open_jobs

    messages = [build_message(rep, cfg["site_url"], open_jobs.load())]
    lesson_msg = build_lesson_message(rep, cfg["site_url"])
    if lesson_msg:
        messages.append(lesson_msg)

    wa = cfg.get("whatsapp", {})
    if args.dry_run or not wa.get("enabled", True):
        for i, msg in enumerate(messages, 1):
            print(f"===== MENSAGEM {i} ({len(msg)} caracteres) =====\n{msg}\n")
        return
    if wa.get("provider") == "twilio":
        from notify import twilio as provider
    else:
        from notify import callmebot as provider
    for i, msg in enumerate(messages, 1):
        if i > 1:
            time.sleep(10)
        provider.send(msg)
        log.info("mensagem %d/%d enviada (%d caracteres)", i, len(messages), len(msg))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
