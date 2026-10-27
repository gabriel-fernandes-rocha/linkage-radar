import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import brasil  # noqa: E402
from dedup import unique  # noqa: E402

BRQ = {"tipo": "vaga", "titulo": "Cientista de Dados Pleno", "empresa": "BRQ", "local": "Remoto · Brasil",
       "fonte": "InHire", "url": "https://brq.inhire.app/vagas/fb7bcaee/cientista-de-dados-pleno",
       "texto": "Será responsável pelo núcleo analítico da resolução de identidade do cliente. Atuará com profiling, "
                "normalização, matching determinístico ou probabilístico, deduplicação, scores de confiança e regras "
                "de sobrevivência que formarão o Unified Customer ID e o Golden Record. Diferenciais: RapidFuzz, "
                "Splink, Record Linkage."}


def test_generic_title_with_theme_in_description_is_captured():
    """A vaga de referência (título genérico, tema só na descrição) NUNCA pode escapar."""
    assert brasil.passes(dict(BRQ)) and brasil.strong(dict(BRQ)) and brasil.central(dict(BRQ))


def test_same_generic_title_from_other_company_is_not_a_duplicate():
    other = dict(BRQ, empresa="Outra", url="https://x.gupy.io/jobs/1", fonte="Gupy", texto="Dashboards.")
    assert len(unique([other, dict(BRQ)])) == 2


def test_single_specific_term_is_enough_without_ai():
    j = {"tipo": "vaga", "titulo": "Engenheiro de Machine Learning", "fonte": "Gupy", "local": "São Paulo",
         "texto": "Modelos para resolução de entidades em bases de clientes.", "url": "u"}
    assert brasil.passes(j) and brasil.strong(j)


def test_out_of_brazil_or_off_topic_fail():
    assert not brasil.passes(dict(BRQ, fonte="Greenhouse/x", local="Berlin, Germany", texto="Record linkage work."))
    assert not brasil.passes({"tipo": "vaga", "titulo": "Analista de Dados", "fonte": "Gupy", "local": "SP",
                              "texto": "Dashboards em Power BI.", "url": "u2"})


def test_levels_from_site_are_parsed_safely():
    import aplicar_niveis

    body = 'texto\n```json\n{"AWS": "parcial", "Spark": "tem", "X": "hack", "BigQuery": "auto"}\n```'
    assert aplicar_niveis.parse(body) == {"AWS": "parcial", "Spark": "tem", "BigQuery": "auto"}


def test_user_level_overrides_ai(tmp_path, monkeypatch):
    import compat

    monkeypatch.setattr(compat, "NIVEIS", tmp_path / "niveis.json")
    (tmp_path / "niveis.json").write_text(json.dumps({"BigQuery": "tem"}), "utf-8")
    cache = compat.apply_declared({"bigquery": {"nome": "BigQuery", "nivel": "nao"}}, {})
    assert cache["bigquery"]["nivel"] == "tem"


INHIRE_ESTAGIO = {
    "tipo": "vaga", "titulo": "Estágio em Engenharia de Dados", "empresa": "InHire", "fonte": "InHire",
    "local": "Remoto · Brasil", "url": "https://carreiras.inhire.app/vagas/d06a2962/estagio-em-engenharia-de-dados",
    "texto": "Você vai atuar no time de Importação, apoiando o processo de migração e integração de dados históricos "
             "de sistemas externos. Construir scripts de ETL. Realizar o mapeamento de campos entre sistemas. Apoiar "
             "no tratamento e limpeza de dados, garantindo consistência e qualidade antes da importação."}


def test_data_integration_job_is_captured():
    """Vaga do post do LinkedIn que o radar perdeu (integração/migração de dados, estágio)."""
    it = dict(INHIRE_ESTAGIO)
    assert brasil.passes(it) and it["categoria"] == "integracao" and brasil.strong(dict(INHIRE_ESTAGIO))


def test_hiring_post_snippet_is_captured():
    post = {"tipo": "vaga", "titulo": "Letícia Freitas on LinkedIn: Pessoal de Dados, vaga de estágio na InHire",
            "texto": "estamos com uma vaga de estágio no time de Importação, trabalhando com Python, SQL e integração "
                     "de dados.", "fonte": "Post · LinkedIn (Brasil)", "local": "Brasil", "social": True,
            "url": "https://www.linkedin.com/posts/x_activity-1"}
    assert brasil.passes(dict(post))


def test_plain_bi_job_is_not_integration():
    bi = {"tipo": "vaga", "titulo": "Analista de BI", "fonte": "Gupy", "local": "SP", "url": "u3",
          "texto": "Criar dashboards em Power BI com qualidade de dados."}
    assert not brasil.passes(bi)


def test_backup_ai_does_not_erase_known_fields():
    from filters import requirements

    job = {"titulo": "x", "local_contratacao": {"escopo": "pais", "paises": ["Brasil"]}, "senioridade": "pleno",
           "requisitos": {"obrigatorios": ["Python"], "desejaveis": []}, "requisitos_estimados": True}
    requirements._apply([job], [{"id": 0, "obrigatorios": ["Python", "SQL"], "desejaveis": [],
                                 "local_contratacao": None, "senioridade": None}])
    assert job["local_contratacao"]["paises"] == ["Brasil"] and job["senioridade"] == "pleno"
    assert job["requisitos"]["obrigatorios"] == ["Python", "SQL"] and "requisitos_estimados" not in job


def test_inhire_closed_job_is_detected(monkeypatch):
    import open_jobs

    class R:
        status_code = 404

        def json(self):
            return {}

    monkeypatch.setattr(open_jobs.requests, "get", lambda *a, **k: R())
    job = {"url": "https://brq.inhire.app/vagas/fb7bcaee-7c24-4cc3-be6c-71b274f1ad17/x", "fonte": "InHire"}
    assert not open_jobs.still_open(job, set())
