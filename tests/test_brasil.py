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
