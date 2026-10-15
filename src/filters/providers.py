"""Cadeia de juízes LLM: tenta cada provedor em ordem e usa o primeiro que responder.

Claude (pago, principal) -> Gemini -> GitHub Models -> Groq -> OpenRouter -> Mistral -> Cerebras (grátis).
Provedor sem chave é pulado. Provedor que falhar por limite/saldo/autenticação é desligado no resto da coleta.
Chaves gratuitas não expiram: cadastre como Secrets do GitHub (nomes em PROVIDERS[...]["env"]).
"""
from __future__ import annotations

import os

import requests

from common import LLM_STATE, log, note_llm_error

# OpenAI-compatíveis (mesmo formato de chamada): url, variável de ambiente da chave, modelo padrão
PROVIDERS = {
    "github": {"url": "https://models.github.ai/inference/chat/completions", "env": "GITHUB_MODELS_TOKEN",
               "model": "openai/gpt-4.1-mini"},
    "groq": {"url": "https://api.groq.com/openai/v1/chat/completions", "env": "GROQ_API_KEY",
             "model": "llama-3.3-70b-versatile"},
    "openrouter": {"url": "https://openrouter.ai/api/v1/chat/completions", "env": "OPENROUTER_API_KEY",
                   "model": "meta-llama/llama-3.3-70b-instruct:free"},
    "mistral": {"url": "https://api.mistral.ai/v1/chat/completions", "env": "MISTRAL_API_KEY",
                "model": "mistral-small-latest"},
    "cerebras": {"url": "https://api.cerebras.ai/v1/chat/completions", "env": "CEREBRAS_API_KEY",
                 "model": "llama-3.3-70b"},
}
DOWN: set[str] = set()  # provedores desligados nesta execução
LAST_USED = {"nome": ""}


def _anthropic(model: str, system: str, user: str, max_tokens: int) -> str:
    import anthropic

    resp = anthropic.Anthropic().messages.create(model=model, max_tokens=max_tokens, system=system,
                                                 messages=[{"role": "user", "content": user}])
    log.info("judge: tokens in=%s out=%s", resp.usage.input_tokens, resp.usage.output_tokens)
    return "".join(b.text for b in resp.content if b.type == "text")


def _gemini(model: str, system: str, user: str, max_tokens: int) -> str:
    r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                      params={"key": os.environ["GEMINI_API_KEY"]}, timeout=90,
                      json={"systemInstruction": {"parts": [{"text": system}]},
                            "contents": [{"parts": [{"text": user}]}],
                            "generationConfig": {"responseMimeType": "application/json",
                                                 "maxOutputTokens": max_tokens}})
    if r.status_code >= 400:
        raise RuntimeError(f"gemini {r.status_code}: {r.text[:300]}")
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _openai_compatible(name: str, model: str, system: str, user: str, max_tokens: int) -> str:
    p = PROVIDERS[name]
    r = requests.post(p["url"], timeout=90, headers={"Authorization": f"Bearer {os.environ[p['env']]}"},
                      json={"model": model, "max_tokens": max_tokens, "temperature": 0,
                            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    if r.status_code >= 400:
        raise RuntimeError(f"{name} {r.status_code}: {r.text[:300]}")
    return r.json()["choices"][0]["message"]["content"]


def chain(cfg: dict) -> list[tuple[str, str]]:
    """[(provedor, modelo)] na ordem configurada, só os que têm chave e não caíram nesta execução."""
    llm = cfg["llm"]
    order = llm.get("cadeia", ["anthropic", "gemini", "github", "groq", "openrouter", "mistral", "cerebras"])
    models = llm.get("modelos_reserva", {})
    out = []
    for name in order:
        if name in DOWN or (name == "anthropic" and LLM_STATE["anthropic_down"]):
            continue
        if name == "anthropic" and os.getenv("ANTHROPIC_API_KEY"):
            out.append((name, llm["model"]))
        elif name == "gemini" and os.getenv("GEMINI_API_KEY"):
            out.append((name, models.get("gemini", llm.get("fallback_model", "gemini-2.5-flash"))))
        elif name in PROVIDERS and os.getenv(PROVIDERS[name]["env"]):
            out.append((name, models.get(name, PROVIDERS[name]["model"])))
    return out


def complete(cfg: dict, system: str, user: str, max_tokens: int = 4000) -> str | None:
    """Pergunta ao 1º provedor disponível da cadeia. Retorna None se nenhum responder."""
    for name, model in chain(cfg):
        try:
            if name == "anthropic":
                text = _anthropic(model, system, user, max_tokens)
            elif name == "gemini":
                text = _gemini(model, system, user, max_tokens)
            else:
                text = _openai_compatible(name, model, system, user, max_tokens)
            if LAST_USED["nome"] != name:
                log.info("judge: usando %s (%s)", name, model)
            LAST_USED["nome"] = name
            return text
        except Exception as e:
            msg = str(e).lower()
            if name == "anthropic" and note_llm_error(e):
                continue
            if any(k in msg for k in (" 401", " 402", " 403", " 429", "quota", "rate limit", "limit exceeded",
                                      "insufficient", "unauthorized", "forbidden")):
                DOWN.add(name)  # limite/chave: não insiste com esse provedor hoje
            log.warning("judge: %s falhou (%s)", name, str(e)[:200])
    return None
