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

from common import DATA, load_config, log, no_dash, today

MAX_CHARS = 2600  # o envio é dividido em partes pelo limite do CallMeBot
TOP_JOBS = 3


def _short(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _first_sentence(text: str) -> str:
    return _short((text or "").split(". ")[0].rstrip("."), 140)


def _compat(it: dict) -> str:
    return f"🎯 {round(it['encaixe'] * 100)}% compatível" if it.get("encaixe") else "🎯 compatibilidade n/d"


def _by_compat(jobs: list[dict]) -> list[dict]:
    return sorted(jobs, key=lambda j: j.get("encaixe", 0), reverse=True)


def _job_block(pos: int, it: dict, is_new: bool) -> list[str]:
    where = f" · {it['local']}" if it.get("local") else ""
    lines = [f"{pos}. {'🆕 ' if is_new else ''}{_short(it['titulo'], 80)}",
             f"   {it.get('empresa') or it.get('fonte', '')}{where}",
             f"   {_compat(it)}"]
    must = (it.get("requisitos") or {}).get("obrigatorios", [])
    if must:
        lines.append(f"   Pede: {', '.join(must[:6])}")
    lines.append(f"   {it['url']}")
    return lines


def build_message(rep: dict, site_url: str, open_jobs: list[dict] | None = None) -> str:
    """Mensagem 1: só as 3 vagas mais compatíveis (abertas, incluindo as de hoje) + contadores."""
    d = date.fromisoformat(rep["data"])
    new_urls = {j["url"] for j in rep.get("vagas", [])}
    pool = {j["url"]: j for j in (open_jobs or [])}
    for j in rep.get("vagas", []):
        pool.setdefault(j["url"], j)
    top = _by_compat(list(pool.values()))[:TOP_JOBS]

    lines = [
        f"📡 Linkage Radar | {d:%d/%m}",
        f"💼 {len(new_urls)} vagas novas hoje · 📋 {rep.get('vagas_abertas_total', len(pool))} abertas no seu perfil",
        "",
    ]
    if top:
        lines.append(f"🏆 TOP {len(top)} VAGAS MAIS COMPATÍVEIS COM VOCÊ")
        for i, job in enumerate(top, 1):
            lines += _job_block(i, job, job["url"] in new_urls) + [""]
    else:
        lines += ["Nenhuma vaga aberta no seu perfil hoje ✅", ""]
    extras = [f"{n} {label}" for n, label in (
        (len(rep.get("papers", [])), "📄 papers"),
        (len(rep.get("linkedin", [])), "🔗 posts"),
        (len(rep.get("eventos", [])), "📅 eventos"),
    ) if n]
    if extras:
        lines.append("No site também: " + " · ".join(extras))
    lines.append(f"Todas as vagas e o ranking de requisitos: {site_url}")
    return no_dash("\n".join(lines))


def build_lesson_message(rep: dict, site_url: str) -> str | None:
    """Mensagem 2: a aula do dia completa, para ler no próprio WhatsApp."""
    a = rep.get("aula")
    if not a or not a.get("explicacao"):
        return None
    parts = [
        f"🎓 Aula {a['dia']} de 365: {a['titulo']}",
        f"📚 {a['modulo']}",
        "",
        a["explicacao"].strip(),
    ]
    if a.get("exemplo"):
        parts += ["", "💡 Exemplo:", a["exemplo"].strip()]
    if a.get("pergunta_reflexao"):
        parts += ["", "🤔 Para pensar:", a["pergunta_reflexao"].strip()]
    parts += ["", f"Aulas anteriores: {site_url}"]
    return no_dash("\n".join(parts))


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
