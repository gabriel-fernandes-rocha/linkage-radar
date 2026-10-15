import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import fraud  # noqa: E402


def job(title, text="", company=""):
    return {"tipo": "vaga", "titulo": title, "texto": text, "empresa": company, "url": "https://x.co/" + title}


def test_fraud_data_roles_pass():
    assert fraud.passes(job("Senior Data Engineer - Financial Crime"))
    assert fraud.passes(job("Data Scientist Sênior (Prevenção a Fraudes)"))
    assert fraud.passes(job("Senior Data Scientist", "Build models.", company="sardine"))  # empresa de antifraude
    assert fraud.passes(job("Quantexa Data Engineer"))


def test_non_technical_or_off_topic_fail():
    assert not fraud.passes(job("Account Executive, Fraud Prevention"))           # vendas
    assert not fraud.passes(job("Fraud Operations Analyst"))                      # operação, sem dados
    assert not fraud.passes(job("Senior Data Engineer", "We build pipelines."))   # dados sem fraude
    assert not fraud.strong(job("Senior Entity Resolution Engineer"))             # ER sem fraude não é da trilha


def test_er_signals_badge():
    j = job("Data Engineer, Fraud", "We use entity resolution and graph analytics with Neo4j.")
    assert {"entity resolution", "graph analytics", "neo4j"} <= set(fraud.er_signals(j))
