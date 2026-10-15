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
from filters import heuristic, keywords, llm_judge, providers  # noqa: E402


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """Cada teste: rótulos em pasta temporária, cadeia só com Claude, nenhum provedor desligado."""
    import common

    monkeypatch.setattr(heuristic, "LABELS", tmp_path / "labels.json")
    heuristic._MODELS.clear()
    providers.DOWN.clear()
    common.LLM_STATE.update(anthropic_down=False, motivo="")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "teste")
    for env in ["GEMINI_API_KEY"] + [p["env"] for p in providers.PROVIDERS.values()]:
        monkeypatch.delenv(env, raising=False)
    yield
    common.LLM_STATE.update(anthropic_down=False, motivo="")

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
    monkeypatch.setattr(providers, "_anthropic", lambda model, system, user, mt: "Aqui:\n" + fake)
    cfg = load_config()
    out = llm_judge.judge(items, cfg)
    assert [it["titulo"] for it in out] == [RELEVANT[0]["titulo"]]
    assert out[0]["motivo"] == "foco em ER"


def test_judge_drops_batch_on_garbage(monkeypatch):
    monkeypatch.setattr(providers, "_anthropic", lambda model, system, user, mt: "desculpe, não sei")
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


def test_claude_quota_falls_back_without_losing_items(monkeypatch):
    """Claude sem limite e nenhuma reserva: para no 1º erro, nada vira 'visto', a heurística barra o ruído."""
    import common

    calls = {"n": 0}

    def boom(model, system, user, mt):
        calls["n"] += 1
        raise RuntimeError("Error code: 400 - You have reached your specified API usage limits. "
                           "You will regain access on 2026-11-01 at 00:00 UTC.")

    monkeypatch.setattr(providers, "_anthropic", boom)
    cfg = load_config()
    cfg["llm"]["batch_size"] = 2
    items = [dict(x) for x in RELEVANT + FALSE_POSITIVES]
    for it in items:
        keywords.passes(it)
    assert llm_judge.judge(items, cfg) == []
    assert calls["n"] == 1
    assert common.LLM_STATE["anthropic_down"]
    assert not any(it.get("_julgado") for it in items)
    ok = [it["titulo"] for it in items if heuristic.approve(it)]
    assert "Senior Entity Resolution Engineer" in ok
    assert not set(ok) & {x["titulo"] for x in FALSE_POSITIVES}


def test_chain_uses_free_backup_when_claude_is_down(monkeypatch):
    def boom(model, system, user, mt):
        raise RuntimeError("Error code: 400 - credit balance is too low")

    fake = json.dumps([{"id": 0, "relevante": True, "confianca": 0.9, "motivo": "ER", "resumo_pt": "ok"}])
    monkeypatch.setattr(providers, "_anthropic", boom)
    monkeypatch.setenv("GROQ_API_KEY", "teste")
    monkeypatch.setattr(providers, "_openai_compatible", lambda name, model, system, user, mt: fake)
    out = llm_judge.judge([dict(RELEVANT[0])], load_config())
    assert len(out) == 1 and out[0]["juiz"] == "groq"


def test_heuristic_learns_and_keeps_high_precision(monkeypatch):
    """Com histórico suficiente, o modelo só aprova onde o juiz aprovaria (alvo: precisão >= 95%)."""
    import random as rnd

    rows = []
    good = ["Entity Resolution Engineer", "Record Linkage Data Engineer", "Senior Identity Resolution Engineer",
            "Data Engineer, Entity Matching", "MDM Engineer, Master Data Management"]
    bad = ["Data Engineer", "Sales Engineer, Data Matching", "SRE Engineer", "GIS Technician", "BI Analyst"]
    r = rnd.Random(1)
    for i in range(120):
        ok = i % 2 == 0
        title = r.choice(good if ok else bad)
        text = ("build entity resolution pipelines with blocking and probabilistic record linkage" if ok else
                "company leader in entity resolution. you will maintain dashboards and sales pipeline")
        rows.append({"tipo": "vaga", "titulo": title, "texto": text, "ok": ok, "data": "2026-10-01"})
    heuristic.LABELS.write_text(json.dumps(rows), "utf-8")
    yes = dict(tipo="vaga", titulo="Senior Entity Resolution Engineer",
               texto="build entity resolution pipelines with blocking and probabilistic record linkage")
    no = dict(tipo="vaga", titulo="Data Engineer - Entity Resolution platform company",
              texto="company leader in entity resolution. you will maintain dashboards and sales pipeline")
    keywords.passes(yes)
    keywords.passes(no)
    assert heuristic.approve(yes)
    assert not heuristic.approve(no)
    assert heuristic._MODELS["vaga"]["precisao"] >= 0.95


def test_compat_tolerates_empty_fields_from_backup_ai():
    """Caso real (15/10): o Groq devolveu senioridade/modalidade vazias e o cálculo quebrava a coleta."""
    import compat

    job = {"titulo": "ER Engineer", "requisitos": {"obrigatorios": ["Python"], "desejaveis": []},
           "senioridade": None, "modalidade": None, "ingles": None, "contratacao": None,
           "local_contratacao": None, "anos_experiencia_min": None, "foco_er": None}
    compat.score(job, load_config(), {"python": {"nome": "Python", "nivel": "tem"}})
    assert 0 < job["encaixe"] <= 1
