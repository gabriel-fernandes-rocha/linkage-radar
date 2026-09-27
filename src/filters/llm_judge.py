"""Etapa 2 — LLM como juiz. Julga vários itens por chamada para gastar o mínimo."""
from __future__ import annotations

import json
import os
import re

from common import get, log, no_dash

SYSTEM = """Você avalia se itens são relevantes para um especialista em Record Linkage / Entity Matching / \
Entity Resolution (qualquer tipo de entidade) e Geocodificação tratada como problema de linkage \
(address matching, normalização e parsing de endereços, fuzzy matching de endereços, blocking).
O leitor quer ALTA PRECISÃO: na dúvida, reprove.

Regras por tipo:
- vaga: aprove SOMENTE se o foco principal da função for entity matching / record linkage / entity \
resolution / deduplicação de registros / MDM matching, ou geocodificação / address matching. Vagas genéricas \
de dados, BI, GIS ou ML que só citam o termo de passagem = reprovar.
- vaga vinda de POST em rede social (fonte "Post · ..."): aprove só se o post anunciar uma vaga concreta e aberta (quem contrata, qual função) com foco no tema. Post genérico de "open to work", curso ou opinião = reprovar.
- evento: aprove somente se o tema central for isso E for no Brasil (ou online com organização/foco brasileiro claro). \
Eventos já encerrados = reprovar.
- paper: aprove se o problema central for linkage / ER / matching de registros ou entidades / geocodificação.
- linkedin: aprove se o post discutir tecnicamente (ou anunciar algo concreto: ferramenta, paper, vaga específica, \
evento) sobre esses temas. Autopromoção vazia, clickbait ou menção de passagem = reprovar.

Para cada item, responda um objeto: {"id": <id>, "relevante": bool, "confianca": 0-1, \
"motivo": "1 frase em português", "resumo_pt": "até 2 frases em português, fiel ao texto", \
"encaixe": 0-1, "nota_perfil": "1 frase"}.
"encaixe" e "nota_perfil" valem só para vagas: o quanto a vaga combina com o PERFIL DO LEITOR abaixo \
(senioridade, stack, idioma, localização/modalidade — presencial fora do Brasil exige visto e reduz muito o \
encaixe; remoto global ou no Brasil é ideal). Para outros tipos, use encaixe 0 e nota_perfil "".
Nunca use travessão (— ou –) nos textos: use vírgula, dois-pontos ou ponto.
Responda SOMENTE com um array JSON com um objeto por item, na mesma ordem."""


def _system(cfg: dict) -> str:
    return SYSTEM + "\n\nPERFIL DO LEITOR:\n" + cfg.get("perfil", "")


def _payload(batch: list[dict]) -> str:
    rows = []
    for i, it in enumerate(batch):
        rows.append({
            "id": i, "tipo": it["tipo"], "titulo": it["titulo"],
            "empresa_ou_fonte": it.get("empresa") or it.get("fonte", ""),
            "local": it.get("local", ""), "data": it.get("data", ""),
            "texto": (it.get("texto") or "")[:1200],
        })
    return json.dumps(rows, ensure_ascii=False)


def _parse(text: str) -> list[dict]:
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        raise ValueError(f"resposta sem JSON: {text[:200]}")
    return json.loads(m.group(0))


def _anthropic(model: str, content: str, system: str) -> str:
    import anthropic

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model,
        max_tokens=4000,
        system=system,
        messages=[{"role": "user", "content": content}],
    )
    log.info("judge: tokens in=%s out=%s", resp.usage.input_tokens, resp.usage.output_tokens)
    return "".join(b.text for b in resp.content if b.type == "text")


def _gemini(model: str, content: str, system: str) -> str:
    import requests

    key = os.environ["GEMINI_API_KEY"]
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": key},
        json={"systemInstruction": {"parts": [{"text": system}]},
              "contents": [{"parts": [{"text": content}]}],
              "generationConfig": {"responseMimeType": "application/json"}},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def available(cfg: dict) -> bool:
    provider = cfg["llm"]["provider"]
    return bool(os.getenv("GEMINI_API_KEY" if provider == "gemini" else "ANTHROPIC_API_KEY"))


def judge(items: list[dict], cfg: dict) -> list[dict]:
    """Retorna só os aprovados, com motivo/resumo preenchidos."""
    llm = cfg["llm"]
    call = _gemini if llm["provider"] == "gemini" else _anthropic
    min_conf = llm.get("min_confidence", 0.8)
    size = llm.get("batch_size", 8)
    approved = []
    for start in range(0, len(items), size):
        batch = items[start:start + size]
        try:
            verdicts = _parse(call(llm["model"], _payload(batch), _system(cfg)))
        except Exception as e:
            log.warning("judge: lote falhou (%s) — itens descartados (precisão > recall)", e)
            continue
        for v in verdicts:
            try:
                it = batch[int(v["id"])]
            except (KeyError, ValueError, IndexError, TypeError):
                continue
            if v.get("relevante") is True and float(v.get("confianca", 0)) >= min_conf:
                it.update(motivo=no_dash(v.get("motivo", "")), resumo=no_dash(v.get("resumo_pt", "")),
                          confianca=round(float(v["confianca"]), 2))
                if it["tipo"] == "vaga" or "/jobs/view/" in it.get("url", ""):
                    it.update(encaixe=round(float(v.get("encaixe") or 0), 2), nota_perfil=no_dash(v.get("nota_perfil", "")))
                approved.append(it)
    return approved
