import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from main_send import build_lesson_message, build_message  # noqa: E402
from notify.callmebot import MAX_ENCODED  # noqa: E402
from urllib.parse import quote_plus  # noqa: E402


def _rep(n):
    jobs = [{"titulo": "Entity Resolution Engineer — Remote", "empresa": "X", "local": "Remoto",
             "url": f"https://x.co/{i}", "encaixe": i / 10} for i in range(n)]
    return {"data": "2026-09-28", "vagas": jobs, "eventos": [], "papers": [], "linkedin": [],
            "aula": {"dia": 1, "titulo": "Intro", "explicacao": "Record linkage liga registros. Mais texto."}}


def test_empty_day():
    msg = build_message(_rep(0), "https://site")
    assert "Nenhuma vaga aberta" in msg and "28/09" in msg


def test_long_message_truncated():
    msg = build_message(_rep(10), "https://site")
    assert len(quote_plus(msg)) <= MAX_ENCODED  # cabe em UMA mensagem do WhatsApp
    assert "10 vagas novas hoje" in msg and msg.count("% compatível") == 3 and "—" not in msg


def test_jobs_sorted_by_compatibility():
    rep = _rep(0)
    rep["vagas"] = [{"titulo": "Baixa", "url": "u1", "encaixe": 0.3}, {"titulo": "Alta", "url": "u2", "encaixe": 0.9}]
    msg = build_message(rep, "https://site")
    assert msg.index("90% compatível") < msg.index("30% compatível")


def test_lesson_message_is_complete():
    rep = _rep(0)
    rep["aula"] = {"dia": 3, "modulo": "1. Fundamentos", "titulo": "T", "explicacao": "E " * 100,
                   "exemplo": "X", "pergunta_reflexao": "P?"}
    msg = build_lesson_message(rep, "https://site")
    assert ("E " * 100).strip() in msg and "Exemplo: X" in msg and "Para pensar: P?" in msg


def test_callmebot_split_respects_encoded_limit():
    from urllib.parse import quote_plus

    from notify.callmebot import MAX_ENCODED, split

    text = "\n".join(f"📡 linha {i} com acentuação e emoji 🎓 https://exemplo.com/{'x' * 40}" for i in range(30))
    parts = split(text)
    assert len(parts) > 1
    assert all(len(quote_plus(p)) <= MAX_ENCODED for p in parts)
    assert "\n".join(parts) == text  # nada se perde
