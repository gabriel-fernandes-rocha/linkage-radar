"""Busca na web para fontes sem API (LinkedIn, Sympla, Even3...).

Ordem de preferência:
  1. SerpAPI (Google), se SERPAPI_KEY existir — 100 buscas grátis/mês.
  2. Ferramenta web_search do Claude (US$ 10 / 1000 buscas + tokens), limitada por `max_uses`.

Para evitar alucinação, só aceitamos URLs que realmente vieram dos resultados da busca.
"""
from __future__ import annotations

import json
import os
import re

from common import clean, get, log

WEB_SEARCH_TOOL = "web_search_20250305"  # variante suportada pelo Claude Haiku 4.5


def serpapi(query: str, recency: str = "qdr:w") -> list[dict]:
    key = os.getenv("SERPAPI_KEY")
    if not key:
        return []
    data = get("https://serpapi.com/search.json",
               params={"engine": "google", "q": query, "api_key": key, "tbs": recency, "num": 20, "hl": "pt-BR"}).json()
    return [{"titulo": r.get("title", ""), "url": r.get("link", ""), "texto": clean(r.get("snippet")),
             "data": r.get("date", "")} for r in data.get("organic_results", [])]


def claude_search(cfg: dict, instructions: str, allowed_domains: list[str] | None, max_uses: int) -> list[dict]:
    if not os.getenv("ANTHROPIC_API_KEY"):
        log.info("websearch: sem ANTHROPIC_API_KEY, pulando")
        return []
    import anthropic

    client = anthropic.Anthropic()
    tool = {"type": WEB_SEARCH_TOOL, "name": "web_search", "max_uses": max_uses}
    if allowed_domains:
        tool["allowed_domains"] = allowed_domains
    prompt = (
        f"{instructions}\n\n"
        "Responda SOMENTE com um array JSON (sem texto antes ou depois), no formato:\n"
        '[{"titulo": "...", "url": "...", "texto": "resumo fiel de 1-2 frases do conteúdo", "data": "YYYY-MM-DD ou vazio"}]\n'
        "Use apenas URLs que apareceram nos resultados da busca. Se não achar nada relevante, responda []."
    )
    resp = client.messages.create(
        model=cfg["llm"]["model"],
        max_tokens=2000,
        tools=[tool],
        messages=[{"role": "user", "content": prompt}],
    )
    seen_urls = set()
    text = ""
    for block in resp.content:
        if block.type == "web_search_tool_result" and isinstance(block.content, list):
            seen_urls |= {r.url.split("?")[0].rstrip("/") for r in block.content}
        elif block.type == "text":
            text += block.text
    usage = resp.usage
    log.info("websearch: tokens in=%s out=%s", usage.input_tokens, usage.output_tokens)
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        results = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    # anti-alucinação: só URLs presentes nos resultados reais
    return [r for r in results
            if isinstance(r, dict) and r.get("url", "").split("?")[0].rstrip("/") in seen_urls]
