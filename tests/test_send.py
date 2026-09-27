import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from main_send import MAX_CHARS, build_message  # noqa: E402


def _rep(n):
    job = {"titulo": "Entity Resolution Engineer " * 3, "empresa": "X", "local": "Remoto", "url": "https://x.co/" + "a" * 60}
    return {"data": "2026-09-28", "vagas": [job] * n, "eventos": [], "papers": [], "linkedin": [],
            "aula": {"dia": 1, "titulo": "Intro", "explicacao": "Record linkage liga registros. Mais texto."}}


def test_empty_day():
    msg = build_message(_rep(0), "https://site")
    assert "Nada novo hoje ✅" in msg and "28/09" in msg and "Aula 1: Intro" in msg


def test_long_message_truncated():
    msg = build_message(_rep(10), "https://site")
    assert len(msg) <= MAX_CHARS
    assert "Vagas novas: 10" in msg and "Ver tudo: https://site" in msg


def test_callmebot_split_respects_encoded_limit():
    from urllib.parse import quote_plus

    from notify.callmebot import MAX_ENCODED, split

    text = "\n".join(f"📡 linha {i} com acentuação e emoji 🎓 https://exemplo.com/{'x' * 40}" for i in range(30))
    parts = split(text)
    assert len(parts) > 1
    assert all(len(quote_plus(p)) <= MAX_ENCODED for p in parts)
    assert "\n".join(parts) == text  # nada se perde
