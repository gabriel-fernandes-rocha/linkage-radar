"""10 exemplos fixos: 5 relevantes e 5 falsos positivos típicos.

pytest                      → testa o filtro de palavras-chave e o parser do juiz (grátis)
RUN_LLM_TESTS=1 pytest      → também chama o LLM de verdade (custa ~US$ 0,002)
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from common import load_config  # noqa: E402
from filters import keywords, llm_judge  # noqa: E402

RELEVANT = [
    {"tipo": "vaga", "titulo": "Senior Entity Resolution Engineer", "empresa": "Senzing", "local": "Remote",
     "texto": "Design and scale entity resolution pipelines, probabilistic record linkage and blocking strategies."},
    {"tipo": "vaga", "titulo": "Data Engineer – Record Linkage", "empresa": "NHS Digital", "local": "Leeds, UK",
     "texto": "Build record linkage services using Splink and Fellegi-Sunter models across national health datasets."},
    {"tipo": "paper", "titulo": "Ditto: Deep Entity Matching with Pre-Trained Language Models",
     "texto": "We present Ditto, an entity matching system based on pre-trained Transformer language models."},
    {"tipo": "paper", "titulo": "Address matching for geocoding Brazilian health records",
     "texto": "We propose an address matching approach using CNEFE as gazetteer to geocode records from SIM."},
    {"tipo": "vaga", "titulo": "Geospatial Engineer, Address Matching", "empresa": "Mapbox", "local": "Remote",
     "texto": "Own our address matching and geocoding matching quality: parsing, normalization and fuzzy matching of addresses."},
]

FALSE_POSITIVES = [
    {"tipo": "vaga", "titulo": "Senior SRE Engineer", "empresa": "Reltio", "local": "Bangalore",
     "texto": "Reltio is the leader in entity resolution and master data. You will run Kubernetes clusters."},
    {"tipo": "vaga", "titulo": "Data Engineer", "empresa": "Acme", "local": "São Paulo",
     "texto": "Build ETL pipelines in Airflow and dbt. Knowledge of matching and data quality is a plus."},
    {"tipo": "vaga", "titulo": "Sales Development Representative – Data Matching Platform", "empresa": "Tamr",
     "texto": "Prospect customers for our data matching product. Sales quota."},
    {"tipo": "vaga", "titulo": "GIS Technician", "empresa": "City of Austin",
     "texto": "Maintain maps and geocoding layers in ArcGIS."},
    {"tipo": "paper", "titulo": "Smoking among high school students in Semarang",
     "texto": "Cross-sectional survey of 400 students; logistic regression of risk factors."},
]


def test_relevant_pass_keywords():
    for it in RELEVANT:
        assert keywords.passes(dict(it)), it["titulo"]


def test_false_positives_blocked_by_keywords():
    blocked = [it for it in FALSE_POSITIVES if not keywords.passes(dict(it))]
    # o de vendas cita "data matching" no título; o filtro barato penaliza, o juiz confirma
    assert len(blocked) >= 4, [it["titulo"] for it in FALSE_POSITIVES if keywords.passes(dict(it))]


def test_judge_filters_by_confidence(monkeypatch):
    items = [dict(RELEVANT[0]), dict(FALSE_POSITIVES[2]), dict(RELEVANT[2])]
    fake = json.dumps([
        {"id": 0, "relevante": True, "confianca": 0.95, "motivo": "foco em ER", "resumo_pt": "Vaga de ER."},
        {"id": 1, "relevante": False, "confianca": 0.9, "motivo": "vendas", "resumo_pt": ""},
        {"id": 2, "relevante": True, "confianca": 0.6, "motivo": "talvez", "resumo_pt": "Paper."},
    ])
    monkeypatch.setattr(llm_judge, "_anthropic", lambda model, content, system: "Aqui:\n" + fake)
    cfg = load_config()
    out = llm_judge.judge(items, cfg)
    assert [it["titulo"] for it in out] == [RELEVANT[0]["titulo"]]
    assert out[0]["motivo"] == "foco em ER"


def test_judge_drops_batch_on_garbage(monkeypatch):
    monkeypatch.setattr(llm_judge, "_anthropic", lambda model, content, system: "desculpe, não sei")
    assert llm_judge.judge([dict(RELEVANT[0])], load_config()) == []


@pytest.mark.skipif(not os.getenv("RUN_LLM_TESTS"), reason="defina RUN_LLM_TESTS=1 para chamar o LLM real")
def test_judge_live():
    cfg = load_config()
    out = llm_judge.judge([dict(x) for x in RELEVANT + FALSE_POSITIVES], cfg)
    titles = {it["titulo"] for it in out}
    fp = titles & {x["titulo"] for x in FALSE_POSITIVES}
    tp = titles & {x["titulo"] for x in RELEVANT}
    print(f"\nverdadeiros positivos: {len(tp)}/5, falsos positivos: {len(fp)}/5")
    assert not fp, fp
    assert len(tp) >= 4
