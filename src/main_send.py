"""Envia o resumo do dia no WhatsApp.

Uso:
    python src/main_send.py --dry-run          # só imprime a mensagem
    python src/main_send.py --date 2026-09-28  # reenviar um dia específico
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import date, timedelta
from urllib.parse import quote_plus

from common import DATA, load_config, log, no_dash, today

TOP_JOBS = 3
GAP_SECONDS = 120   # intervalo entre as 2 mensagens: evita que o CallMeBot junte as duas
SENT = DATA / "sent.json"


def _short(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _by_compat(jobs: list[dict]) -> list[dict]:
    return sorted(jobs, key=lambda j: j.get("encaixe", 0), reverse=True)


def job_link(job: dict, site_url: str) -> str:
    """Link direto se for curto; senão um link curto do site que redireciona para a vaga."""
    url = job["url"]
    if len(url) <= 70:
        return url
    return f"{site_url.rstrip('/')}/#vaga-{hashlib.sha1(url.encode()).hexdigest()[:6]}"


def _job_lines(pos: int, it: dict, is_new: bool, site_url: str, n_skills: int, title_len: int) -> list[str]:
    pct = f"{round(it['encaixe'] * 100)}%" if it.get("encaixe") else "?"
    where = f" ({_short(it['local'], 28)})" if it.get("local") else ""
    company = it.get("empresa") or it.get("fonte", "")
    lines = [f"{pos}. {pct} compatível{' | NOVA' if is_new else ''}",
             f"{_short(it['titulo'], title_len)}, {_short(company, 30)}{where}"]
    must = (it.get("requisitos") or {}).get("obrigatorios", [])
    if must and n_skills:
        lines.append("Pede: " + ", ".join(must[:n_skills]))
    lines.append(job_link(it, site_url))
    return lines


def build_message(rep: dict, site_url: str, open_jobs: list[dict] | None = None) -> str:
    """Mensagem 1: status + as 3 vagas mais compatíveis, tudo em UMA mensagem do WhatsApp."""
    from notify.callmebot import MAX_ENCODED

    d = date.fromisoformat(rep["data"])
    new_urls = {j["url"] for j in rep.get("vagas", [])}
    pool = {j["url"]: j for j in (open_jobs or [])}
    for j in rep.get("vagas", []):
        pool.setdefault(j["url"], j)
    top = _by_compat(list(pool.values()))[:TOP_JOBS]
    extras = ", ".join(f"{n} {label}" for n, label in (
        (len(rep.get("papers", [])), "paper(s)"),
        (len(rep.get("linkedin", [])), "post(s)"),
        (len(rep.get("eventos", [])), "evento(s)"),
    ) if n)

    header = [f"📡 Linkage Radar {d:%d/%m}",
              f"{len(new_urls)} {'vaga nova' if len(new_urls) == 1 else 'vagas novas'} hoje | "
              f"{rep.get('vagas_abertas_total', len(pool))} abertas no seu perfil"]
    footer = (f"No site também: {extras}. " if extras else "") + f"Tudo em {site_url}"
    # vai enxugando até caber em UMA mensagem do CallMeBot
    for n_skills, title_len, with_footer in ((4, 70, True), (3, 60, True), (3, 60, False), (2, 55, False),
                                             (1, 50, False), (0, 50, False), (0, 38, False)):
        lines = header + [""]
        if top:
            lines.append("TOP 3 MAIS COMPATÍVEIS COM VOCÊ")
            for i, job in enumerate(top, 1):
                lines += [""] + _job_lines(i, job, job["url"] in new_urls, site_url, n_skills, title_len)
        else:
            lines.append("Nenhuma vaga aberta no seu perfil hoje.")
        if with_footer:
            lines += ["", footer]
        msg = no_dash("\n".join(lines))
        if len(quote_plus(msg)) <= MAX_ENCODED:
            return msg
    return msg


def build_lesson_message(rep: dict, site_url: str) -> str | None:
    """Mensagem 2: a aula do dia completa, para ler no próprio WhatsApp."""
    a = rep.get("aula")
    if not a or not a.get("explicacao"):
        return None
    parts = [
        f"🎓 Aula {a['dia']} de 365: {a['titulo']}",
        a["modulo"],
        "",
        a["explicacao"].strip(),
    ]
    if a.get("exemplo"):
        parts += ["", "Exemplo: " + a["exemplo"].strip()]
    if a.get("pergunta_reflexao"):
        parts += ["", "Para pensar: " + a["pergunta_reflexao"].strip()]
    return no_dash("\n".join(parts))


def load_report(cfg: dict, day: str | None) -> dict:
    now = today(cfg).date()
    candidates = [day] if day else [now.isoformat(), (now - timedelta(days=1)).isoformat()]
    for d in candidates:
        p = DATA / f"{d}.json"
        if p.exists():
            return json.loads(p.read_text("utf-8"))
    raise FileNotFoundError(f"nenhum relatório encontrado para {candidates}")


def _already_sent(day: str) -> bool:
    return SENT.exists() and json.loads(SENT.read_text("utf-8")).get("data") == day


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--date")
    ap.add_argument("--agendado", action="store_true",
                    help="modo do GitHub Actions: respeita o horário, espera a coleta e nunca envia 2x no dia")
    args = ap.parse_args()

    cfg = load_config()
    now = today(cfg)
    day = now.date().isoformat()
    if args.agendado:
        send_h, send_m = map(int, str(cfg.get("send_time", "06:00")).split(":"))
        if (now.hour, now.minute) < (send_h, send_m):
            log.info("ainda não deu o horário de envio (%s)", cfg.get("send_time"))
            return
        if _already_sent(day):
            log.info("mensagens de hoje já foram enviadas")
            return
        if not (DATA / f"{day}.json").exists() and now.hour < 9:
            log.info("edição de hoje ainda não foi coletada; tento de novo na próxima execução")
            return

    rep = load_report(cfg, args.date)
    import open_jobs

    messages = [build_message(rep, cfg["site_url"], open_jobs.load())]
    lesson_msg = build_lesson_message(rep, cfg["site_url"])
    if lesson_msg:
        messages.append(lesson_msg)

    wa = cfg.get("whatsapp", {})
    if args.dry_run or not wa.get("enabled", True):
        for i, msg in enumerate(messages, 1):
            print(f"===== MENSAGEM {i} ({len(msg)} caracteres, {len(quote_plus(msg))} codificados) =====\n{msg}\n")
        return
    if wa.get("provider") == "twilio":
        from notify import twilio as provider
    else:
        from notify import callmebot as provider
    for i, msg in enumerate(messages, 1):
        if i > 1:
            time.sleep(GAP_SECONDS)
        provider.send(msg)
        log.info("mensagem %d/%d enviada (%d caracteres)", i, len(messages), len(msg))
    if args.agendado:
        SENT.write_text(json.dumps({"data": day, "enviado_em": now.isoformat(timespec="minutes")}), "utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
