"""Compatibilidade realista vaga x perfil (0-100%).

Não é um "chute" do LLM: o LLM só EXTRAI fatos da vaga (requirements.py) e classifica cada requisito
contra o currículo (cache em data/skill_match.json, para a mesma habilidade ter sempre o mesmo veredito).
A nota é calculada aqui, de forma determinística e explicável:

    compatibilidade = habilidades x senioridade x local x inglês x foco

- habilidades: cobertura dos requisitos obrigatórios (75%) e desejáveis (25%); tem=1, parcial=0,5, não=0.
  Ninguém atende 100%, então usamos 0,35 + 0,65 x cobertura (ter 0% não zera, mas pesa muito).
- senioridade: anos pedidos x anos de experiência do perfil (ou nível da vaga, se não houver anos).
- local: a trava mais forte. Vaga que só contrata em país onde você não pode trabalhar quase zera.
- inglês: exigência de fluência com inglês intermediário reduz um pouco.
- foco: vagas centradas em ER/linkage valorizam mais o seu diferencial.
"""
from __future__ import annotations

import json
from datetime import date

from common import DATA, ROOT, log

CACHE = DATA / "skill_match.json"
CREDIT = {"tem": 1.0, "parcial": 0.5, "nao": 0.0}

SYSTEM = """Você é um recrutador técnico sênior de dados e avalia, para cada habilidade/requisito, se o candidato \
abaixo JÁ ATENDE. Leia o currículo inteiro e considere as competências IMPLÍCITAS do trabalho que ele faz.

Níveis:
- "tem": usa no trabalho, é parte inevitável do que ele faz, ou domina.
- "parcial": tem base muito próxima e fica apto em poucos dias/semanas (ex.: sabe Spark e pedem Databricks;
  sabe SQL/Postgres e pedem Snowflake; sabe Python e pedem PyTorch básico).
- "nao": sem evidência no currículo nem implícita no trabalho dele.

Competências implícitas de quem faz record linkage / entity resolution em produção com Spark, Python, SQL,
Elasticsearch, Splink e RapidFuzz (considere "tem"): comparadores de strings (Levenshtein, Damerau, Jaro-Winkler,
Jaccard, q-grams, TF-IDF/cosseno), codificação fonética (Soundex, Metaphone e afins), normalização e padronização,
blocking/indexação, Fellegi-Sunter e EM, deduplicação, clustering de entidades/componentes conexos, regex,
estatística básica, avaliação (precisão/recall), pipelines/ETL em lote, NoSQL de busca (Elasticsearch), Git.
Conceitos de MDM próximos do que ele faz (golden record, survivorship, regras de match/merge): no mínimo "parcial".

Seja honesto: ferramentas/plataformas específicas que ele nunca usou (ex.: Reltio, AWS, Kafka, Neo4j) são "nao",
salvo se houver base próxima ("parcial"). Responda SOMENTE JSON:
{"<habilidade>": {"nivel": "tem|parcial|nao", "motivo": "até 12 palavras"}}"""


def years_of_experience(cfg: dict) -> float:
    start = date.fromisoformat(str(cfg.get("perfil_estruturado", {}).get("experiencia_dados_desde", "2024-01-01")))
    return round((date.today() - start).days / 365.25, 1)


def _load_cache() -> dict:
    cache = json.loads(CACHE.read_text("utf-8")) if CACHE.exists() else {}
    try:
        from common import load_config

        return apply_declared(cache, load_config())
    except Exception:
        return cache


def _profile_hash(cfg: dict) -> str:
    import hashlib

    cv = (ROOT / "profile" / "curriculo.md")
    text = cfg.get("perfil", "") + json.dumps(cfg.get("perfil_estruturado", {}), sort_keys=True, default=str) + \
        (cv.read_text("utf-8") if cv.exists() else "")
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def classify_skills(skills: set[str], cfg: dict) -> dict:
    """Garante veredito para cada habilidade (usa cache; só pergunta ao LLM as novas).
    Se o currículo/perfil mudou, TODOS os vereditos são refeitos (você estudou algo novo)."""
    cache = _load_cache()
    h = _profile_hash(cfg)
    if cache.get("_perfil_hash", {}).get("nivel") != h:
        old = [v["nome"] for k, v in cache.items() if not k.startswith("_")]
        if cache:
            log.info("compat: currículo mudou; reavaliando %d habilidades", len(old))
        cache = {"_perfil_hash": {"nome": "_perfil_hash", "nivel": h}}
        CACHE.write_text(json.dumps(cache), "utf-8")
        skills = set(skills) | set(old)
    new = sorted(s for s in skills if s.lower() not in cache and not s.startswith("_"))
    from common import LLM_STATE, note_llm_error

    if new and LLM_STATE["anthropic_down"]:  # Claude fora: classifica pela cadeia de IAs gratuitas
        from filters import providers

        cv = ROOT / "profile" / "curriculo.md"
        perfil = cv.read_text("utf-8") if cv.exists() else cfg.get("perfil", "")
        for i in range(0, len(new), 40):
            chunk = new[i:i + 40]
            text = providers.complete(cfg, SYSTEM + "\n\nCANDIDATO:\n" + perfil,
                                      json.dumps(chunk, ensure_ascii=False), max_tokens=4000)
            if not text:
                log.info("compat: nenhuma IA disponível; %d habilidades ficam para a próxima coleta", len(new) - i)
                break
            try:
                data = json.loads(text[text.index("{"): text.rindex("}") + 1])
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            for skill in chunk:
                v = data.get(skill) or data.get(skill.lower()) or {}
                if isinstance(v, str):
                    v = {"nivel": v}
                if isinstance(v, dict) and v.get("nivel") in CREDIT:
                    cache[skill.lower()] = {"nome": skill, "nivel": v["nivel"], "motivo": v.get("motivo", "")}
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
        new = []
    if new:
        import anthropic

        client = anthropic.Anthropic()
        cv = ROOT / "profile" / "curriculo.md"
        perfil = (cv.read_text("utf-8") if cv.exists() else cfg.get("perfil", "")) + \
            "\n\nHabilidades declaradas: " + ", ".join(cfg.get("perfil_estruturado", {}).get("habilidades", []))
        for i in range(0, len(new), 40):
            chunk = new[i:i + 40]
            try:
                resp = client.messages.create(
                    model=cfg["llm"].get("extract_model", cfg["llm"]["model"]), max_tokens=4000,
                    system=SYSTEM + "\n\nCANDIDATO:\n" + perfil,
                    messages=[{"role": "user", "content": json.dumps(chunk, ensure_ascii=False)}],
                    output_config={"effort": "low"})
                text = next(b.text for b in resp.content if b.type == "text")
                data = json.loads(text[text.index("{"): text.rindex("}") + 1])
            except Exception as e:
                if not note_llm_error(e):
                    log.warning("compat: classificação de habilidades falhou (%s)", e)
                continue
            for skill in chunk:
                v = data.get(skill) or {}
                nivel = v.get("nivel") if v.get("nivel") in CREDIT else "nao"
                cache[skill.lower()] = {"nome": skill, "nivel": nivel, "motivo": v.get("motivo", "")}
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
    return apply_declared(cache, cfg)


def apply_declared(cache: dict, cfg: dict) -> dict:
    """config.yaml perfil_estruturado.niveis_declarados: {"AWS": "parcial", ...} vence o veredito do modelo."""
    for name, nivel in (cfg.get("perfil_estruturado", {}).get("niveis_declarados") or {}).items():
        if nivel in CREDIT:
            cache[str(name).lower()] = {"nome": name, "nivel": nivel, "motivo": "declarado por você"}
    return cache


def _coverage(skills: list[str], cache: dict, declared: set[str] = frozenset()) -> float | None:
    """Habilidade ainda sem veredito (nenhuma IA disponível) não conta como "não tem": se está entre as
    habilidades declaradas no perfil vale "tem"; senão fica de fora até ser classificada."""
    credits = []
    for s in skills:
        v = cache.get(s.lower(), {}).get("nivel")
        if v in CREDIT:
            credits.append(CREDIT[v])
        elif s.lower() in declared:
            credits.append(1.0)
    return sum(credits) / len(credits) if credits else None


def _seniority(job: dict, years: float) -> tuple[float, str]:
    need = job.get("anos_experiencia_min")
    if isinstance(need, (int, float)) and need > 0:
        gap = need - years
        f = 1.0 if gap <= 1 else 0.8 if gap <= 2 else 0.6 if gap <= 4 else 0.4
        return f, f"pede {need:g}+ anos (você tem {years:g})"
    level = job.get("senioridade") or "nao_informado"  # IAs reserva às vezes devolvem vazio
    f = {"junior": 1.0, "pleno": 1.0, "senior": 0.75, "staff/principal": 0.45, "gerencia": 0.35}.get(level, 0.85)
    return f, f"nível {level.replace('_', ' ')}"


def _location(job: dict, cfg: dict) -> tuple[float, str]:
    perfil = cfg.get("perfil_estruturado", {})
    home_country = perfil.get("pais", "Brasil").lower()
    home_city = perfil.get("cidade", "Salvador").lower()
    loc = job.get("local_contratacao") if isinstance(job.get("local_contratacao"), dict) else {}
    scope = loc.get("escopo") or "nao_informado"
    countries = [str(c).lower() for c in (loc.get("paises") or []) if c]
    mode = job.get("modalidade") or "nao_informado"
    visa = job.get("patrocina_visto")
    contract = job.get("contratacao") or "nao_informado"
    in_home = home_country in countries or "brazil" in countries or "latam" in countries or \
        "america latina" in countries or "américa latina" in countries
    if scope == "global":
        return 1.0, "aceita candidatos do mundo todo"
    if in_home:
        if mode == "remoto":
            return 1.0, "remoto e aceita Brasil/LATAM"
        cities = [c.lower() for c in loc.get("cidades", [])]
        if home_city in " ".join(cities):
            return 1.0, f"{mode} na sua cidade"
        modo = "modalidade não informada" if mode == "nao_informado" else mode
        return (0.85 if mode == "hibrido" else 0.75), f"{modo}, no Brasil (talvez mudança de cidade)"
    if scope in ("pais", "regiao", "cidade") and countries:
        where = ", ".join(loc.get("paises", []))[:40]
        if contract in ("freelance", "contractor_global"):
            return 0.85, f"freelance/contractor ({where})"
        if mode == "remoto":
            return (0.35 if visa else 0.12), f"remoto só para {where}" + (" (patrocina visto)" if visa else
                                                                          ": exige autorização de trabalho lá")
        modo = "" if mode == "nao_informado" else f"{mode} "
        return (0.5 if visa else 0.08), f"{modo}em {where}" + (" com visto" if visa else ", sem patrocínio de visto")
    return 0.6, "local de contratação não informado"


def score(job: dict, cfg: dict, cache: dict) -> None:
    req = job.get("requisitos") or {}
    must, nice = req.get("obrigatorios", []), req.get("desejaveis", [])
    declared = {str(s).lower() for s in cfg.get("perfil_estruturado", {}).get("habilidades", [])}
    cm, cn = _coverage(must, cache, declared), _coverage(nice, cache, declared)
    if cm is None and cn is None:
        skills = 0.5
    elif cm is None:
        skills = cn
    elif cn is None:
        skills = cm
    else:
        skills = 0.75 * cm + 0.25 * cn
    f_skills = 0.35 + 0.65 * skills
    f_sen, sen_txt = _seniority(job, years_of_experience(cfg))
    f_loc, loc_txt = _location(job, cfg)
    english = job.get("ingles") or "nao_informado"
    user_en = cfg.get("perfil_estruturado", {}).get("ingles", "intermediario")
    f_en = 0.85 if english in ("fluente", "nativo") and user_en == "intermediario" else 1.0
    foco = job.get("foco_er")
    f_focus = 0.85 + 0.15 * (foco if isinstance(foco, (int, float)) else 0.5)
    total = f_skills * f_sen * f_loc * f_en * f_focus
    missing = [s for s in must if cache.get(s.lower(), {}).get("nivel") == "nao"]
    partial = [s for s in must if cache.get(s.lower(), {}).get("nivel") == "parcial"]
    job["encaixe"] = round(total, 2)
    job["compat_detalhe"] = {
        "habilidades": round(skills * 100), "senioridade": round(f_sen * 100), "local": round(f_loc * 100),
        "ingles": round(f_en * 100), "foco": round(f_focus * 100),
        "senioridade_txt": sen_txt, "local_txt": loc_txt,
        "faltam": missing[:8], "parciais": partial[:8],
        "estimado": bool(job.get("requisitos_estimados")),
    }


def score_jobs(jobs: list[dict], cfg: dict) -> None:
    jobs = [j for j in jobs if j.get("requisitos")]
    if not jobs:
        return
    skills = {s for j in jobs for s in (j["requisitos"].get("obrigatorios", []) + j["requisitos"].get("desejaveis", []))}
    cache = classify_skills(skills, cfg)
    for j in jobs:
        score(j, cfg, cache)
