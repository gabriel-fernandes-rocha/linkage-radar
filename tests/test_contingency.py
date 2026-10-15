import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import compat  # noqa: E402
from common import load_config  # noqa: E402
from filters import req_heuristic  # noqa: E402
from sources import events  # noqa: E402


def test_docs_page_is_not_event():
    it = {"titulo": "Geocodificação nos visuais do Azure Mapas para o Power BI",
          "url": "https://learn.microsoft.com/pt-br/azure/azure-maps/power-bi-visual-geocode", "texto": "docs"}
    assert not events.is_real_event(it, date(2026, 10, 15))[0]


def test_future_event_passes_and_past_fails():
    future = {"titulo": "Workshop de Record Linkage", "url": "https://www.sympla.com.br/evento/x",
              "texto": "Inscrições abertas. 20/11/2026 às 19h, online."}
    past = dict(future, texto="Realizado em 10/03/2025.")
    assert events.is_real_event(future, date(2026, 10, 15))[0]
    assert not events.is_real_event(past, date(2026, 10, 15))[0]


def test_job_without_ai_still_gets_compatibility():
    job = {"titulo": "Senior Entity Resolution Engineer", "local": "Remote - LATAM",
           "texto": "We need 5+ years with Python, Spark and SQL. Experience with Splink. "
                    "Nice to have: Kafka, AWS."}
    req_heuristic.extract(job)
    assert {"Python", "Spark", "SQL"} <= set(job["requisitos"]["obrigatorios"])
    assert "Kafka" in job["requisitos"]["desejaveis"]
    assert job["anos_experiencia_min"] == 5 and job["senioridade"] == "senior"
    compat.score(job, load_config(), {})
    assert 0 < job["encaixe"] <= 1 and job["compat_detalhe"]["estimado"]
