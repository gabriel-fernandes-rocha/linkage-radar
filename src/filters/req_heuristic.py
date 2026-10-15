"""Extrator de requisitos SEM IA (contingência): garante que toda vaga tenha compatibilidade, mesmo estimada.

Lê o texto da vaga e extrai, por regras:
- habilidades: dicionário (habilidades já vistas nas vagas + lista base), separando obrigatórias e desejáveis
  pelo marcador de seção ("nice to have", "preferred", "diferencial", "desejável"...);
- anos de experiência ("5+ years", "3 anos");
- local de contratação ("remote anywhere/worldwide", "LATAM", "Brazil", "US only", "authorized to work in");
- senioridade pelo título; inglês pelo idioma do texto; foco em ER pelos termos fortes.
O resultado é marcado como estimado (compat_detalhe.estimado = True).
"""
from __future__ import annotations

import json
import re

from common import DATA
from filters import keywords

BASE_SKILLS = [
    "Python", "SQL", "Spark", "PySpark", "Scala", "Java", "Go", "R", "Databricks", "Snowflake", "BigQuery",
    "Redshift", "AWS", "Azure", "GCP", "Kafka", "Airflow", "dbt", "Docker", "Kubernetes", "Terraform", "Git",
    "Elasticsearch", "OpenSearch", "PostgreSQL", "MySQL", "MongoDB", "Neo4j", "Graph databases", "Delta Lake",
    "Machine Learning", "Deep Learning", "PyTorch", "TensorFlow", "scikit-learn", "NLP", "LLMs", "RAG",
    "Entity Resolution", "Record Linkage", "Identity Resolution", "Entity Matching", "Deduplication",
    "Fuzzy Matching", "Master Data Management", "MDM", "Data Quality", "Data Governance", "Splink", "Zingg",
    "Senzing", "Reltio", "Informatica", "Tableau", "Power BI", "Looker", "ETL", "Data Modeling", "Statistics",
    "Probabilistic Matching", "Blocking", "Golden Record", "Knowledge Graphs", "Data Pipelines",
]
NICE_MARK = re.compile(r"(nice[- ]to[- ]have|preferred|bonus|plus:|desirable|diferencia|desej[aá]vel|"
                       r"good to have|would be a plus)", re.I)
US = r"(united states|u\.s\.|\bus\b|usa|america)"


def _skills_dict() -> list[str]:
    names = set(BASE_SKILLS)
    try:
        cache = json.loads((DATA / "skill_match.json").read_text("utf-8"))
        names |= {v["nome"] for k, v in cache.items() if not k.startswith("_") and len(v.get("nome", "")) > 1}
    except Exception:
        pass
    return sorted(names, key=len, reverse=True)


def _find(skills: list[str], text: str) -> list[str]:
    low = text.lower()
    found = []
    for s in skills:
        if re.search(rf"(?<![a-z0-9]){re.escape(s.lower())}(?![a-z0-9])", low) and \
                not any(s.lower() in f.lower() for f in found):
            found.append(s)
    return found


def extract(job: dict) -> None:
    text = f"{job.get('titulo', '')}\n{job.get('texto', '')}"
    skills = _skills_dict()
    m = NICE_MARK.search(text)
    must = _find(skills, text[: m.start()] if m else text)
    nice = [s for s in _find(skills, text[m.start():]) if s not in must] if m else []
    job["requisitos"] = {"obrigatorios": must[:15], "desejaveis": nice[:10]}

    years = [int(y) for y in re.findall(r"(\d{1,2})\+?\s*(?:years|yrs|anos)", text, re.I) if 0 < int(y) < 20]
    job["anos_experiencia_min"] = min(years) if years else None

    title = job.get("titulo", "").lower()
    job["senioridade"] = ("staff/principal" if re.search(r"(staff|principal|distinguished)", title) else
                          "gerencia" if re.search(r"(manager|head of|director|gerente)", title) else
                          "senior" if re.search(r"(senior|sênior|sr\.?|lead|líder)", title) else
                          "junior" if re.search(r"(junior|júnior|jr\.?|intern|estagi)", title) else
                          "pleno" if re.search(r"(pleno|mid)", title) else "nao_informado")

    low = (text + " " + job.get("local", "")).lower()
    remote = bool(re.search(r"(remote|remoto|home office|anywhere)", low))
    job["modalidade"] = "remoto" if remote else ("hibrido" if re.search(r"(hybrid|h[ií]brido)", low) else "nao_informado")
    if job.get("fonte") in ("InHire", "Gupy") or re.search(r"(remoto \(brasil\)|brasil|brazil)", job.get("local", "").lower()):
        loc = {"escopo": "pais", "paises": ["Brasil"], "cidades": []}
    elif re.search(r"(anywhere(?! office)|worldwide|work from anywhere|global remote|qualquer lugar)", low):
        loc = {"escopo": "global", "paises": [], "cidades": []}
    elif re.search(r"(latam|latin america|am[eé]rica latina|brazil|brasil|são paulo|salvador)", low):
        loc = {"escopo": "regiao", "paises": ["LATAM", "Brasil"], "cidades": []}
    elif re.search(rf"(authorized to work in (the )?{US}|must (be|reside) (located )?in (the )?{US}|"
                   rf"{US}[- ]only|remote[,\s(-]+{US}|{US}[,\s(-]+remote)", low):
        loc = {"escopo": "pais", "paises": ["United States"], "cidades": []}
    else:
        loc = {"escopo": "nao_informado", "paises": [], "cidades": []}
    job["local_contratacao"] = loc
    job["patrocina_visto"] = True if re.search(r"visa sponsorship (is )?(available|provided)", low) else None
    job["contratacao"] = "freelance" if "upwork" in low or "freelance" in low else "nao_informado"
    pt = len(re.findall(r"\b(de|que|para|com|você|não)\b", low))
    job["ingles"] = "nao_exigido" if pt > 15 else "fluente"
    hits = keywords._strong_hits(keywords.normalize(text))
    job["foco_er"] = 1.0 if keywords._strong_hits(keywords.normalize(job.get("titulo", ""))) else min(hits / 4, 0.8)
    job["requisitos_estimados"] = True
