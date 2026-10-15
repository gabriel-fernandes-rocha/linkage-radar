"""Mensagens formatadas para o Telegram (HTML: negrito, links clicáveis, código em bloco)."""
from __future__ import annotations

from datetime import date
from html import escape

from common import no_dash

NUM = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]


def age_label(job: dict, today: date) -> str:
    """'publicada hoje', 'ontem', 'há 9 dias' a partir da data de publicação real da vaga."""
    pub = job.get("publicada_em")
    if not pub:
        return ""
    days = (today - date.fromisoformat(pub)).days
    return "publicada hoje" if days <= 0 else "publicada ontem" if days == 1 else f"publicada há {days} dias"


def is_fresh(job: dict, today: date, max_days: int) -> bool:
    pub = job.get("publicada_em")
    return bool(pub) and (today - date.fromisoformat(pub)).days <= max_days


def _e(text) -> str:
    return escape(no_dash(str(text or "")).strip())


def _block(i: int, j: dict, new_urls: set, d: date) -> list[str]:
    det = j.get("compat_detalhe") or {}
    req = j.get("requisitos") or {}
    local = " · ".join(x for x in (j.get("local"), det.get("local_txt")) if x)
    age = age_label(j, d)
    lines = ["", f"{NUM[i]} <b>{_e(j['titulo'])}</b>", f"🏢 {_e(j.get('empresa') or j.get('fonte'))}"]
    if local:
        lines.append(f"📍 {_e(local)}")
    lines.append(f"🎯 <b>{round(j.get('encaixe', 0) * 100)}% compatível</b>"
                 + (f" · habilidades {det['habilidades']}%" if det.get("habilidades") is not None else "")
                 + (" (estimado)" if det.get("estimado") else ""))
    if age:
        lines.append(f"🗓️ {age}" + (" · 🆕 nova no radar" if j["url"] in new_urls else ""))
    if req.get("obrigatorios"):
        lines.append(f"🧰 Pede: {_e(', '.join(req['obrigatorios'][:6]))}")
    if det.get("faltam"):
        lines.append(f"⚠️ Falta: {_e(', '.join(det['faltam'][:4]))}")
    lines.append(f'🔗 <a href="{escape(j["url"], quote=True)}">Ver vaga</a>')
    return lines


def jobs_message(rep: dict, site_url: str, open_jobs: list[dict], min_compat: float, top_n: int = 3,
                 alert: str | None = None, fresh_days: int = 2) -> str:
    d = date.fromisoformat(rep["data"])
    new_urls = {j["url"] for j in rep.get("vagas", [])}
    pool = {j["url"]: j for j in open_jobs}
    for j in rep.get("vagas", []):
        pool.setdefault(j["url"], j)
    ranked = sorted(pool.values(), key=lambda j: j.get("encaixe", 0), reverse=True)
    top = [j for j in ranked if j.get("encaixe", 0) >= min_compat][:top_n * 2]
    blocked = len(ranked) - len([j for j in ranked if j.get("encaixe", 0) >= min_compat])

    out = []
    if alert:
        out += [f"<i>{_e(alert)}</i>", ""]
    out += [f"<b>📡 Linkage Radar · {d:%d/%m}</b>",
            f"💼 {len(new_urls)} vagas novas hoje · 📋 {rep.get('vagas_abertas_total', len(pool))} abertas no seu perfil",
            ""]
    fresh = [j for j in ranked if is_fresh(j, d, fresh_days) and j.get("encaixe", 0) >= min_compat * 0.6][:3]
    if fresh:
        out.append(f"<b>🔥 PUBLICADAS NOS ÚLTIMOS {fresh_days + 1} DIAS: CANDIDATE-SE CEDO</b>")
        for i, j in enumerate(fresh):
            out += _block(i, j, new_urls, d)
        out.append("")
    top = ([j for j in top if j not in fresh] or top)[:top_n]
    if top:
        out.append(f"<b>🏆 TOP {len(top)} MAIS COMPATÍVEIS COM VOCÊ</b>" if len(top) == top_n else
                   f"<b>🏆 {len(top)} {'VAGA ACESSÍVEL' if len(top) == 1 else 'VAGAS ACESSÍVEIS'}</b>")
        for i, j in enumerate(top):
            out += _block(i, j, new_urls, d)
    elif not fresh:
        out.append("Nenhuma vaga acessível no seu perfil hoje.")
    if blocked:
        out += ["", f"<i>+{blocked} vagas abaixo de {round(min_compat * 100)}% (exigem morar/ter visto no exterior "
                    "ou fogem do perfil): veja no site</i>"]
    extras = [f"{n} {label}" for n, label in ((len(rep.get("papers", [])), "📄 papers"),
                                              (len(rep.get("linkedin", [])), "🔗 posts do LinkedIn"),
                                              (len(rep.get("eventos", [])), "📅 eventos")) if n]
    out += ["", ("No site também: " + ", ".join(extras) + ". ") if extras else "",
            f'🌐 <a href="{escape(site_url, quote=True)}">Abrir o Linkage Radar</a>']
    return "\n".join(x for x in out if x is not None)


def lesson_message(a: dict, prev: dict | None, book_line: str | None, book_link: str | None,
                   site_url: str) -> str | None:
    if not a or not a.get("gerada"):
        return None
    tipo = {"conceito": "conceito", "laboratorio": "laboratório", "revisao": "revisão ativa"}.get(a["tipo"], "")
    p = [f"<b>🎓 AULA {a['dia']} DE 365</b> · Semana {a['semana']}: {_e(a['tema'])} · {tipo}",
         f"<b>{_e(a['titulo']).upper()}</b>"]
    if book_line:
        p.append(f"📖 {_e(book_line)}")
    if book_link:
        p.append(f'🔗 <a href="{escape(book_link, quote=True)}">Abrir no livro, na página</a>')
    p.append("")
    if prev and prev.get("gabarito"):
        p += ["<b>✅ Gabarito do desafio de ontem</b>", _e(prev["gabarito"]), ""]
    p += [f"<b>🎯 Objetivo:</b> {_e(a['objetivo'])}", ""]

    def sec(title, text, code=False):
        if text:
            p.extend([f"<b>{title}</b>", f"<pre>{_e(text)}</pre>" if code else _e(text), ""])

    if a["tipo"] == "conceito":
        sec("📖 Conceito", a["conceito"])
        sec("🧮 Como funciona", a["como_funciona"])
        sec("✍️ Exemplo resolvido", a["exemplo"])
        sec("🛠️ Na prática", a["na_pratica"])
        sec("⚠️ Armadilha", a["armadilha"])
    elif a["tipo"] == "laboratorio":
        sec("🧪 Contexto", a["contexto"])
        p += ["<b>📋 Passos</b>"] + [f"{i}. {_e(s)}" for i, s in enumerate(a["passos"], 1)] + [""]
        sec("💻 Código inicial", a["codigo"], code=True)
        sec("📏 Como avaliar", a["como_avaliar"])
    else:
        sec("🗺️ Mapa da semana", a["conexao"])
        p += ["<b>❓ Responda de cabeça antes de ver as respostas</b>"]
        p += [f"{i}. {_e(q['pergunta'])}" for i, q in enumerate(a["perguntas"], 1)] + [""]
    p += ["<b>🧠 Desafio do dia</b>", _e(a["desafio"]), "<i>(o gabarito chega amanhã)</i>", ""]
    if a["tipo"] == "revisao":
        p += ["<b>🔑 Respostas</b>"] + [f'<tg-spoiler>{i}. {_e(q["resposta"])}</tg-spoiler>'
                                       for i, q in enumerate(a["perguntas"], 1)] + [""]
    if a.get("fontes"):
        p += [f"<i>📚 {_e('; '.join(a['fontes']))}</i>", ""]
    p.append(f'🌐 <a href="{escape(site_url, quote=True)}">Aulas anteriores no site</a>')
    return "\n".join(p)
