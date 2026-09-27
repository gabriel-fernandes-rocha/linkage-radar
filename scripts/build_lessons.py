"""Gera curriculum/lessons.json (365 aulas) UMA ÚNICA VEZ.

- Mantém aulas já escritas (as 30 primeiras foram escritas à mão).
- Preenche as que faltam com o Claude Haiku, em lotes de 10 (custo total ≈ US$ 0,50).
- Pode ser interrompido e rodado de novo: só gera o que falta.

Uso:  python scripts/build_lessons.py            (precisa de ANTHROPIC_API_KEY)
      python scripts/build_lessons.py --skeleton (só monta o arquivo, sem LLM)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "curriculum"))
import syllabus  # noqa: E402

OUT = ROOT / "curriculum" / "lessons.json"
MODEL = "claude-haiku-4-5"

PROMPT = """Você é professor de Record Linkage / Entity Resolution / Geocodificação, ensinando um engenheiro \
de dados brasileiro que já trabalha com linkage em produção (Spark, Python, Splink, Elasticsearch, bases do SUS) \
e faz mestrado em Ciência da Computação. Escreva as aulas abaixo em português do Brasil.

Para cada aula, gere:
- "explicacao": no máximo 120 palavras, tom de professor, tecnicamente correta, concreta
- "exemplo": curto (1-3 linhas; pode ser um mini-cálculo, trecho de código ou caso real)
- "pergunta_reflexao": 1 pergunta que faça pensar na prática dele

Não invente citações, números de artigos ou estatísticas específicas. Responda SOMENTE um array JSON:
[{"dia": n, "explicacao": "...", "exemplo": "...", "pergunta_reflexao": "..."}]

Aulas (dia, módulo, título):
"""


def skeleton() -> list[dict]:
    existing = {l["dia"]: l for l in json.loads(OUT.read_text("utf-8"))} if OUT.exists() else {}
    lessons = []
    for i, (mod, title) in enumerate(syllabus.flat(), start=1):
        old = existing.get(i, {})
        lessons.append({
            "dia": i, "modulo": mod, "titulo": title,
            "explicacao": old.get("explicacao", "") if old.get("titulo") == title else "",
            "exemplo": old.get("exemplo", "") if old.get("titulo") == title else "",
            "pergunta_reflexao": old.get("pergunta_reflexao", "") if old.get("titulo") == title else "",
        })
    return lessons


def save(lessons):
    OUT.write_text(json.dumps(lessons, ensure_ascii=False, indent=1), "utf-8")


def main():
    lessons = skeleton()
    save(lessons)
    if "--skeleton" in sys.argv:
        print(f"esqueleto salvo: {sum(1 for l in lessons if l['explicacao'])}/365 aulas completas")
        return
    import anthropic

    client = anthropic.Anthropic()
    todo = [l for l in lessons if not l["explicacao"]]
    print(f"gerando {len(todo)} aulas...")
    for start in range(0, len(todo), 10):
        batch = todo[start:start + 10]
        listing = "\n".join(f'{l["dia"]} | {l["modulo"]} | {l["titulo"]}' for l in batch)
        resp = client.messages.create(model=MODEL, max_tokens=8000,
                                      messages=[{"role": "user", "content": PROMPT + listing}])
        text = "".join(b.text for b in resp.content if b.type == "text")
        try:
            got = {g["dia"]: g for g in json.loads(re.search(r"\[.*\]", text, re.S).group(0))}
        except Exception as e:
            print(f"lote {batch[0]['dia']} falhou ({e}); rode de novo depois")
            continue
        for l in batch:
            g = got.get(l["dia"])
            if g:
                l.update(explicacao=g["explicacao"], exemplo=g["exemplo"], pergunta_reflexao=g["pergunta_reflexao"])
        save(lessons)
        print(f"  ok até o dia {batch[-1]['dia']}")
    print(f"pronto: {sum(1 for l in lessons if l['explicacao'])}/365 aulas completas")


if __name__ == "__main__":
    main()
