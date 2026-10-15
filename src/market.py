"""'O que o mercado pede': ranking de requisitos, famílias, ganho de compatibilidade e plano de estudo.

- Nicho: requisitos das vagas aprovadas (ER, record linkage, MDM, identity resolution...).
- Mercado amplo: amostra semanal de vagas de engenharia/ciência de dados em geral (data/market_sample.json).
- Ganho: para cada habilidade que você não tem, simula "e se você aprendesse isso?" nas vagas ABERTAS e mede
  quanto a sua compatibilidade média sobe e quantas vagas passam a ficar acessíveis (>= min_compat).
"""
from __future__ import annotations

import copy
import json
import random
import re
from collections import Counter, defaultdict
from datetime import date, timedelta

from common import DATA, load_config, log

SAMPLE = DATA / "market_sample.json"

# família -> padrões (minúsculo). Uma vaga conta 1x por família, mesmo citando várias ferramentas dela.
FAMILIES = {
    "Nuvem (AWS, Azure ou GCP)": r"^(aws|azure|gcp|google cloud.*|amazon .*|s3|ec2|lambda|glue|emr|redshift|bigquery|"
                                 r"synapse|azure data factory|cloud platforms?|cloud)$",
    "Plataformas de MDM (Reltio, Informatica, IBM, Profisee, Tamr)": r"(reltio|informatica|ibm mdm|profisee|tamr|"
                                                                     r"stibo|semarchy|mdm platforms?|sap mdg)",
    "Bancos de grafos (Neo4j, GraphFrames)": r"(neo4j|graph ?databases?|graphframes|tigergraph|neptune|graph db)",
    "Deep learning (PyTorch, TensorFlow)": r"^(pytorch|tensorflow|keras|deep learning)$",
    "LLMs e IA generativa": r"(llm|large language|genai|generative ai|rag|langchain|prompt)",
    "Orquestração (Airflow, Dagster, Prefect)": r"(airflow|dagster|prefect|luigi|orchestration)",
    "Transformação e modelagem (dbt, data modeling)": r"(^dbt$|data modeling|dimensional modeling|data modelling)",
    "Lakehouse (Databricks, Delta, Iceberg)": r"(databricks|delta lake|iceberg|hudi|lakehouse|unity catalog)",
    "Data warehouse na nuvem (Snowflake, BigQuery, Redshift)": r"(snowflake|bigquery|redshift|synapse)",
    "Streaming (Kafka, Kinesis, Flink)": r"(kafka|kinesis|flink|pub/?sub|spark streaming|streaming)",
    "Containers e DevOps (Docker, Kubernetes, CI/CD)": r"(docker|kubernetes|k8s|ci/cd|terraform|devops|git)",
    "Linguagens JVM (Scala, Java)": r"^(scala|java|kotlin)$",
    "Busca (Elasticsearch, OpenSearch, Solr)": r"(elasticsearch|opensearch|solr|lucene)",
    "BI (Tableau, Power BI, Looker)": r"(tableau|power bi|looker|qlik)",
}


def _canon_map(jobs: list[dict]) -> dict[str, str]:
    """Junta variações de maiúscula/minúscula: usa a grafia mais frequente como nome oficial."""
    spell = defaultdict(Counter)
    for j in jobs:
        req = j.get("requisitos") or {}
        for s in req.get("obrigatorios", []) + req.get("desejaveis", []):
            spell[s.lower().strip()][s.strip()] += 1
    return {k: c.most_common(1)[0][0] for k, c in spell.items()}


def _rank(jobs: list[dict], match: dict) -> dict:
    jobs = [j for j in jobs if j.get("requisitos")]
    canon = _canon_map(jobs)
    must, nice, any_, fam_any, fam_members = Counter(), Counter(), Counter(), Counter(), defaultdict(Counter)
    for j in jobs:
        req = j["requisitos"]
        m = {canon[s.lower().strip()] for s in req.get("obrigatorios", [])}
        n = {canon[s.lower().strip()] for s in req.get("desejaveis", [])} - m
        must.update(m)
        nice.update(n)
        any_.update(m | n)
        fams = set()
        for s in m | n:
            for fam, pat in FAMILIES.items():
                if re.search(pat, s.lower()):
                    fams.add(fam)
                    fam_members[fam][s] += 1
        fam_any.update(fams)
    total = len(jobs)
    pct = lambda c: round(100 * c / total) if total else 0
    declared = {str(s).lower() for s in load_config().get("perfil_estruturado", {}).get("habilidades", [])}
    # sem veredito ainda (nenhuma IA disponível): declarada no perfil = "tem"; senão "pendente" (não é "falta")
    level = lambda s: match.get(s.lower(), {}).get("nivel") or ("tem" if s.lower() in declared else "pendente")
    rows = [{"nome": k, "vagas": c, "pct": pct(c), "obrigatorio": must[k], "desejavel": nice[k], "voce": level(k)}
            for k, c in any_.most_common(80)]
    fams = [{"nome": f, "vagas": c, "pct": pct(c), "exemplos": [s for s, _ in fam_members[f].most_common(5)],
             "voce": max((level(s) for s in fam_members[f]), key=["pendente", "nao", "parcial", "tem"].index)}
            for f, c in fam_any.most_common()]
    return {"vagas_analisadas": total, "ranking": rows, "familias": fams}


def _gains(jobs: list[dict], rows: list[dict], fams: list[dict]) -> dict:
    """Simula 'e se você aprendesse X?' em TODAS as vagas do nicho (a localização não entra: ela não muda
    com estudo). Mede: quanto sobe a sua cobertura média de requisitos e em quantas vagas você passaria a
    cumprir todos os obrigatórios."""
    import compat

    cache = compat._load_cache()
    jobs = [j for j in jobs if j.get("requisitos")]
    if not jobs:
        return {"habilidades": [], "familias": []}

    def evaluate(c):
        cov, full = 0.0, 0
        for j in jobs:
            req = j["requisitos"]
            m, n = compat._coverage(req.get("obrigatorios", []), c), compat._coverage(req.get("desejaveis", []), c)
            cov += (0.75 * m + 0.25 * n) if m is not None and n is not None else (m if m is not None else (n or 0))
            full += m == 1.0 if m is not None else 0
        return 100 * cov / len(jobs), full

    base_cov, base_full = evaluate(cache)

    def gain(names: list[str], label: str, extra: dict) -> dict:
        c2 = dict(cache)
        for nm in names:
            c2[nm.lower()] = {"nome": nm, "nivel": "tem", "motivo": "simulação"}
        cov, full = evaluate(c2)
        return {"nome": label, "ganho_cobertura": round(cov - base_cov, 1), "vagas_completas_a_mais": full - base_full,
                **extra}

    skills = [gain([r["nome"]], r["nome"], {"voce": r["voce"], "pct_nicho": r["pct"]})
              for r in rows if r["voce"] != "tem" and r["vagas"] >= 2]
    families = [gain(f["exemplos"], f["nome"], {"voce": f["voce"], "pct_nicho": f["pct"]})
                for f in fams if f["voce"] != "tem"]
    key = lambda g: (g["ganho_cobertura"], g["vagas_completas_a_mais"])
    return {"cobertura_atual": round(base_cov, 1), "vagas_completas_hoje": base_full, "vagas_analisadas": len(jobs),
            "habilidades": sorted(skills, key=key, reverse=True)[:25],
            "familias": sorted(families, key=key, reverse=True)}


def write(archive: list[dict], day: str, out=None) -> dict:
    """out: onde gravar (padrão data/skills.json; a trilha de fraude grava em data/fraude/skills.json)."""
    match = json.loads((DATA / "skill_match.json").read_text("utf-8")) if (DATA / "skill_match.json").exists() else {}
    import compat

    match = compat.apply_declared(match, load_config())
    since = (date.fromisoformat(day) - timedelta(days=90)).isoformat()
    sample = json.loads(SAMPLE.read_text("utf-8")) if SAMPLE.exists() else []
    geral = _rank(archive, match)
    stats = {
        "atualizado_em": day,
        "geral": geral,
        "ultimos_90_dias": _rank([j for j in archive if j.get("primeira_vez", "") >= since], match),
        "mercado_amplo": _rank(sample, match),
        "ganhos": _gains(archive, geral["ranking"], geral["familias"]),
        "senioridade": Counter(j.get("senioridade") or "nao_informado" for j in archive).most_common(),
        "modalidade": Counter(j.get("modalidade") or "nao_informado" for j in archive).most_common(),
    }
    out = out or (DATA / "skills.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(stats, ensure_ascii=False, indent=1), "utf-8")
    log.info("mercado: %d vagas no nicho, %d no mercado amplo", geral["vagas_analisadas"],
             stats["mercado_amplo"]["vagas_analisadas"])
    return stats


BROAD_TITLES = re.compile(r"(data engineer|engenheir[oa]\(?a?\)? de dados|analytics engineer|data scientist|"
                          r"cientista de dados|machine learning engineer|ml engineer|data platform|big data)", re.I)


def sample_broad_market(raw_jobs: list[dict], cfg: dict, day: str, size: int = 40) -> None:
    """1x por semana: extrai requisitos de uma amostra de vagas de dados em geral (Haiku, barato)."""
    sample = json.loads(SAMPLE.read_text("utf-8")) if SAMPLE.exists() else []
    if sample and max(s.get("data", "") for s in sample) > (date.fromisoformat(day) - timedelta(days=7)).isoformat():
        return
    seen = {s["url"] for s in sample}
    pool = [j for j in raw_jobs if BROAD_TITLES.search(j.get("titulo", "")) and j["url"] not in seen
            and len(j.get("texto") or "") > 400]
    if not pool:
        return
    random.seed(day)
    picked = [dict(j) for j in random.sample(pool, min(size, len(pool)))]
    from filters import requirements

    cfg2 = copy.deepcopy(cfg)
    cfg2["llm"]["extract_model"] = cfg["llm"]["model"]  # Haiku: amostra grande, custo baixo
    requirements.extract(picked, cfg2, batch_size=5)
    keep = ("titulo", "empresa", "url", "fonte", "requisitos", "senioridade", "modalidade")
    new = [{**{k: j.get(k) for k in keep}, "data": day} for j in picked if j.get("requisitos")]
    since = (date.fromisoformat(day) - timedelta(days=120)).isoformat()
    sample = [s for s in sample if s.get("data", "") >= since] + new
    SAMPLE.write_text(json.dumps(sample[-600:], ensure_ascii=False, indent=1), "utf-8")
    log.info("mercado amplo: +%d vagas na amostra (total %d)", len(new), len(sample))
