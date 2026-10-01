"""Gera as 365 aulas do programa (curriculum/plan.py) com o Claude Sonnet 5, ancoradas no livro do Christen.

O texto do livro fica SÓ na sua máquina (.book/christen.txt, ignorado pelo git; direitos autorais).
As aulas são texto original de ensino, com citação de seção e página.

Uso:
  python scripts/build_curriculum.py --teste 3        # gera as 3 primeiras de forma síncrona (para revisar)
  python scripts/build_curriculum.py --batch          # envia todas as que faltam via Batch API (50% mais barato)
  python scripts/build_curriculum.py --coletar ID     # baixa os resultados do batch e salva
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "curriculum"))
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8")

import plan  # noqa: E402
from common import no_dash  # noqa: E402

BOOK = ROOT / ".book" / "christen.txt"
OUT = ROOT / "curriculum" / "lessons.json"
MODEL = "claude-sonnet-5"
PAGE_OFFSET = 16          # página impressa + 16 = página do PDF
MAX_EXCERPT = 18000       # caracteres do livro por aula (~4,5k tokens)

SYSTEM = """Você é um professor sênior de Data Matching / Record Linkage / Entity Resolution, autor de cursos de \
pós-graduação, e escreve em português do Brasil. Seu aluno é Gabriel: engenheiro de dados brasileiro que já faz \
record linkage em produção com bilhões de registros (Spark, Python, SQL, Elasticsearch, Splink, RapidFuzz) e faz \
mestrado em Ciência da Computação. Ele quer se tornar ESPECIALISTA reconhecido internacionalmente e competir por \
vagas sênior no exterior. Logo, nada de conteúdo raso ou genérico: ensine como num bom livro-texto, com rigor.

Como escrever cada aula:
- Ancore o conteúdo no TRECHO DO LIVRO fornecido (Christen, 2012) sempre que houver: use as definições, a \
notação e os exemplos do livro, mas com suas palavras (nunca copie frases do livro). Indique seção e página.
- Complete com a literatura listada em REFERÊNCIAS PERMITIDAS. Cite SOMENTE essas referências (autor, ano). \
Nunca invente artigos, números, estatísticas, resultados de benchmark ou páginas.
- Seja concreto: fórmulas escritas em texto simples (ex.: w = log2(m/u)), passos de algoritmo numerados, \
exemplo resolvido com números reais que o aluno consiga refazer à mão.
- "na_pratica": como isso aparece num pipeline real (Python, PySpark, Splink, Elasticsearch ou SQL), com um \
trecho curto de código quando fizer sentido (até 8 linhas, sem comentários longos).
- "armadilha": um erro que profissionais experientes cometem, e como evitar.
- "desafio": um problema que exija raciocínio (calcular, comparar, projetar ou diagnosticar), nunca uma pergunta \
de opinião. Deve ser resolvível em 5 a 10 minutos. "gabarito": a resolução completa e curta.
- Varie os exemplos: bancos, varejo, saúde, governo, big techs, Brasil e exterior. Não cite o empregador do \
aluno nem instituições onde ele trabalha.
- Proibido travessão (— ou –): use vírgula, dois-pontos, parênteses ou ponto.
- Texto para ler no WhatsApp: parágrafos curtos, sem markdown (sem **, #, tabelas). Pode usar listas com "1." e "-".
- Precisão matemática: confira cada conta do exemplo e do gabarito. Use os termos certos de crescimento \
(linear, quadrático, 1/n); nunca diga "exponencial" se não for exponencial.
- Código: use SOMENTE APIs que você tem certeza que existem nas versões atuais. Se não tiver certeza da assinatura \
exata, descreva o passo em texto em vez de inventar código. Referência das APIs atuais:

Splink 4:
  import splink.comparison_library as cl
  from splink import DuckDBAPI, Linker, SettingsCreator, block_on
  settings = SettingsCreator(link_type="dedupe_only",   # ou "link_only" / "link_and_dedupe"
      comparisons=[cl.JaroWinklerAtThresholds("first_name", [0.9, 0.7]), cl.ExactMatch("city")],
      blocking_rules_to_generate_predictions=[block_on("first_name"), block_on("surname", "dob")])
  linker = Linker(df, settings, db_api=DuckDBAPI())       # duas bases: Linker([df_a, df_b], ...)
  linker.training.estimate_u_using_random_sampling(max_pairs=1e6)
  linker.training.estimate_parameters_using_expectation_maximisation(block_on("dob"))
  pred = linker.inference.predict(threshold_match_probability=0.9)
  clusters = linker.clustering.cluster_pairwise_predictions_at_threshold(pred, 0.95)
recordlinkage (Python):
  import recordlinkage
  from recordlinkage.datasets import load_febrl1, load_febrl4   # febrl4 devolve (dfA, dfB)
  idx = recordlinkage.Index(); idx.block("surname")            # ou idx.sortedneighbourhood("surname", window=5)
  pairs = idx.index(dfA, dfB)
  cmp = recordlinkage.Compare()
  cmp.string("given_name", "given_name", method="jarowinkler", threshold=0.85)
  cmp.exact("date_of_birth", "date_of_birth")
  features = cmp.compute(pairs, dfA, dfB)
RapidFuzz: from rapidfuzz.distance import Levenshtein, JaroWinkler; from rapidfuzz import fuzz, process
"""

SCHEMAS = {
    "conceito": {
        "type": "object",
        "properties": {
            "objetivo": {"type": "string", "description": "1 frase: o que o aluno saberá fazer ao final"},
            "conceito": {"type": "string", "description": "explicação rigorosa, 2 a 3 parágrafos curtos, 120 a 200 palavras"},
            "como_funciona": {"type": "string", "description": "fórmula e/ou passos numerados do método"},
            "exemplo": {"type": "string", "description": "exemplo resolvido com números, passo a passo"},
            "na_pratica": {"type": "string", "description": "aplicação em pipeline real, com código curto se fizer sentido"},
            "armadilha": {"type": "string", "description": "erro comum e como evitar, 1 a 2 frases"},
            "desafio": {"type": "string", "description": "problema de 5 a 10 min que exige raciocínio"},
            "gabarito": {"type": "string", "description": "resolução completa e curta do desafio"},
            "fontes": {"type": "array", "items": {"type": "string"}, "description": "ex.: 'Christen (2012), seç. 4.5, p. 81-84'"},
        },
        "required": ["objetivo", "conceito", "como_funciona", "exemplo", "na_pratica", "armadilha",
                     "desafio", "gabarito", "fontes"],
        "additionalProperties": False,
    },
    "laboratorio": {
        "type": "object",
        "properties": {
            "objetivo": {"type": "string"},
            "contexto": {"type": "string", "description": "cenário realista do exercício, 2 a 4 frases"},
            "passos": {"type": "array", "items": {"type": "string"}, "description": "4 a 7 passos objetivos"},
            "codigo": {"type": "string", "description": "código Python inicial, até 25 linhas, executável"},
            "como_avaliar": {"type": "string", "description": "como saber se o resultado está bom (métricas/checagens)"},
            "desafio": {"type": "string", "description": "extensão do laboratório para ir além"},
            "gabarito": {"type": "string", "description": "o que se espera observar e por quê"},
            "fontes": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["objetivo", "contexto", "passos", "codigo", "como_avaliar", "desafio", "gabarito", "fontes"],
        "additionalProperties": False,
    },
    "revisao": {
        "type": "object",
        "properties": {
            "objetivo": {"type": "string"},
            "conexao": {"type": "string", "description": "1 parágrafo ligando os assuntos da semana num mapa mental"},
            "perguntas": {
                "type": "array",
                "description": "7 perguntas de recuperação ativa: 5 da semana e 2 de aulas anteriores",
                "items": {"type": "object",
                          "properties": {"pergunta": {"type": "string"}, "resposta": {"type": "string"}},
                          "required": ["pergunta", "resposta"], "additionalProperties": False},
            },
            "desafio": {"type": "string", "description": "problema integrador da semana"},
            "gabarito": {"type": "string"},
            "fontes": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["objetivo", "conexao", "perguntas", "desafio", "gabarito", "fontes"],
        "additionalProperties": False,
    },
}


def book_pages() -> dict[int, str]:
    text = BOOK.read_text("utf-8")
    pages = {}
    for chunk in text.split("<<<PAGE ")[1:]:
        num, _, body = chunk.partition(">>>")
        pages[int(num) - PAGE_OFFSET] = body.strip()
    return pages


def excerpt(pages: dict[int, str], ranges: list[tuple[int, int]]) -> str:
    parts = []
    for a, b in ranges:
        for p in range(a, b + 1):
            if p in pages:
                parts.append(f"[p. {p}]\n{pages[p]}")
    return "\n\n".join(parts)[:MAX_EXCERPT]


def previous_titles(all_lessons: list[dict], dia: int, n: int = 6) -> str:
    prev = [l for l in all_lessons if l["dia"] < dia][-n:]
    return "\n".join(f"- Aula {l['dia']}: {l['titulo']}" for l in prev) or "- (esta é a primeira aula)"


def _summary(c: dict) -> str:
    keys = ("objetivo", "conceito", "como_funciona", "desafio", "gabarito", "contexto")
    return " | ".join(f"{k}: {c[k][:500]}" for k in keys if isinstance(c.get(k), str))


def user_prompt(lesson: dict, all_lessons: list[dict], pages: dict[int, str], done: dict | None = None) -> str:
    refs = "\n".join(f"- {plan.REFS[k]}" for k in ["christen2012", *lesson["refs"]] if k in plan.REFS)
    week_days = [l["titulo"] for l in all_lessons if l["semana"] == lesson["semana"] and l["tipo"] == "conceito"]
    parts = [
        f"AULA {lesson['dia']} de 365 | Semana {lesson['semana']} de 52: {lesson['tema']}",
        f"TIPO: {lesson['tipo']}",
        f"TÍTULO DA AULA: {lesson['titulo']}",
        "AULAS DESTA SEMANA (para não repetir conteúdo das outras):\n" + "\n".join(f"- {t}" for t in week_days),
        "AULAS ANTERIORES (continuidade):\n" + previous_titles(all_lessons, lesson["dia"]),
        "REFERÊNCIAS PERMITIDAS:\n" + refs,
    ]
    if lesson["tipo"] == "revisao":
        done = done or {}
        week = [l for l in all_lessons if l["semana"] == lesson["semana"] and l["tipo"] != "revisao"]
        parts.append("CONTEÚDO REAL DAS AULAS DESTA SEMANA (as perguntas devem se basear nisto):\n" + "\n".join(
            f"- Aula {l['dia']} ({l['titulo']}): {_summary(done.get(l['dia'], {}).get('conteudo_gerado', {}))}"
            for l in week))
        # repetição espaçada: aulas de 1, 3 e 8 semanas atrás (quando existirem)
        back = [l for l in all_lessons if l["tipo"] == "conceito"
                and l["semana"] in {lesson["semana"] - 1, lesson["semana"] - 3, lesson["semana"] - 8}]
        back = back[::3][:3]
        parts.append("AULAS ANTERIORES PARA REPETIÇÃO ESPAÇADA (faça 2 perguntas sobre elas, citando o número da aula):\n" +
                     ("\n".join(f"- Aula {l['dia']} ({l['titulo']}): "
                                 f"{_summary(done.get(l['dia'], {}).get('conteudo_gerado', {}))}" for l in back)
                      or "- nenhuma (primeira semana): faça as 7 perguntas sobre esta semana"))
    if lesson["tipo"] == "laboratorio":
        parts.append("O laboratório deve usar dados públicos ou sintéticos (ex.: recordlinkage.datasets.load_febrl1, "
                     "Faker, ou um CSV pequeno criado no próprio código) e rodar num notebook comum.")
    ex = excerpt(pages, lesson["livro"]) if lesson["livro"] else ""
    parts.append("TRECHO DO LIVRO (Christen, 2012), use como base e cite seção/página:\n" + ex if ex else
                 "Esta aula vai além do livro de 2012: use as referências permitidas e cite-as.")
    return "\n\n".join(parts)


def request_params(lesson: dict, all_lessons: list[dict], pages: dict[int, str], done: dict | None = None) -> dict:
    return {
        "model": MODEL,
        "max_tokens": 12000,
        "system": [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user_prompt(lesson, all_lessons, pages, done)}],
        "output_config": {"effort": "medium",
                          "format": {"type": "json_schema", "schema": SCHEMAS[lesson["tipo"]]}},
    }


def clean(obj):
    if isinstance(obj, str):
        return no_dash(obj.replace("**", "").strip())
    if isinstance(obj, list):
        return [clean(x) for x in obj]
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    return obj


def load_out() -> dict[int, dict]:
    if not OUT.exists():
        return {}
    data = json.loads(OUT.read_text("utf-8"))
    return {l["dia"]: l for l in data if l.get("versao") == 2}


def save(done: dict[int, dict], all_lessons: list[dict]) -> None:
    rows = []
    for l in all_lessons:
        base = {k: l[k] for k in ("dia", "semana", "tema", "tipo", "titulo")}
        base["modulo"] = f"Semana {l['semana']}: {l['tema']}"
        base["versao"] = 2
        base.update(done.get(l["dia"], {}).get("conteudo_gerado", {}))
        if l["dia"] in done:
            base["gerada"] = True
        rows.append(base)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), "utf-8")


def text_of(message) -> str:
    return next(b.text for b in message.content if b.type == "text")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teste", type=int)
    ap.add_argument("--batch", action="store_true", help="etapa 1: conceitos e laboratórios")
    ap.add_argument("--batch-revisoes", action="store_true", help="etapa 2: revisões (depois da etapa 1)")
    ap.add_argument("--refazer", type=str, help="dias para refazer, ex.: 1-7")
    ap.add_argument("--coletar")
    args = ap.parse_args()

    import anthropic

    client = anthropic.Anthropic()
    all_lessons = plan.lessons()
    pages = book_pages()
    done = {d: {"conteudo_gerado": {k: v for k, v in l.items()
                                    if k not in ("dia", "semana", "tema", "tipo", "titulo", "modulo", "versao", "gerada")}}
            for d, l in load_out().items() if l.get("gerada")}

    if args.refazer:
        a, _, b = args.refazer.partition("-")
        for d in range(int(a), int(b or a) + 1):
            done.pop(d, None)

    if args.teste:
        for lesson in all_lessons[: args.teste]:
            if lesson["dia"] in done:
                continue
            resp = client.messages.create(**request_params(lesson, all_lessons, pages, done))
            print(f"aula {lesson['dia']}: in={resp.usage.input_tokens} out={resp.usage.output_tokens} "
                  f"cache_read={resp.usage.cache_read_input_tokens}")
            done[lesson["dia"]] = {"conteudo_gerado": clean(json.loads(text_of(resp)))}
            save(done, all_lessons)
        return

    if args.batch or args.batch_revisoes:
        from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
        from anthropic.types.messages.batch_create_params import Request

        want = ("revisao",) if args.batch_revisoes else ("conceito", "laboratorio")
        todo = [l for l in all_lessons if l["dia"] not in done and l["tipo"] in want]
        batch = client.messages.batches.create(requests=[
            Request(custom_id=f"aula-{l['dia']}",
                    params=MessageCreateParamsNonStreaming(**request_params(l, all_lessons, pages, done)))
            for l in todo])
        (ROOT / ".book" / "batch_id.txt").write_text(batch.id)
        print(f"batch {batch.id} com {len(todo)} aulas enviado")
        args.coletar = batch.id

    if args.coletar:
        while True:
            b = client.messages.batches.retrieve(args.coletar)
            print(f"status={b.processing_status} ok={b.request_counts.succeeded} "
                  f"erro={b.request_counts.errored} processando={b.request_counts.processing}", flush=True)
            if b.processing_status == "ended":
                break
            time.sleep(60)
        failed = []
        for r in client.messages.batches.results(args.coletar):
            dia = int(r.custom_id.split("-")[1])
            if r.result.type == "succeeded":
                try:
                    done[dia] = {"conteudo_gerado": clean(json.loads(text_of(r.result.message)))}
                except Exception:
                    failed.append(dia)
            else:
                failed.append(dia)
        save(done, all_lessons)
        print(f"salvas: {len(done)}/365. falharam: {sorted(failed)} (rode --batch de novo para refazer)")


if __name__ == "__main__":
    main()
