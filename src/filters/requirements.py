"""Extrai ferramentas/métodos SOMENTE da seção de requisitos das vagas (Claude Haiku, em lotes).

Ignora "sobre a empresa", benefícios e descrição genérica: o objetivo é saber o que o mercado
realmente exige, sem inflar a contagem.
"""
from __future__ import annotations

import json
import re

from common import log, no_dash

SYSTEM = """Você lê descrições de vagas e extrai APENAS o que está na seção de requisitos/qualificações \
(ex.: "Requirements", "Qualifications", "What you'll need", "Must have", "Nice to have", "Requisitos", \
"Diferenciais"). Ignore descrição da empresa, benefícios, responsabilidades genéricas e texto de marketing.

Extraia ferramentas, linguagens, frameworks, bancos de dados, nuvens e MÉTODOS/técnicas \
(ex.: Python, Spark, SQL, Splink, Elasticsearch, AWS, Databricks, Fellegi-Sunter, blocking, fuzzy matching, \
entity resolution, record linkage, MDM, graph databases, LLMs, dbt, Airflow). Não extraia soft skills, \
diplomas genéricos nem anos de experiência.

Use nomes canônicos curtos e consistentes (ex.: "PySpark" e "Apache Spark" -> "Spark"; "Amazon Web Services" \
-> "AWS"; "Postgres" -> "PostgreSQL"; "ML" -> "Machine Learning").
Classifique em "obrigatorios" (exigidos) e "desejaveis" (diferenciais, nice to have, preferred, plus).
Se o texto não tiver seção de requisitos clara, extraia só o que for explicitamente exigido do candidato.
Também informe "senioridade" (junior|pleno|senior|staff/principal|gerencia|nao_informado) e \
"modalidade" (remoto|hibrido|presencial|nao_informado).

Responda SOMENTE um array JSON, um objeto por vaga, na mesma ordem:
[{"id": 0, "obrigatorios": ["..."], "desejaveis": ["..."], "senioridade": "...", "modalidade": "..."}]"""

ALIASES = {
    "pyspark": "Spark", "apache spark": "Spark", "spark sql": "Spark", "amazon web services": "AWS",
    "google cloud": "GCP", "google cloud platform": "GCP", "microsoft azure": "Azure", "postgres": "PostgreSQL",
    "ml": "Machine Learning", "machine-learning": "Machine Learning", "elastic": "Elasticsearch",
    "elastic search": "Elasticsearch", "opensearch": "Elasticsearch/OpenSearch", "k8s": "Kubernetes",
    "apache airflow": "Airflow", "apache kafka": "Kafka", "scikit learn": "scikit-learn", "sklearn": "scikit-learn",
    "golang": "Go", "mdm": "Master Data Management", "entity matching": "Entity Resolution", "entity resolution (er)": "Entity Resolution",
    "record matching": "Record Linkage", "data linkage": "Record Linkage", "llm": "LLMs", "large language models": "LLMs",
}


def canonical(name: str) -> str:
    name = no_dash(name or "").strip().strip(".")
    return ALIASES.get(name.lower(), name)


def extract(jobs: list[dict], cfg: dict, batch_size: int = 4) -> None:
    """Preenche job["requisitos"] = {"obrigatorios": [...], "desejaveis": [...]} + senioridade/modalidade."""
    import anthropic

    client = anthropic.Anthropic()
    for start in range(0, len(jobs), batch_size):
        batch = jobs[start:start + batch_size]
        payload = json.dumps([{"id": i, "titulo": j["titulo"], "texto": (j.get("texto") or "")[:6000]}
                              for i, j in enumerate(batch)], ensure_ascii=False)
        try:
            resp = client.messages.create(model=cfg["llm"]["model"], max_tokens=3000, system=SYSTEM,
                                          messages=[{"role": "user", "content": payload}])
            text = "".join(b.text for b in resp.content if b.type == "text")
            log.info("requisitos: tokens in=%s out=%s", resp.usage.input_tokens, resp.usage.output_tokens)
            rows = json.loads(re.search(r"\[.*\]", text, re.S).group(0))
        except Exception as e:
            log.warning("requisitos: lote falhou (%s)", e)
            continue
        for row in rows:
            try:
                job = batch[int(row["id"])]
            except (KeyError, ValueError, IndexError, TypeError):
                continue
            dedup = lambda xs: list(dict.fromkeys(canonical(x) for x in xs or [] if x))
            must = dedup(row.get("obrigatorios"))
            nice = [x for x in dedup(row.get("desejaveis")) if x not in must]
            job["requisitos"] = {"obrigatorios": must, "desejaveis": nice}
            job["senioridade"] = row.get("senioridade", "nao_informado")
            job["modalidade"] = row.get("modalidade", "nao_informado")
