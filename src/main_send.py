"""Envia o resumo do dia no WhatsApp.

Uso:
    python src/main_send.py --dry-run          # só imprime a mensagem
    python src/main_send.py --date 2026-09-28  # reenviar um dia específico
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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


def cfg_min_compat() -> float:
    try:
        return float(load_config().get("whatsapp", {}).get("min_compat", 0.25))
    except Exception:
        return 0.25


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
    why = (it.get("compat_detalhe") or {}).get("local_txt", "")
    lines = [f"{pos}. {pct} compatível{' | NOVA' if is_new else ''}" + (f" ({_short(why, 40)})" if why else ""),
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
    min_compat = cfg_min_compat()
    ranked = _by_compat(list(pool.values()))
    top = [j for j in ranked if j.get("encaixe", 0) >= min_compat][:TOP_JOBS]
    blocked = sum(1 for j in ranked if j.get("encaixe", 0) < min_compat)
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
            lines.append(f"TOP {len(top)} MAIS COMPATÍVEIS COM VOCÊ" if len(top) == TOP_JOBS else
                         f"SÓ {len(top)} {'VAGA ACESSÍVEL' if len(top) == 1 else 'VAGAS ACESSÍVEIS'} HOJE")
            for i, job in enumerate(top, 1):
                lines += [""] + _job_lines(i, job, job["url"] in new_urls, site_url, n_skills, title_len)
        else:
            lines.append("Nenhuma vaga aberta no seu perfil hoje.")
        if blocked:
            lines += ["", f"(+{blocked} vagas abaixo de {round(min_compat * 100)}%: exigem morar/ter visto no exterior"
                          " ou fogem do seu perfil; veja no site)"]
        if with_footer:
            lines += ["", footer]
        msg = no_dash("\n".join(lines))
        if len(quote_plus(msg)) <= MAX_ENCODED:
            return msg
    return msg


PDF_OFFSET = 16  # página impressa + 16 = página do PDF do livro


def book_link(refs: list[str]) -> str | None:
    """Link para a página certa do SEU exemplar do livro (Secret BOOK_URL, só no WhatsApp; nunca no site público).
    Dropbox/OneDrive/arquivo direto: abre no visualizador de PDF do navegador já na página (#page=N)."""
    url = os.getenv("BOOK_URL", "").strip()
    m = re.search(r"p\.\s*(\d+)", " ".join(refs)) if refs else None
    if not url or not m:
        return None
    if "dropbox.com" in url:
        url = re.sub(r"[?&]dl=0", "", url) + ("&" if "?" in url else "?") + "raw=1"
    return f"{url}#page={int(m.group(1)) + PDF_OFFSET}"


def _previous_lesson(a: dict) -> dict | None:
    try:
        import lesson

        lessons = {l["dia"]: l for l in lesson.load()}
        return lessons.get(a["dia"] - 1)
    except Exception:
        return None


def build_lesson_message(rep: dict, site_url: str) -> str | None:
    """Mensagem 2: a aula do dia completa, para ler no próprio WhatsApp."""
    a = rep.get("aula")
    if not a:
        return None
    if a.get("versao") != 2:  # formato antigo
        if not a.get("explicacao"):
            return None
        return no_dash("\n".join([f"🎓 Aula {a['dia']} de 365: {a['titulo']}", "", a["explicacao"].strip(),
                                  "", f"Plataforma: {site_url}"]))
    if not a.get("gerada"):
        return None

    p = [f"🎓 AULA {a['dia']} DE 365 | Semana {a['semana']}: {a['tema']}", a["titulo"].upper()]
    book = [f for f in a.get("fontes", []) if "Christen (2012)" in f and "p." in f]
    if not book and a.get("livro"):
        book = ["Christen (2012), p. " + ", ".join(f"{x}-{y}" for x, y in a["livro"])]
    p += [f"📖 No livro: {'; '.join(book)}" if book else "📖 Tema além do livro de 2012: veja as fontes no fim"]
    link = book_link(book)
    if link:
        p += [f"🔗 Abrir no livro: {link}"]
    p += [""]
    prev = _previous_lesson(a)
    if prev and prev.get("gabarito"):
        p += ["✅ Gabarito do desafio de ontem", prev["gabarito"].strip(), ""]
    p += ["🎯 Objetivo: " + a["objetivo"].strip(), ""]

    if a["tipo"] == "conceito":
        p += ["📖 CONCEITO", a["conceito"].strip(), "",
              "🧮 COMO FUNCIONA", a["como_funciona"].strip(), "",
              "✍️ EXEMPLO RESOLVIDO", a["exemplo"].strip(), "",
              "🛠️ NA PRÁTICA", a["na_pratica"].strip(), "",
              "⚠️ ARMADILHA", a["armadilha"].strip(), ""]
    elif a["tipo"] == "laboratorio":
        p += ["🧪 CONTEXTO", a["contexto"].strip(), "", "📋 PASSOS"]
        p += [f"{i}. {s.strip()}" for i, s in enumerate(a["passos"], 1)]
        p += ["", "💻 CÓDIGO INICIAL", a["codigo"].strip(), "",
              "📏 COMO AVALIAR", a["como_avaliar"].strip(), ""]
    else:  # revisão ativa: perguntas primeiro, respostas no fim (tente responder antes de rolar)
        p += ["🗺️ MAPA DA SEMANA", a["conexao"].strip(), "", "❓ RESPONDA DE CABEÇA ANTES DE OLHAR"]
        p += [f"{i}. {q['pergunta'].strip()}" for i, q in enumerate(a["perguntas"], 1)]
        p += [""]
    p += ["🧠 DESAFIO DO DIA", a["desafio"].strip(), "(o gabarito chega amanhã)", ""]
    if a["tipo"] == "revisao":
        p += ["🔑 RESPOSTAS"] + [f"{i}. {q['resposta'].strip()}" for i, q in enumerate(a["perguntas"], 1)] + [""]
    if a.get("fontes"):
        p += ["📚 Fontes: " + "; ".join(a["fontes"]), ""]
    p += [f"Plataforma: {site_url}"]
    return no_dash("\n".join(p))


def load_report(cfg: dict, day: str | None) -> dict:
    now = today(cfg).date()
    candidates = [day] if day else [now.isoformat(), (now - timedelta(days=1)).isoformat()]
    for d in candidates:
        p = DATA / f"{d}.json"
        if p.exists():
            return json.loads(p.read_text("utf-8"))
    raise FileNotFoundError(f"nenhum relatório encontrado para {candidates}")


def _state(day: str) -> dict:
    """Progresso do envio do dia (data/sent.json). Formato antigo (sem 'concluido') = já enviado."""
    if not SENT.exists():
        return {}
    st = json.loads(SENT.read_text("utf-8"))
    if st.get("data") != day:
        return {}
    st.setdefault("concluido", True)
    return st


def _save_state(st: dict) -> None:
    SENT.write_text(json.dumps(st, ensure_ascii=False, indent=1), "utf-8")


def _already_sent(day: str) -> bool:
    return bool(_state(day).get("concluido"))


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
        send_h, send_m = map(int, str(cfg.get("send_time", "07:00")).split(":"))
        if (now.hour, now.minute) < (send_h, send_m):
            log.info("ainda não deu o horário de envio (%s)", cfg.get("send_time"))
            return
        if _already_sent(day):
            log.info("mensagens de hoje já foram enviadas")
            return
        if not (DATA / f"{day}.json").exists() and now.hour < 9:
            log.info("edição de hoje ainda não foi coletada; tento de novo na próxima execução")
            return

    wa = cfg.get("whatsapp", {})
    if wa.get("provider") == "twilio":
        from notify import twilio as provider
    else:
        from notify import callmebot as provider

    # As partes ficam salvas no estado: uma nova tentativa continua EXATAMENTE de onde parou,
    # sem reenviar o que já chegou (antes, uma falha no meio fazia a mensagem chegar repetida).
    st = _state(day) if args.agendado else {}
    if not st.get("partes"):
        rep = load_report(cfg, args.date)
        import open_jobs

        messages = [build_message(rep, cfg["site_url"], open_jobs.load())]
        lesson_msg = build_lesson_message(rep, cfg["site_url"])
        if lesson_msg:
            messages.append(lesson_msg)
        if args.dry_run or not wa.get("enabled", True):
            for i, msg in enumerate(messages, 1):
                print(f"===== MENSAGEM {i} ({len(msg)} caracteres, {len(quote_plus(msg))} codificados, "
                      f"{len(provider.split(msg)) if hasattr(provider, 'split') else 1} partes) =====\n{msg}\n")
            return
        split = getattr(provider, "split", lambda m: [m])
        st = {"data": day, "concluido": False, "partes": [split(m) for m in messages],
              "enviadas": [0] * len(messages), "inicio": now.isoformat(timespec="minutes")}
        if args.agendado:
            _save_state(st)

    for i, parts in enumerate(st["partes"]):
        done = st["enviadas"][i]
        if done >= len(parts):
            continue
        if i > 0 and done == 0:
            time.sleep(GAP_SECONDS)  # separa a mensagem da aula da mensagem de vagas
        for j in range(done, len(parts)):
            provider.send_part(parts[j])
            st["enviadas"][i] = j + 1
            if args.agendado:
                _save_state(st)
            log.info("mensagem %d parte %d/%d enviada", i + 1, j + 1, len(parts))
            if j + 1 < len(parts):
                time.sleep(provider.PART_GAP)
    st["concluido"] = True
    st["fim"] = today(cfg).isoformat(timespec="minutes")
    if args.agendado:
        _save_state(st)
    log.info("envio concluído")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
