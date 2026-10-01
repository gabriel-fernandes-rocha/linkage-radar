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

from common import DATA, log

CACHE = DATA / "skill_match.json"
CREDIT = {"tem": 1.0, "parcial": 0.5, "nao": 0.0}

SYSTEM = """Você avalia, para cada habilidade/requisito, se o candidato abaixo JÁ ATENDE com base no currículo.
Responda "tem" (usa no trabalho ou domina), "parcial" (tem base próxima e aprende rápido: ex. sabe Spark, \
pedem Databricks; sabe SQL e PostgreSQL, pedem Snowflake) ou "nao" (sem evidência).
Seja rigoroso e honesto: não infle. Responda SOMENTE JSON: {"<habilidade>": {"nivel": "tem|parcial|nao", \
"motivo": "até 12 palavras"}}"""


def years_of_experience(cfg: dict) -> float:
    start = date.fromisoformat(str(cfg.get("perfil_estruturado", {}).get("experiencia_dados_desde", "2024-01-01")))
    return round((date.today() - start).days / 365.25, 1)


def _load_cache() -> dict:
    return json.loads(CACHE.read_text("utf-8")) if CACHE.exists() else {}


def classify_skills(skills: set[str], cfg: dict) -> dict:
    """Garante veredito para cada habilidade (usa cache; só pergunta ao LLM as novas)."""
    cache = _load_cache()
    new = sorted(s for s in skills if s.lower() not in cache)
    if new:
        import anthropic

        client = anthropic.Anthropic()
        perfil = cfg.get("perfil", "") + "\nHabilidades declaradas: " + ", ".join(
            cfg.get("perfil_estruturado", {}).get("habilidades", []))
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
                log.warning("compat: classificação de habilidades falhou (%s)", e)
                continue
            for skill in chunk:
                v = data.get(skill) or {}
                nivel = v.get("nivel") if v.get("nivel") in CREDIT else "nao"
                cache[skill.lower()] = {"nome": skill, "nivel": nivel, "motivo": v.get("motivo", "")}
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
    return cache


def _coverage(skills: list[str], cache: dict) -> float | None:
    if not skills:
        return None
    return sum(CREDIT[cache.get(s.lower(), {}).get("nivel", "nao")] for s in skills) / len(skills)


def _seniority(job: dict, years: float) -> tuple[float, str]:
    need = job.get("anos_experiencia_min")
    if isinstance(need, (int, float)) and need > 0:
        gap = need - years
        f = 1.0 if gap <= 1 else 0.8 if gap <= 2 else 0.6 if gap <= 4 else 0.4
        return f, f"pede {need:g}+ anos (você tem {years:g})"
    level = job.get("senioridade", "nao_informado")
    f = {"junior": 1.0, "pleno": 1.0, "senior": 0.75, "staff/principal": 0.45, "gerencia": 0.35}.get(level, 0.85)
    return f, f"nível {level.replace('_', ' ')}"


def _location(job: dict, cfg: dict) -> tuple[float, str]:
    perfil = cfg.get("perfil_estruturado", {})
    home_country = perfil.get("pais", "Brasil").lower()
    home_city = perfil.get("cidade", "Salvador").lower()
    loc = job.get("local_contratacao") or {}
    scope = loc.get("escopo", "nao_informado")
    countries = [c.lower() for c in loc.get("paises", [])]
    mode = job.get("modalidade", "nao_informado")
    visa = job.get("patrocina_visto")
    contract = job.get("contratacao", "nao_informado")
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
        return (0.85 if mode == "hibrido" else 0.75), f"{mode} no Brasil (mudança de cidade)"
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
    cm, cn = _coverage(must, cache), _coverage(nice, cache)
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
    english = job.get("ingles", "nao_informado")
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
    }


def score_jobs(jobs: list[dict], cfg: dict) -> None:
    jobs = [j for j in jobs if j.get("requisitos")]
    if not jobs:
        return
    skills = {s for j in jobs for s in (j["requisitos"].get("obrigatorios", []) + j["requisitos"].get("desejaveis", []))}
    cache = classify_skills(skills, cfg)
    for j in jobs:
        score(j, cfg, cache)
