"""Extrai ferramentas/métodos SOMENTE da seção de requisitos das vagas (Claude Haiku, em lotes).

Ignora "sobre a empresa", benefícios e descrição genérica: o objetivo é saber o que o mercado
realmente exige, sem inflar a contagem.
"""
from __future__ import annotations

import json

from common import log, no_dash

SYSTEM = """Você extrai FATOS de descrições de vagas. Não opine, não estime compatibilidade: só registre o que \
está escrito (ou "nao_informado").

Requisitos: use APENAS a seção de requisitos/qualificações ("Requirements", "Qualifications", "What you'll need", \
"Must have", "Nice to have", "Requisitos", "Diferenciais"). Ignore descrição da empresa, benefícios e marketing.
Extraia ferramentas, linguagens, frameworks, bancos, nuvens e MÉTODOS (ex.: Python, Spark, SQL, Splink, \
Elasticsearch, AWS, Databricks, Fellegi-Sunter, blocking, fuzzy matching, entity resolution, record linkage, MDM, \
graph databases, LLMs, dbt, Airflow). Não extraia soft skills, diplomas genéricos nem anos de experiência.
Nomes canônicos curtos ("PySpark"/"Apache Spark" -> "Spark"; "Amazon Web Services" -> "AWS"; "Postgres" -> \
"PostgreSQL"). "obrigatorios" = exigidos; "desejaveis" = nice to have / preferred / plus / diferencial.

Local de contratação (onde a empresa aceita candidatos), a informação MAIS importante:
- escopo "global": aceita qualquer país (ex.: "remote anywhere", "work from anywhere", freelance global).
- escopo "regiao"/"pais"/"cidade": liste os países em "paises" (use "LATAM" para América Latina) e cidades em \
"cidades". "Remote, US" = escopo "pais", paises ["United States"]. Vaga presencial em Nova York = escopo "cidade", \
paises ["United States"], cidades ["New York"].
- "nao_informado" se não der para saber.
"patrocina_visto": true/false só se o texto disser; senão null.
"contratacao": "clt_ou_fulltime", "contractor_global" (contrato PJ aceito de qualquer país), "freelance", \
"nao_informado".
"anos_experiencia_min": menor número de anos exigido (ex.: "5+ years" -> 5), ou null.
"ingles": exigência de inglês ("nao_exigido", "intermediario", "fluente", "nativo", "nao_informado"); vaga \
escrita em inglês para país anglófono sem menção explícita = "fluente".
"foco_er": 0 a 1, quanto do trabalho é entity resolution / record linkage / matching / MDM / identity resolution \
(1 = é o centro da função; 0,5 = parte relevante; 0,1 = citado de passagem)."""

SCHEMA = {
    "type": "object",
    "properties": {"vagas": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "obrigatorios": {"type": "array", "items": {"type": "string"}},
            "desejaveis": {"type": "array", "items": {"type": "string"}},
            "senioridade": {"type": "string", "enum": ["junior", "pleno", "senior", "staff/principal", "gerencia",
                                                      "nao_informado"]},
            "modalidade": {"type": "string", "enum": ["remoto", "hibrido", "presencial", "nao_informado"]},
            "local_contratacao": {"type": "object", "properties": {
                "escopo": {"type": "string", "enum": ["global", "regiao", "pais", "cidade", "nao_informado"]},
                "paises": {"type": "array", "items": {"type": "string"}},
                "cidades": {"type": "array", "items": {"type": "string"}}},
                "required": ["escopo", "paises", "cidades"], "additionalProperties": False},
            "patrocina_visto": {"type": ["boolean", "null"]},
            "contratacao": {"type": "string", "enum": ["clt_ou_fulltime", "contractor_global", "freelance",
                                                      "nao_informado"]},
            "anos_experiencia_min": {"type": ["number", "null"]},
            "ingles": {"type": "string", "enum": ["nao_exigido", "intermediario", "fluente", "nativo",
                                                 "nao_informado"]},
            "foco_er": {"type": "number"},
        },
        "required": ["id", "obrigatorios", "desejaveis", "senioridade", "modalidade", "local_contratacao",
                     "patrocina_visto", "contratacao", "anos_experiencia_min", "ingles", "foco_er"],
        "additionalProperties": False}}},
    "required": ["vagas"], "additionalProperties": False,
}

FIELDS = ("senioridade", "modalidade", "local_contratacao", "patrocina_visto", "contratacao",
          "anos_experiencia_min", "ingles", "foco_er")

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
    """Preenche requisitos e fatos (local, visto, anos, inglês, foco) lendo a vaga inteira."""
    import anthropic

    client = anthropic.Anthropic()
    model = cfg["llm"].get("extract_model", cfg["llm"]["model"])
    for start in range(0, len(jobs), batch_size):
        batch = jobs[start:start + batch_size]
        payload = json.dumps([{"id": i, "titulo": j["titulo"], "empresa": j.get("empresa", ""),
                               "local_anunciado": j.get("local", ""), "fonte": j.get("fonte", ""),
                               "texto": (j.get("texto") or "")[:7000]}
                              for i, j in enumerate(batch)], ensure_ascii=False)
        try:
            resp = client.messages.create(
                model=model, max_tokens=6000, system=SYSTEM,
                messages=[{"role": "user", "content": payload}],
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}})
            text = next(b.text for b in resp.content if b.type == "text")
            log.info("requisitos: tokens in=%s out=%s", resp.usage.input_tokens, resp.usage.output_tokens)
            rows = json.loads(text)["vagas"]
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
            for f in FIELDS:
                job[f] = row.get(f)
