"""Etapa 2 — LLM como juiz. Julga vários itens por chamada para gastar o mínimo."""
from __future__ import annotations

import json
import os
import re

from common import LLM_STATE, get, log, no_dash, note_llm_error

SYSTEM = """Você avalia se itens são relevantes para um especialista em Record Linkage / Entity Matching / \
Entity Resolution (qualquer tipo de entidade) e Geocodificação tratada como problema de linkage \
(address matching, normalização e parsing de endereços, fuzzy matching de endereços, blocking).
O leitor quer ALTA PRECISÃO: na dúvida, reprove.

Regras por tipo:
- vaga: aprove se entity resolution / record linkage / entity matching / identity resolution / deduplicação / \
MDM (dados mestres, golden record, customer 360, CDP) / data matching / geocodificação ou address matching for o \
foco da função OU uma responsabilidade relevante descrita nas atividades/requisitos. A compatibilidade com o perfil \
é calculada depois, então NÃO reprove por local, senioridade ou idioma. Reprove só vagas que não tratam do tema \
(dados genéricos, BI, vendas, suporte), que citam o termo apenas na descrição institucional da empresa, ou vagas de "dados mestres" que são só cadastro operacional manual (cadastrar materiais/fornecedores no ERP, sem deduplicação, regras de matching, qualidade ou governança de dados mestres).
- vaga vinda de POST em rede social (fonte "Post · ..."): aprove só se o post anunciar uma vaga concreta e aberta (quem contrata, qual função) com foco no tema. Post genérico de "open to work", curso ou opinião = reprovar.
- pessoa (perfil do LinkedIn): aprove se a pessoa claramente trabalha, pesquisa ou lidera algo cujo foco é \
entity resolution / record linkage / MDM matching / identity resolution / geocodificação. No "resumo_pt" diga em \
1 frase quem é (cargo e empresa SOMENTE se estiverem escritos no texto; nunca deduza a empresa). Recrutador genérico ou menção de passagem = reprovar.
- empresa (página do LinkedIn): aprove se o produto/serviço central da empresa for esse tema (ou se ela for \
referência no assunto). No "resumo_pt" diga em 1 frase o que ela faz.
- evento: aprove somente se o tema central for isso E for no Brasil (ou online com organização/foco brasileiro claro). \
Eventos já encerrados = reprovar.
- paper: aprove se o problema central for linkage / ER / matching de registros ou entidades / geocodificação.
- linkedin: aprove se o post discutir tecnicamente (ou anunciar algo concreto: ferramenta, paper, vaga específica, \
evento) sobre esses temas. Autopromoção vazia, clickbait ou menção de passagem = reprovar.

Para cada item, responda um objeto: {"id": <id>, "relevante": bool, "confianca": 0-1, \
"motivo": "1 frase em português", "resumo_pt": "até 2 frases em português, fiel ao texto"}.
Nunca use travessão (— ou –) nos textos: use vírgula, dois-pontos ou ponto.
Responda SOMENTE com um array JSON com um objeto por item, na mesma ordem."""


def _system(cfg: dict) -> str:
    return SYSTEM + "\n\nPERFIL DO LEITOR:\n" + cfg.get("perfil", "")


def _payload(batch: list[dict]) -> str:
    rows = []
    for i, it in enumerate(batch):
        rows.append({
            "id": i, "tipo": it["tipo"], "titulo": it["titulo"],
            "empresa_ou_fonte": "" if it["tipo"] in ("pessoa", "empresa") else (it.get("empresa") or it.get("fonte", "")),
            "local": it.get("local", ""), "data": it.get("data", ""),
            "texto": (it.get("texto") or "")[:1200],
        })
    return json.dumps(rows, ensure_ascii=False)


def _parse(text: str) -> list[dict]:
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        raise ValueError(f"resposta sem JSON: {text[:200]}")
    return json.loads(m.group(0))


def available(cfg: dict) -> bool:
    from filters import providers

    return bool(providers.chain(cfg))


def judge(items: list[dict], cfg: dict) -> list[dict]:
    """Retorna só os aprovados, com motivo/resumo preenchidos. Marca it["_julgado"] nos que foram avaliados.

    Usa a cadeia de provedores (providers.py): Claude -> Gemini -> GitHub Models -> Groq -> OpenRouter ->
    Mistral -> Cerebras. Se nenhum responder, os itens ficam sem "_julgado" e o main_collect usa a heurística."""
    from filters import heuristic, providers

    llm = cfg["llm"]
    min_conf = llm.get("min_confidence", 0.8)
    size = llm.get("batch_size", 8)
    approved = []
    for start in range(0, len(items), size):
        batch = items[start:start + size]
        text = providers.complete(cfg, _system(cfg), _payload(batch))
        try:
            verdicts = _parse(text) if text else None
        except Exception as e:
            log.warning("judge: resposta ilegível de %s (%s)", providers.LAST_USED["nome"], str(e)[:150])
            verdicts = None
        if verdicts is None:
            continue
        ok_ids = set()
        for it in batch:
            it["_julgado"] = True
            it["juiz"] = providers.LAST_USED["nome"]
        if isinstance(verdicts, dict):  # alguns modelos embrulham a lista: {"itens": [...]}
            verdicts = next((x for x in verdicts.values() if isinstance(x, list)), [])
        for v in verdicts:
            if not isinstance(v, dict):
                continue
            try:
                it = batch[int(v["id"])]
            except (KeyError, ValueError, IndexError, TypeError):
                continue
            if v.get("relevante") is True and float(v.get("confianca", 0)) >= min_conf:
                it.update(motivo=no_dash(v.get("motivo", "")), resumo=no_dash(v.get("resumo_pt", "")),
                          confianca=round(float(v["confianca"]), 2))
                approved.append(it)
                ok_ids.add(id(it))
        heuristic.record(batch, ok_ids)  # cada decisão vira exemplo de treino da heurística
    return approved
