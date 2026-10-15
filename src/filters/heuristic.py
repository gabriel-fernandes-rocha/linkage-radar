"""Heurística de ALTA PRECISÃO para quando nenhuma IA responde.

1) Toda decisão dos juízes LLM fica gravada (data/judge_labels.json): título, trecho e aprovado/reprovado.
2) Com esse histórico, treinamos um Naive Bayes de palavras (unigramas + bigramas; o título pesa em dobro),
   separado por tipo (vaga / post e paper).
3) O limiar é escolhido por validação cruzada para PRECISÃO >= 95% (quando o modelo diz "sim", acerta 95%+
   das vezes no histórico). Se ainda há pouco histórico, vale só a regra rígida de palavras-chave.
4) Decisão final = regra rígida (keywords.strong_enough) E, havendo modelo, probabilidade >= limiar.
"""
from __future__ import annotations

import json
import math
import random
import re
from collections import Counter
from datetime import date

from common import DATA, log
from filters import keywords

LABELS = DATA / "judge_labels.json"
MIN_LABELS, MIN_POS, TARGET_PRECISION = 40, 8, 0.95
_MODELS: dict[str, dict | None] = {}


def _group(tipo: str) -> str:
    return "vaga" if tipo == "vaga" else "conteudo"


def _tokens(it: dict) -> list[str]:
    title = re.findall(r"[a-z0-9]+", keywords.normalize(it.get("titulo", "")))
    text = re.findall(r"[a-z0-9]+", keywords.normalize((it.get("texto") or "")[:600]))
    words = title * 2 + text
    return words + [f"{a}_{b}" for a, b in zip(words, words[1:])]


def record(batch: list[dict], approved_ids: set[int]) -> None:
    """Grava as decisões do juiz (base de treino da heurística)."""
    try:
        labels = json.loads(LABELS.read_text("utf-8")) if LABELS.exists() else []
        for it in batch:
            labels.append({"tipo": it.get("tipo"), "titulo": it.get("titulo", "")[:200],
                           "texto": (it.get("texto") or "")[:600], "ok": id(it) in approved_ids,
                           "data": date.today().isoformat()})
        LABELS.write_text(json.dumps(labels[-6000:], ensure_ascii=False), "utf-8")
    except Exception as e:
        log.warning("heurística: não consegui gravar rótulos (%s)", e)


def _fit(rows: list[dict]) -> dict:
    pos, neg = Counter(), Counter()
    npos = sum(r["ok"] for r in rows)
    for r in rows:
        (pos if r["ok"] else neg).update(set(_tokens(r)))
    vocab = set(pos) | set(neg)
    return {"pos": pos, "neg": neg, "npos": npos, "nneg": len(rows) - npos, "v": len(vocab) or 1}


def _logodds(m: dict, it: dict) -> float:
    s = math.log((m["npos"] + 1) / (m["nneg"] + 1))
    for t in set(_tokens(it)):
        s += math.log((m["pos"][t] + 1) / (m["npos"] + 2)) - math.log((m["neg"][t] + 1) / (m["nneg"] + 2))
    return s


def _train(group: str) -> dict | None:
    labels = json.loads(LABELS.read_text("utf-8")) if LABELS.exists() else []
    rows = [r for r in labels if _group(r.get("tipo", "")) == group]
    if len(rows) < MIN_LABELS or sum(r["ok"] for r in rows) < MIN_POS:
        log.info("heurística/%s: %d rótulos (precisa de %d); usando só a regra rígida", group, len(rows), MIN_LABELS)
        return None
    random.Random(42).shuffle(rows)
    scored = []  # (log-odds fora da amostra, rótulo): validação cruzada em 5 partes
    for k in range(5):
        test = rows[k::5]
        train = [r for i, r in enumerate(rows) if i % 5 != k]
        m = _fit(train)
        scored += [(_logodds(m, r), r["ok"]) for r in test]
    best = None
    for thr in sorted({s for s, _ in scored}, reverse=True):  # limiares distintos (empates entram juntos)
        sel = [ok for s, ok in scored if s >= thr]
        tp = sum(sel)
        if tp >= 3 and tp / len(sel) >= TARGET_PRECISION:
            best = thr  # menor limiar que ainda mantém a precisão: maximiza o recall
    if best is None:
        log.info("heurística/%s: histórico não atinge %d%% de precisão; usando só a regra", group,
                 TARGET_PRECISION * 100)
        return None
    m = _fit(rows)
    m["limiar"] = best
    prec = sum(ok for s, ok in scored if s >= best) / max(1, sum(1 for s, _ in scored if s >= best))
    rec = sum(ok for s, ok in scored if s >= best) / max(1, sum(ok for _, ok in scored))
    log.info("heurística/%s: %d rótulos, precisão %.0f%% e recall %.0f%% na validação", group, len(rows),
             100 * prec, 100 * rec)
    m["precisao"], m["recall"] = round(prec, 2), round(rec, 2)
    return m


def approve(it: dict) -> bool:
    """Decisão de contingência (sem IA): regra rígida E, se houver histórico suficiente, o modelo."""
    if not keywords.strong_enough(it):
        return False
    g = _group(it.get("tipo", ""))
    if g not in _MODELS:
        _MODELS[g] = _train(g)
    m = _MODELS[g]
    return True if m is None else _logodds(m, it) >= m["limiar"]
