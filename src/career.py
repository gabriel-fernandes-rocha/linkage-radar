"""Carreira: (1) pílula diária do que o mercado pede e (2) análise semanal do seu perfil vs. especialistas.

data/market_lessons.json  -> uma aula prática por dia sobre a habilidade mais pedida que você ainda não tem
data/profile_tips.json    -> sugestões para LinkedIn e currículo (semanal), com histórico
Nada disso vai para o WhatsApp: fica no site.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from common import DATA, ROOT, log, no_dash

MARKET = DATA / "market_lessons.json"
TIPS = DATA / "profile_tips.json"
CV = ROOT / "profile" / "curriculo.md"


def _load(path, default):
    return json.loads(path.read_text("utf-8")) if path.exists() else default


def _clean(obj):
    if isinstance(obj, str):
        return no_dash(obj.replace("**", "").strip())
    if isinstance(obj, list):
        return [_clean(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    return obj


def _ask(cfg: dict, system: str, user: str, schema: dict, effort: str = "low", max_tokens: int = 8000) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=cfg["llm"].get("writer_model", "claude-sonnet-5"), max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}})
    log.info("carreira: tokens in=%s out=%s", resp.usage.input_tokens, resp.usage.output_tokens)
    return _clean(json.loads(next(b.text for b in resp.content if b.type == "text")))


# --------------------------------------------------------------------------- pílula de mercado
MARKET_SYSTEM = """Você é um mentor técnico sênior. Ensine, em português do Brasil, UMA habilidade que aparece com \
frequência nas vagas de entity resolution / record linkage / MDM, para um engenheiro de dados que já domina \
Spark, Python, SQL, Elasticsearch e Splink. Objetivo: ele ficar APTO para passar na triagem e na entrevista \
dessa habilidade com o menor esforço possível, aproveitando o que já sabe. Seja prático e honesto sobre o \
nível mínimo necessário. Não invente links: cite só nomes de documentações oficiais ou cursos muito conhecidos. \
Proibido travessão (— ou –). Sem markdown."""

MARKET_SCHEMA = {
    "type": "object",
    "properties": {
        "o_que_e": {"type": "string", "description": "2 a 4 frases"},
        "por_que_pedem": {"type": "string", "description": "por que vagas de ER/linkage pedem isso"},
        "ponte_com_o_que_voce_sabe": {"type": "string", "description": "como o que ele já sabe acelera"},
        "minimo_para_ficar_apto": {"type": "array", "items": {"type": "string"}},
        "plano_rapido": {"type": "array", "items": {"type": "string"}, "description": "passos com horas estimadas"},
        "mini_projeto": {"type": "string", "description": "projeto de portfólio ligado a entity resolution"},
        "como_colocar_no_curriculo": {"type": "string", "description": "1 bullet de currículo pronto, honesto"},
        "perguntas_de_entrevista": {"type": "array", "items": {
            "type": "object", "properties": {"pergunta": {"type": "string"}, "resposta": {"type": "string"}},
            "required": ["pergunta", "resposta"], "additionalProperties": False}},
        "fontes_para_estudar": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["o_que_e", "por_que_pedem", "ponte_com_o_que_voce_sabe", "minimo_para_ficar_apto",
                 "plano_rapido", "mini_projeto", "como_colocar_no_curriculo", "perguntas_de_entrevista",
                 "fontes_para_estudar"],
    "additionalProperties": False,
}


def _pick_skill(cfg: dict, history: list[dict], day: str) -> dict | None:
    skills = _load(DATA / "skills.json", {})
    match = _load(DATA / "skill_match.json", {})
    ranking = (skills.get("ultimos_90_dias") or {}).get("ranking") or (skills.get("geral") or {}).get("ranking", [])
    recent = {h["habilidade"].lower() for h in history
              if h["data"] >= (date.fromisoformat(day) - timedelta(days=60)).isoformat()}
    for row in ranking:
        nivel = match.get(row["nome"].lower(), {}).get("nivel", "nao")
        if nivel != "tem" and row["nome"].lower() not in recent:
            return {**row, "nivel_atual": nivel}
    return None


def market_lesson(cfg: dict, day: str) -> dict | None:
    history = _load(MARKET, [])
    if history and history[0]["data"] == day:
        return history[0]
    pick = _pick_skill(cfg, history, day)
    if not pick:
        log.info("carreira: nenhuma habilidade nova para ensinar hoje")
        return None
    archive = _load(DATA / "jobs_archive.json", [])
    examples = [j["titulo"] for j in archive
                if pick["nome"] in (j.get("requisitos") or {}).get("obrigatorios", []) +
                (j.get("requisitos") or {}).get("desejaveis", [])][:5]
    user = (f"HABILIDADE: {pick['nome']}\n"
            f"Aparece em {pick['pct']}% das vagas do nicho ({pick['obrigatorio']}x como obrigatória, "
            f"{pick['desejavel']}x como desejável).\n"
            f"Nível atual do aluno: {pick['nivel_atual']}.\n"
            f"Vagas que pedem: {'; '.join(examples) or 'n/d'}\n\nPERFIL DO ALUNO:\n{cfg.get('perfil', '')}")
    try:
        content = _ask(cfg, MARKET_SYSTEM, user, MARKET_SCHEMA)
    except Exception as e:
        log.warning("carreira: pílula falhou (%s)", e)
        return None
    entry = {"data": day, "habilidade": pick["nome"], "pct_vagas": pick["pct"], "nivel_atual": pick["nivel_atual"],
             **content}
    MARKET.write_text(json.dumps([entry] + history[:364], ensure_ascii=False, indent=1), "utf-8")
    return entry


# --------------------------------------------------------------------------- perfil vs especialistas
TIPS_SYSTEM = """Você é um recrutador técnico internacional especializado em dados e um coach de carreira. \
Compare o currículo do candidato com (a) os perfis públicos de especialistas em entity resolution / record \
linkage e (b) o que as vagas do nicho realmente pedem. Dê sugestões CONCRETAS e prontas para copiar, honestas \
(nunca invente experiência que ele não tem), com foco em conseguir vagas remotas internacionais e no Brasil. \
LinkedIn em inglês (mercado global), com versão em português quando pedido. Proibido travessão (— ou –). \
Sem markdown."""

TIPS_SCHEMA = {
    "type": "object",
    "properties": {
        "diagnostico": {"type": "string", "description": "3 a 5 frases: onde ele está forte e o que falta"},
        "headlines_en": {"type": "array", "items": {"type": "string"}, "description": "3 opções, até 220 caracteres"},
        "headline_pt": {"type": "string"},
        "sobre_en": {"type": "string", "description": "seção About do LinkedIn, 120 a 200 palavras"},
        "competencias_linkedin": {"type": "array", "items": {"type": "string"},
                                  "description": "até 15, na ordem em que devem aparecer"},
        "bullets_experiencia": {"type": "array", "items": {
            "type": "object", "properties": {"antes": {"type": "string"}, "depois": {"type": "string"}},
            "required": ["antes", "depois"], "additionalProperties": False},
            "description": "reescritas de bullets com impacto e escala (use [X] onde faltar número real)"},
        "ajustes_curriculo": {"type": "array", "items": {"type": "string"}},
        "lacunas_prioritarias": {"type": "array", "items": {
            "type": "object", "properties": {"habilidade": {"type": "string"}, "por_que": {"type": "string"},
                                             "como_fechar": {"type": "string"}},
            "required": ["habilidade", "por_que", "como_fechar"], "additionalProperties": False}},
        "padroes_dos_especialistas": {"type": "array", "items": {"type": "string"},
                                      "description": "o que os perfis fortes destacam e ele não"},
        "palavras_chave_ats": {"type": "array", "items": {"type": "string"}},
        "plano_30_dias": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["diagnostico", "headlines_en", "headline_pt", "sobre_en", "competencias_linkedin",
                 "bullets_experiencia", "ajustes_curriculo", "lacunas_prioritarias", "padroes_dos_especialistas",
                 "palavras_chave_ats", "plano_30_dias"],
    "additionalProperties": False,
}


def profile_tips(cfg: dict, day: str, force: bool = False) -> dict | None:
    current = _load(TIPS, {})
    weekday = cfg.get("carreira", {}).get("dia_analise_perfil", 6)  # 6 = domingo
    if not force and current and (date.fromisoformat(day).weekday() != weekday or current.get("data") == day):
        return None
    people = _load(DATA / "people.json", [])
    skills = _load(DATA / "skills.json", {}).get("geral", {}).get("ranking", [])[:30]
    match = _load(DATA / "skill_match.json", {})
    open_jobs = _load(DATA / "open_jobs.json", [])
    user = "\n\n".join([
        "CURRÍCULO DO CANDIDATO:\n" + (CV.read_text("utf-8") if CV.exists() else cfg.get("perfil", "")),
        "O QUE AS VAGAS DO NICHO PEDEM (requisito, % das vagas, se ele já tem):\n" + "\n".join(
            f"- {s['nome']}: {s['pct']}% ({match.get(s['nome'].lower(), {}).get('nivel', 'nao')})" for s in skills),
        "VAGAS ABERTAS MAIS COMPATÍVEIS:\n" + "\n".join(
            f"- {j['titulo']} ({j.get('empresa', '')}), compat {round(j.get('encaixe', 0) * 100)}%"
            for j in open_jobs[:10]),
        "PERFIS PÚBLICOS DE ESPECIALISTAS (headline e trecho público):\n" + "\n".join(
            f"- {p.get('nome')}: {(p.get('perfil_publico') or p.get('resumo') or '')[:300]}" for p in people[:60]),
    ])
    try:
        content = _ask(cfg, TIPS_SYSTEM, user, TIPS_SCHEMA, effort="medium", max_tokens=12000)
    except Exception as e:
        log.warning("carreira: análise de perfil falhou (%s)", e)
        return None
    hist = ([{"data": current["data"], "diagnostico": current.get("diagnostico", "")}] if current else []) + \
        current.get("historico", [])
    tips = {"data": day, "perfis_analisados": len(people), **content, "historico": hist[:52]}
    TIPS.write_text(json.dumps(tips, ensure_ascii=False, indent=1), "utf-8")
    return tips
