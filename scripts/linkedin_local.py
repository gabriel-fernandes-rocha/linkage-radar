"""Varredura do LinkedIn LOGADO, rodando no seu computador (1x por dia, ao ligar o Windows).

O radar no GitHub não tem acesso a uma conta logada; este script complementa a aba "Brasil" com o que só
aparece logado: busca de PESSOAS, EMPRESAS, VAGAS e POSTS. Ele usa um navegador Chrome próprio (pasta
separada, com a conta não oficial "IAGs" logada uma única vez) e grava:
    data/brasil/people.json, data/brasil/companies.json  -> pessoas e empresas do tema (direto no site)
    data/brasil/linkedin_local.json                      -> vagas/posts candidatos; a coleta da noite julga
e faz commit + push.

Uso:
    python scripts/linkedin_local.py --login     # 1ª vez: abre o navegador para você entrar na conta
    python scripts/linkedin_local.py             # varredura (pula se já rodou hoje)
    python scripts/linkedin_local.py --forcar    # roda mesmo se já rodou hoje

Cautela contra bloqueio: poucas buscas por dia, pausas aleatórias de 8 a 18 s, só leitura (nunca segue,
conecta, curte ou manda mensagem), e para no primeiro sinal de bloqueio/verificação.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

PROFILE_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "linkage-radar" / "linkedin-chrome"
STAMP = PROFILE_DIR.parent / "ultima_varredura.txt"
LOG = ROOT / "data" / "logs" / "linkedin_local.log"
OUT = ROOT / "data" / "brasil" / "linkedin_local.json"
GEO_BR = "106057199"

# "dados mestres"/"master data management" saíram: trazem analistas de cadastro SAP, não linkage
PESSOAS = ["record linkage", "entity resolution", "identity resolution", "data matching", "deduplicação de dados",
           "resolução de entidades", "golden record", "linkage de dados", "fuzzy matching", "MDM matching"]
EMPRESAS = ["master data management", "entity resolution", "qualidade de dados", "dados cadastrais",
            "enriquecimento de dados"]
VAGAS = ["entity resolution", "record linkage", "deduplicação", "dados mestres", "golden record",
         "integração de dados", "migração de dados", "data matching", "MDM", "qualidade de dados"]
POSTS = ["vaga record linkage", "vaga entity resolution", "vaga deduplicação de dados", "vaga dados mestres",
         "vaga integração de dados", "vaga migração de dados"]
EXCLUIR = re.compile(r"(cidacs|gabrielfernandesrocha)", re.I)  # você e o seu instituto ficam de fora

JS_PEOPLE = r"""(sel) => {
  const seen = new Map();
  for (const a of document.querySelectorAll('main a[href*="' + sel + '"]')) {
    const u = a.href.split('?')[0];
    if (seen.has(u)) continue;
    let b = a;
    for (let k = 0; k < 8 && b.parentElement; k++) { b = b.parentElement; if (b.innerText.split('\n').filter(Boolean).length >= 3) break; }
    const lines = b.innerText.split('\n').map(s => s.trim()).filter(Boolean)
      .filter(l => !/^(Conectar|Seguir|Mensagem|Connect|Follow|Message|• ?\d|\d+º)/.test(l));
    seen.set(u, lines.slice(0, 5));
  }
  return [...seen].map(([url, lines]) => ({url, lines}));
}"""
JS_JOBS = r"""() => {
  const out = new Map();
  for (const a of document.querySelectorAll('a[href*="/jobs/view/"], a[href*="currentJobId="]')) {
    const m = a.href.match(/view\/(\d+)|currentJobId=(\d+)/); const id = m && (m[1] || m[2]);
    if (!id || out.has(id)) continue;
    let b = a;
    for (let k = 0; k < 6 && b.parentElement; k++) { b = b.parentElement; if (b.innerText.split('\n').filter(Boolean).length >= 3) break; }
    out.set(id, b.innerText.split('\n').map(s => s.trim()).filter(Boolean).slice(0, 5));
  }
  return [...out].map(([id, lines]) => ({id, lines}));
}"""
JS_POSTS = r"""() => (document.querySelector('main') || document.body).innerText
  .split(/Publicação no feed|Feed post/).slice(1).map(b => b.trim())"""


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def pausa(a: float = 8, b: float = 18) -> None:
    time.sleep(random.uniform(a, b))


class Bloqueado(Exception):
    pass


def abrir(page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    time.sleep(random.uniform(4, 7))
    for _ in range(2):  # rola como uma pessoa para carregar mais resultados
        page.mouse.wheel(0, random.randint(1500, 2600))
        time.sleep(random.uniform(1.5, 3))
    u = page.url
    if any(k in u for k in ("/login", "/checkpoint", "/authwall", "challenge")):
        raise Bloqueado(f"LinkedIn pediu login/verificação ({u[:80]})")


# termos que sozinhos não indicam linkage (MDM no Brasil costuma ser cadastro manual no ERP)
FRACOS = {"mdm", "master data", "dados mestres", "master data management", "gestao de dados mestres", "blocking",
          "dedup", "levenshtein", "geocodificacao", "customer 360", "cliente 360", "higienizacao de dados"}
EMPRESA_EXTRA = ["qualidade de dados", "data quality", "dados cadastrais", "enriquecimento de dados", "governanca de dados"]


def forte(texto: str) -> list[str]:
    return [k for k in tema(texto) if k not in FRACOS]


def tema(texto: str) -> list[str]:
    from filters.keywords import _has, normalize

    import brasil

    t = normalize(texto)
    extra = ["mdm", "master data", "dados mestres", "data matching", "linkage", "identity resolution"]
    return [k for k in dict.fromkeys(brasil.TEMA + extra) if _has(k, t)]


def buscar_pessoas(page) -> list[dict]:
    achados = []
    for termo in PESSOAS:
        abrir(page, f"https://www.linkedin.com/search/results/people/?keywords={quote(termo)}"
                    f"&geoUrn=%5B%22{GEO_BR}%22%5D")
        for r in page.evaluate(JS_PEOPLE, "/in/"):
            nome, resto = (r["lines"] or [""])[0], " | ".join(r["lines"][1:])
            if EXCLUIR.search(r["url"] + resto) or not forte(resto):
                continue
            achados.append({"nome": nome, "titulo": nome, "url": r["url"], "resumo": resto[:220],
                            "fonte": "LinkedIn (varredura logada)", "texto": resto})
        pausa()
    return achados


def buscar_empresas(page) -> list[dict]:
    achados = []
    for termo in EMPRESAS:
        abrir(page, f"https://www.linkedin.com/search/results/companies/?keywords={quote(termo)}"
                    f"&companyHqGeo=%5B%22{GEO_BR}%22%5D")
        for r in page.evaluate(JS_PEOPLE, "/company/"):
            nome, resto = (r["lines"] or [""])[0], " | ".join(r["lines"][1:])
            from filters.keywords import _has, normalize

            txt = normalize(nome + " " + resto)
            if not (tema(nome + " " + resto) or any(_has(k, txt) for k in EMPRESA_EXTRA)):
                continue
            achados.append({"nome": nome, "titulo": nome, "url": r["url"], "resumo": resto[:220],
                            "fonte": "LinkedIn (varredura logada)"})
        pausa()
    return achados


def buscar_vagas(page) -> list[dict]:
    """Coleta IDs de vagas pela busca logada e lê a descrição inteira pela página pública da vaga."""
    import brasil
    from sources import linkedin_guest as lg
    from sources.brasil_jobs import DATA_TITLE
    from sources.jobs import _job

    ids = {}
    for termo in VAGAS:
        abrir(page, f"https://www.linkedin.com/jobs/search/?keywords={quote(termo)}&geoId={GEO_BR}&f_TPR=r604800")
        for r in page.evaluate(JS_JOBS):
            if r["id"] not in ids and r["lines"] and DATA_TITLE.search(r["lines"][0]):
                ids[r["id"]] = r["lines"]
        pausa()
    vagas = []
    for jid, lines in ids.items():
        d = lg._get(lg.DETAIL.format(jid))
        m = re.search(r'show-more-less-html__markup[^>]*>(.*?)</div>', d.text, re.S) if d is not None else None
        texto = lg._text(m.group(1)) if m else ""
        empresa = next((l for l in lines[1:] if "with verification" not in l and l != lines[0]), "")
        local = next((l for l in lines if re.search(r"(Brasil|Brazil|Remoto|Híbrido|Presencial)", l)), "Brasil")
        it = _job(lines[0], f"https://www.linkedin.com/jobs/view/{jid}", empresa, local, texto, "LinkedIn Jobs (Brasil)")
        if brasil.passes(dict(it)):
            vagas.append(it)
    log(f"vagas: {len(ids)} de dados vistas na busca logada, {len(vagas)} passam no filtro da aba Brasil")
    return vagas


def buscar_posts(page) -> list[dict]:
    from sources.jobs import _job

    posts = []
    for termo in POSTS:
        abrir(page, f"https://www.linkedin.com/search/results/content/?keywords={quote(termo)}"
                    "&datePosted=%22past-week%22&sortBy=%22date_posted%22")
        for bloco in page.evaluate(JS_POSTS):
            linhas = [l.strip() for l in bloco.split("\n") if l.strip()]
            vaga = re.search(r"(vaga|contratando|hiring|estamos buscando|procuramos|oportunidade)", bloco, re.I)
            if not (vaga and tema(bloco)) or not linhas:
                continue
            links = re.findall(r"https?://\S+", bloco)
            url = links[0] if links else (f"https://www.linkedin.com/search/results/content/?keywords="
                                          f"{quote(' '.join(linhas[:1] + tema(bloco)[:2]))}")
            it = _job(f"{linhas[0]} on LinkedIn: {' '.join(linhas[3:6])[:120]}", url, "", "Brasil", bloco[:4000],
                      "Post · LinkedIn (Brasil)")
            it["social"] = True
            posts.append(it)
        pausa()
    log(f"posts: {len(posts)} com vaga e tema")
    return posts


def salvar(pessoas: list[dict], empresas: list[dict], vagas: list[dict]) -> None:
    from sources import network

    day = date.today().isoformat()
    p = network._merge(ROOT / "data" / "brasil" / "people.json", pessoas, day, 25)
    c = network._merge(ROOT / "data" / "brasil" / "companies.json", empresas, day, 15)
    atual = json.loads(OUT.read_text("utf-8")) if OUT.exists() else []
    limite = (date.today() - timedelta(days=14)).isoformat()
    urls = {j["url"] for j in atual}
    atual = [j for j in atual if j.get("visto_em", "") >= limite] + \
            [{**j, "visto_em": day} for j in vagas if j["url"] not in urls]
    OUT.write_text(json.dumps(atual, ensure_ascii=False, indent=1), "utf-8")
    log(f"salvo: {sum(x.get('desde') == day for x in p)} pessoas novas, {sum(x.get('desde') == day for x in c)} "
        f"empresas novas, {len(vagas)} vagas/posts candidatos")


def publicar() -> None:
    files = ["data/brasil/people.json", "data/brasil/companies.json", "data/brasil/linkedin_local.json",
             "data/logs/linkedin_local.log"]
    run = lambda *a: subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)
    run("stash", "push", "--include-untracked", "--", *files)
    run("pull", "--rebase", "-X", "theirs")
    run("stash", "pop")
    run("add", *files)
    if run("diff", "--cached", "--quiet").returncode == 0:
        log("nada novo para publicar")
        return
    run("commit", "-m", "radar: varredura do LinkedIn logado (computador local)")
    for _ in range(3):
        if run("push").returncode == 0:
            log("publicado no GitHub")
            return
        run("pull", "--rebase", "-X", "theirs")
        time.sleep(5)
    log("não consegui publicar (sem internet?); tento de novo na próxima vez")


def navegador(p, visivel: bool):
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return p.chromium.launch_persistent_context(
        str(PROFILE_DIR), channel="chrome", headless=False, viewport={"width": 1280, "height": 900},
        args=[] if visivel else ["--start-minimized"], locale="pt-BR")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true", help="abre o navegador para você entrar na conta")
    ap.add_argument("--forcar", action="store_true", help="roda mesmo se já rodou hoje")
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright

    if args.login:
        # Chrome NORMAL (sem automação) na mesma pasta: o Google bloqueia "Entrar com Google" em navegador
        # automatizado. Você entra, fecha a janela, e a varredura reaproveita o login salvo.
        chrome = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe"
        if chrome.exists():
            PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            subprocess.run([str(chrome), f"--user-data-dir={PROFILE_DIR}", "--no-first-run",
                            "https://www.linkedin.com/login"])
            print("Entre na conta (pode ser pelo Google) e FECHE a janela do Chrome quando o feed aparecer.")
            return 0
        with sync_playwright() as p:
            ctx = navegador(p, visivel=True)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://www.linkedin.com/login")
            print("Entre na conta IAGs na janela que abriu. Ela fecha sozinha quando o feed aparecer (até 15 min).")
            ok = False
            for _ in range(180):
                time.sleep(5)
                if "/feed" in page.url:
                    ok = True
                    time.sleep(5)  # deixa os cookies gravarem
                    break
            ctx.close()
        print("Login salvo." if ok else "Não vi o feed; rode --login de novo se a varredura falhar.")
        return 0

    hoje = date.today().isoformat()
    if not args.forcar and STAMP.exists() and STAMP.read_text().strip() == hoje:
        print("A varredura de hoje já rodou.")
        return 0
    time.sleep(random.uniform(30, 90))  # deixa o Windows e a internet subirem
    log("===== varredura do LinkedIn logado =====")
    pessoas, empresas, vagas = [], [], []
    with sync_playwright() as p:
        ctx = navegador(p, visivel=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            abrir(page, "https://www.linkedin.com/feed/")
            pessoas = buscar_pessoas(page)
            log(f"pessoas: {len(pessoas)} do tema")
            empresas = buscar_empresas(page)
            log(f"empresas: {len(empresas)}")
            vagas = buscar_vagas(page) + buscar_posts(page)
        except Bloqueado as e:
            log(f"PAROU: {e}. Rode: python scripts/linkedin_local.py --login")
        except Exception as e:  # nunca trava o computador do usuário
            log(f"erro: {str(e)[:300]}")
        finally:
            ctx.close()
    if pessoas or empresas or vagas:
        salvar(pessoas, empresas, vagas)
        STAMP.parent.mkdir(parents=True, exist_ok=True)
        STAMP.write_text(hoje)
    publicar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
