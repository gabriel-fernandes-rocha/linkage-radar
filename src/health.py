"""Monitor de saúde do radar: roda no fim de cada coleta e grava data/health.json.

Confere, para cada fonte, se ela respondeu e se o volume está dentro do esperado (mínimo fixo e
comparação com a mediana dos últimos 7 dias), além de cota da SerpAPI, falhas do Claude e o último envio.
Se algo estiver errado, o aviso aparece na mensagem diária e no topo do site.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date
from statistics import median

import requests

from common import DATA, RECORDER, log

HEALTH = DATA / "health.json"
HISTORY = DATA / "health_history.json"

# mínimo diário esperado de itens brutos por fonte (abaixo disso: algo quebrou)
MINIMOS = {
    "jobs/greenhouse": 300, "jobs/lever": 50, "jobs/remotive": 20, "jobs/remoteok": 20, "jobs/himalayas": 10,
    "jobs/jobicy": 10, "jobs/workable": 20, "jobs/weworkremotely": 20, "jobs/gupy": 50,
    "papers/openalex": 10,  # Google Jobs/posts dependem do orçamento da SerpAPI: não entram como mínimo
    "linkedin/posts": 3, "network/perfis": 1,
}
# sem chave de API o Semantic Scholar recusa (429) quase sempre; Adzuna só com chave; HN depende do mês
OPCIONAIS = {"papers/semantic_scholar", "jobs/adzuna", "jobs/hn_who_is_hiring", "papers/arxiv"}
NOMES = {
    "jobs/greenhouse": "Vagas Greenhouse", "jobs/lever": "Vagas Lever", "jobs/ashby": "Vagas Ashby",
    "jobs/remotive": "Vagas Remotive", "jobs/remoteok": "Vagas RemoteOK", "jobs/himalayas": "Vagas Himalayas",
    "jobs/jobicy": "Vagas Jobicy", "jobs/workable": "Vagas Workable", "jobs/weworkremotely": "Vagas We Work Remotely",
    "jobs/gupy": "Vagas Gupy (Brasil)", "jobs/serpapi_google_jobs": "Vagas Google Jobs",
    "jobs/social_posts": "Vagas em posts de redes sociais", "jobs/hn_who_is_hiring": "Vagas Hacker News",
    "papers/arxiv": "Papers arXiv", "papers/openalex": "Papers OpenAlex",
    "papers/semantic_scholar": "Papers Semantic Scholar", "linkedin/posts": "Posts do LinkedIn",
    "network/perfis": "Perfis para seguir",
}


def _counts() -> tuple[dict[str, int], list[str]]:
    counts, failures = {}, []
    for level, msg in RECORDER.records:
        if m := re.match(r"(jobs|papers)/(\w+): (\d+)$", msg):
            counts[f"{m[1]}/{m[2]}"] = int(m[3])
        elif m := re.match(r"linkedin: (\d+) candidatos", msg):
            counts["linkedin/posts"] = int(m[1])
        elif m := re.match(r"network: (\d+) perfis", msg):
            counts["network/perfis"] = max(counts.get("network/perfis", 0), int(m[1]))
        if level in ("WARNING", "ERROR") and "falhou" in msg:
            failures.append(msg[:220])
        if m := re.match(r"(jobs|papers)/(\w+) falhou", msg):
            counts[f"{m[1]}/{m[2]}"] = -1  # -1 = a fonte deu erro
    return counts, failures


def _serpapi(cfg: dict) -> dict | None:
    key = os.getenv("SERPAPI_KEY")
    if not key:
        return None
    try:  # consultar a conta não consome busca
        return requests.get("https://serpapi.com/account.json", params={"api_key": key}, timeout=30).json()
    except Exception:
        return None


def check(cfg: dict, day: str, report: dict) -> dict:
    counts, failures = _counts()
    history = json.loads(HISTORY.read_text("utf-8")) if HISTORY.exists() else {}
    checks = []

    def add(status, nome, detalhe):
        checks.append({"status": status, "nome": nome, "detalhe": detalhe})

    for key, n in sorted(counts.items()):
        nome = NOMES.get(key, key)
        if key in OPCIONAIS:  # fontes complementares instáveis: aparecem no painel, sem alarme
            continue
        past = [h[key] for d, h in sorted(history.items())[-7:] if d != day and h.get(key, -1) >= 0]
        med = median(past) if past else None
        if n < 0:
            add("problema", nome, "a fonte deu erro nesta coleta")
        elif key in MINIMOS and n < MINIMOS[key]:
            add("problema" if n == 0 else "atencao", nome, f"{n} itens (esperado pelo menos {MINIMOS[key]})")
        elif med and med >= 10 and n < 0.3 * med:
            add("atencao", nome, f"{n} itens, bem abaixo do normal ({med:.0f}/dia)")
    for key in MINIMOS:  # fonte que nem rodou
        if key not in counts:
            add("atencao", NOMES.get(key, key), "não rodou nesta coleta")

    if failures:
        credit = [f for f in failures if "credit" in f.lower() or "balance" in f.lower()]
        if credit:
            add("problema", "Créditos do Claude", "saldo da API da Anthropic acabou: recarregue em console.anthropic.com")
        judge = [f for f in failures if f.startswith(("judge", "requisitos", "carreira", "compat"))]
        if judge:
            add("problema" if len(judge) > 2 else "atencao", "Claude (juiz/extração)", f"{len(judge)} chamadas falharam")

    acc = _serpapi(cfg)
    if acc and "plan_searches_left" in acc:
        left = acc["plan_searches_left"]
        today = date.fromisoformat(day)
        days_left = (date(today.year + (today.month == 12), today.month % 12 + 1, 1) - today).days
        per_day = left // max(days_left, 1)
        status = "problema" if left == 0 else "atencao" if per_day < 3 else "ok"
        add(status, "Cota SerpAPI", f"{left} buscas restantes para {days_left} dias (~{per_day}/dia; "
                                    "LinkedIn e pessoas têm prioridade)")

    sent = DATA / "sent.json"
    if sent.exists():
        st = json.loads(sent.read_text("utf-8"))
        if st.get("concluido") is False and st.get("data") and st["data"] < day:
            add("problema", "Envio da mensagem",
                f"o envio de {st['data']} não terminou ({sum(st.get('enviadas', []))} partes enviadas)"
                + (f": {st['erro'][:150]}" if st.get("erro") else ""))

    st_report = report.get("estatisticas", {})
    if st_report.get("vagas", {}).get("brutos", 0) < 500:
        add("problema", "Coleta de vagas", f"só {st_report.get('vagas', {}).get('brutos', 0)} vagas brutas no total")

    worst = "problema" if any(c["status"] == "problema" for c in checks) else \
        "atencao" if any(c["status"] == "atencao" for c in checks) else "ok"
    result = {"data": day, "status": worst, "checks": [c for c in checks if c["status"] != "ok"] or checks,
              "fontes": counts, "falhas": failures[:20]}
    HEALTH.write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
    history[day] = counts
    HISTORY.write_text(json.dumps(dict(sorted(history.items())[-60:]), ensure_ascii=False, indent=1), "utf-8")
    log.info("saúde: %s (%d alertas)", worst, sum(c["status"] != "ok" for c in checks))
    return result


def summary_line() -> str | None:
    """Uma linha para a mensagem diária quando há problema."""
    if not HEALTH.exists():
        return None
    h = json.loads(HEALTH.read_text("utf-8"))
    bad = [c for c in h.get("checks", []) if c["status"] != "ok"]
    if not bad:
        return None
    icon = "🚨" if h["status"] == "problema" else "⚠️"
    top = "; ".join(f"{c['nome']}: {c['detalhe']}" for c in bad[:3])
    return f"{icon} Saúde do radar: {top}" + (f" (+{len(bad) - 3})" if len(bad) > 3 else "")
