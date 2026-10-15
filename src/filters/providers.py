"""Cadeia de juízes LLM: tenta cada provedor em ordem e usa o primeiro que responder.

Claude (pago, principal) -> Gemini -> GitHub Models -> Groq -> OpenRouter -> Mistral -> Cerebras (grátis).
Provedor sem chave é pulado. Provedor que falhar por limite/saldo/autenticação é desligado no resto da coleta.
Chaves gratuitas não expiram: cadastre como Secrets do GitHub (nomes em PROVIDERS[...]["env"]).
"""
from __future__ import annotations

import os
import re
import time

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
_DISCOVERED: dict[str, list[str]] = {}  # modelos disponíveis hoje, por provedor (descobertos na hora)

# Nomes de modelos gratuitos mudam toda hora (em out/2026 vários foram retirados). Por isso cada provedor
# descobre a lista ATUAL de modelos e escolhemos pelo padrão de preferência, nunca por nome fixo.
PREFS = {
    "gemini": [r"gemini-[\d.]+-flash$", r"gemini-[\d.]+-flash-\d", r"gemini-[\d.]+-pro$", r"flash"],
    "github": [r"gpt-4\.1-mini", r"gpt-4o-mini", r"gpt-4\.1$", r"gpt-4o$", r"llama", r"mistral"],
    "groq": [r"llama-3\.3-70b", r"llama-4", r"gpt-oss-120b", r"qwen.*32b", r"llama.*70b", r"gpt-oss", r"llama"],
    "openrouter": [r"deepseek.*:free", r"llama.*70b.*:free", r"qwen.*:free", r"gemma.*:free", r"mistral.*:free",
                   r":free$"],
    "mistral": [r"mistral-small-latest", r"mistral-small", r"open-mistral", r"ministral"],
    "cerebras": [r"llama-3\.3-70b", r"gpt-oss", r"qwen", r"llama"],
}
_GH_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def _version_key(name: str) -> list[float]:
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", name)][:3] or [0.0]


def _list_models(name: str) -> list[str]:
    """Lista os modelos disponíveis AGORA para a sua chave."""
    try:
        if name == "gemini":
            r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                             params={"key": os.environ["GEMINI_API_KEY"], "pageSize": 200}, timeout=30)
            return [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
                    if "generateContent" in m.get("supportedGenerationMethods", [])
                    and not re.search(r"(lite|preview|exp|tts|image|audio|live|embedding|thinking)", m["name"])]
        if name == "github":
            r = requests.get("https://models.github.ai/catalog/models", timeout=30,
                             headers={**_GH_HEADERS, "Authorization": f"Bearer {os.environ['GITHUB_MODELS_TOKEN']}"})
            return [m["id"] for m in r.json()]
        if name == "openrouter":
            r = requests.get("https://openrouter.ai/api/v1/models", timeout=30)
            return [m["id"] for m in r.json().get("data", []) if m["id"].endswith(":free")
                    and (m.get("context_length") or 0) >= 16000]
        p = PROVIDERS[name]
        base = p["url"].rsplit("/chat/completions", 1)[0]
        r = requests.get(f"{base}/models", timeout=30, headers={"Authorization": f"Bearer {os.environ[p['env']]}"})
        return [m["id"] for m in r.json().get("data", [])]
    except Exception as e:
        log.warning("judge: não consegui listar modelos de %s (%s)", name, str(e)[:120])
        return []


def candidates(name: str, preferred: str | None) -> list[str]:
    """Modelos a tentar, em ordem: o configurado (se ainda existir) e os melhores da lista atual."""
    if name not in _DISCOVERED:
        avail = _list_models(name)
        ranked = []
        for pat in PREFS.get(name, []):
            hits = sorted((m for m in avail if re.search(pat, m) and m not in ranked), key=_version_key, reverse=True)
            ranked += hits
        _DISCOVERED[name] = ranked[:3]
        if ranked:
            log.info("judge: modelos de %s disponíveis hoje: %s", name, ", ".join(ranked[:3]))
    out = [m for m in [preferred] if m and (not _DISCOVERED[name] or m in _list_cache(name))]
    return out + [m for m in _DISCOVERED[name] if m not in out] or ([preferred] if preferred else [])


def _list_cache(name: str) -> list[str]:
    return _DISCOVERED.get(name, [])
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
    headers = {"Authorization": f"Bearer {os.environ[p['env']]}", "Content-Type": "application/json"}
    if name == "github":
        headers.update(_GH_HEADERS)
    r = requests.post(p["url"], timeout=90, headers=headers,
                      json={"model": model, "max_tokens": max_tokens, "temperature": 0,
                            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    if r.status_code >= 400:
        raise RuntimeError(f"{name} {r.status_code}: {r.text[:300]}")
    try:
        return r.json()["choices"][0]["message"]["content"]
    except Exception:
        raise RuntimeError(f"{name} resposta inesperada {r.status_code}: {r.text[:200]!r}")


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
    """Pergunta ao 1º provedor disponível da cadeia. Retorna None se nenhum responder.
    - modelo inexistente (404): tenta o próximo modelo descoberto do mesmo provedor;
    - limite por minuto (429): espera e tenta de novo uma vez;
    - sem saldo/chave inválida: desliga o provedor no resto da coleta."""
    for name, configured in chain(cfg):
        models = [configured] if name == "anthropic" else candidates(name, configured)
        for model in models:
            for attempt in (1, 2):
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
                        break
                    if " 429" in msg and attempt == 1:
                        time.sleep(8)
                        continue
                    log.warning("judge: %s/%s falhou (%s)", name, model, str(e)[:200])
                    if " 404" in msg or "not found" in msg or "does not exist" in msg or "unavailable" in msg:
                        break  # este modelo saiu: tenta o próximo modelo do mesmo provedor
                    if any(k in msg for k in (" 401", " 402", " 403", " 429", "quota", "insufficient",
                                              "unauthorized", "forbidden")):
                        DOWN.add(name)
                    break
            if name in DOWN or (name == "anthropic" and LLM_STATE["anthropic_down"]):
                break
    return None
