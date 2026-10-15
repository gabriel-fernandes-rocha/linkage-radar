"""Trilha BRASIL: a aba "Brasil" do site.

Vagas NO BRASIL (presenciais, híbridas ou remotas para o Brasil) com entity resolution e todas as variações:
record linkage, resolução de identidade/entidades, data matching, matching determinístico/probabilístico,
deduplicação, golden record, dados mestres com matching, unificação de cadastros, Customer 360...
Além de pessoas e empresas brasileiras do tema.

O ponto crítico é RECALL: a vaga perfeita costuma ter título genérico ("Cientista de Dados Pleno") e o tema só
na descrição. Por isso: fontes com descrição inteira (InHire, Gupy, Google Jobs, Greenhouse/Lever/Ashby de
empresas brasileiras + tudo o que o radar principal já coleta) e filtro que lê o texto todo em português e inglês.

Dados em data/brasil/: open_jobs.json, archive.json, skills.json, people.json, companies.json, seen.json,
inhire_tenants.json (empresas da InHire descobertas automaticamente).
Sem IA: regras aprovam só o que tem sinal forte do tema (marcado como não verificado).
"""
from __future__ import annotations

import copy
import re
from urllib.parse import quote_plus

import compat
import job_archive
import open_jobs
from common import DATA, log
from dedup import Seen, _norm_url, unique
from filters import llm_judge, requirements
from filters.keywords import _has, normalize
from sources import brasil_jobs, jobs, network

DIR = DATA / "brasil"
OPEN, ARCHIVE, SKILLS = DIR / "open_jobs.json", DIR / "archive.json", DIR / "skills.json"
PEOPLE, COMPANIES, SEEN = DIR / "people.json", DIR / "companies.json", DIR / "seen.json"

# ---------------------------------------------------------------- tema (normalizado: minúsculo, sem acento)
TEMA = [
    # entity resolution e variações (pt/en)
    "entity resolution", "resolucao de entidades", "resolucao de entidade", "identity resolution",
    "resolucao de identidade", "resolucao de identidades", "record linkage", "linkage de dados",
    "linkage de registros", "data linkage", "probabilistic linkage", "relacionamento de bases",
    "pareamento de registros", "pareamento de bases", "pareamento probabilistico", "pareamento deterministico",
    "vinculacao de registros", "entity matching", "record matching", "data matching", "matching deterministico",
    "matching probabilistico", "correspondencia de registros", "fellegi-sunter", "fellegi sunter",
    # deduplicação e unificação de cadastros
    "deduplicacao", "deduplication", "dedup", "duplicate detection", "registros duplicados", "cadastros duplicados",
    "duplicidade de cadastros", "duplicidade de registros", "unificacao de cadastros", "unificacao de clientes",
    "consolidacao de cadastros", "higienizacao de cadastros", "higienizacao de dados", "cadastro unico do cliente",
    "visao unica do cliente", "unified customer id", "customer 360", "cliente 360", "single customer view",
    "identity graph", "grafo de identidade",
    # MDM e golden record
    "golden record", "registro de ouro", "survivorship", "regras de sobrevivencia", "master data management",
    "gestao de dados mestres", "match and merge", "match & merge",
    # ferramentas e técnicas
    "splink", "zingg", "senzing", "dedupe", "rapidfuzz", "fuzzy matching", "jaro-winkler", "levenshtein",
    "similaridade de strings", "string similarity", "blocking", "address matching", "geocodificacao",
    "normalizacao de enderecos", "padronizacao de enderecos",
]
# termos que sozinhos são fracos (MDM no Brasil muitas vezes é cadastro manual no ERP)
FRACOS = {"blocking", "dedup", "levenshtein", "geocodificacao", "master data management", "gestao de dados mestres",
          "higienizacao de dados", "customer 360", "cliente 360"}
TECH_TITLE = re.compile(r"(dados|data|analytics|cientista|engenheir|scientist|engineer|machine learning|\bml\b|"
                        r"\bia\b|\bai\b|mdm|arquitet|desenvolvedor|developer|governan|qualidade|estat[ií]stic|"
                        r"\bbi\b|intelig[eê]ncia)", re.I)
NEG_TITLE = re.compile(r"(vendas|sales|comercial|account executive|recrutador|recruiter|estagi[aá]rio|"
                       r"jovem aprendiz|auxiliar|assistente administrativo|motorista|atendente)", re.I)
BR_LOCAL = re.compile(r"(brasil|brazil|\bbr\b|s[aã]o paulo|rio de janeiro|belo horizonte|curitiba|porto alegre|"
                      r"recife|salvador|florian[oó]polis|campinas|bras[ií]lia|fortaleza|goi[aâ]nia|manaus|bel[eé]m|"
                      r"vit[oó]ria|natal|jo[aã]o pessoa|macei[oó]|aracaju|teresina|s[aã]o lu[ií]s|cuiab[aá]|"
                      r"campo grande|londrina|joinville|blumenau|ribeir[aã]o preto|sorocaba|santos|\b(sp|rj|mg|pr|"
                      r"rs|sc|ba|pe|ce|df|go)\b|latam|latin america|am[eé]rica latina)", re.I)
BR_SOURCES = ("Gupy", "InHire", "Google Jobs (Brasil)", "LinkedIn Jobs (Brasil)")


def hits(it: dict) -> tuple[list[str], list[str]]:
    """(termos no título, termos no texto) distintos."""
    t, x = normalize(it.get("titulo", "")), normalize(it.get("texto", "") or "")
    return [k for k in TEMA if _has(k, t)], [k for k in TEMA if _has(k, x)]


def no_brasil(it: dict) -> bool:
    if it.get("fonte", "").startswith(BR_SOURCES):
        return True
    loc = f"{it.get('local', '')} {it.get('fonte', '')}"
    if BR_LOCAL.search(loc):
        return True
    # descrição em português sem local informado: quase sempre vaga brasileira
    pt = len(re.findall(r"\b(voc[eê]|n[aã]o|para|com|dados|experi[eê]ncia|conhecimento)\b", (it.get("texto") or "").lower()))
    return not it.get("local") and pt > 12


def passes(it: dict) -> bool:
    """Alto RECALL: qualquer termo do tema no título, ou 1 termo forte / 2 termos quaisquer no texto."""
    if not no_brasil(it) or NEG_TITLE.search(it.get("titulo", "")):
        return False
    ht, hx = hits(it)
    strong_x = [k for k in hx if k not in FRACOS]
    it["score"] = 3 * len(ht) + len(set(hx))
    it["termos"] = sorted(set(ht + hx))[:8]
    return bool(ht) or bool(strong_x) or len(hx) >= 2


def central(it: dict) -> bool:
    """Regra para juízes reserva: tema no título ou 2+ termos fortes no texto."""
    ht, hx = hits(it)
    return bool([k for k in ht if k not in FRACOS]) or len([k for k in hx if k not in FRACOS]) >= 2


# termos tão específicos que UMA menção já indica o tema (para não perder vaga quando nenhuma IA responde)
ESPECIFICOS = {"entity resolution", "resolucao de entidades", "resolucao de entidade", "identity resolution",
               "resolucao de identidade", "resolucao de identidades", "record linkage", "linkage de dados",
               "linkage de registros", "data matching", "matching deterministico", "matching probabilistico",
               "pareamento probabilistico", "pareamento deterministico", "pareamento de registros", "golden record",
               "unificacao de cadastros", "unified customer id", "splink", "zingg", "senzing", "entity matching",
               "fellegi-sunter", "fellegi sunter", "identity graph"}


def strong(it: dict) -> bool:
    """Contingência sem IA: vaga técnica com o tema claramente presente."""
    if not TECH_TITLE.search(it.get("titulo", "")):
        return False
    ht, hx = hits(it)
    fortes = [k for k in hx if k not in FRACOS]
    return bool([k for k in ht if k not in FRACOS]) or len(fortes) >= 2 or any(k in ESPECIFICOS for k in fortes)


SYSTEM = """Você avalia itens para a aba BRASIL de um engenheiro de dados especialista em entity resolution e \
record linkage (matching determinístico/probabilístico, deduplicação, blocking, Splink, RapidFuzz, Spark).
Ele quer encontrar TODAS as oportunidades no Brasil do tema. Seja inclusivo com vagas que tenham o tema como \
responsabilidade, requisito OU diferencial, mesmo com título genérico ("Cientista de Dados", "Engenheiro de Dados").

Regras por tipo:
- vaga: aprove se a vaga for no Brasil (ou remota aceitando o Brasil) E envolver entity resolution ou variações: \
resolução de identidade/entidades, record linkage, data matching, matching determinístico/probabilístico, \
deduplicação de registros, unificação de cadastros, golden record, MDM com regras de match/merge, Customer 360 / \
visão única do cliente, identity graph, fuzzy matching de nomes/endereços. Reprove: vendas, suporte, vagas que só \
citam o termo de passagem na descrição da empresa, e "dados mestres" que é só cadastro manual de materiais/\
fornecedores no ERP (sem matching, deduplicação, regras ou qualidade de dados). Não reprove por senioridade.
- vaga vinda de POST em rede social: aprove só se anunciar uma vaga concreta e aberta com esse tema.
- pessoa (perfil do LinkedIn): aprove se a pessoa for do Brasil (ou trabalhar em empresa brasileira) e trabalhar, \
pesquisar ou liderar algo com esse tema. No "resumo_pt" diga em 1 frase quem é (cargo e empresa SOMENTE se \
estiverem escritos no texto).
- empresa: aprove se for brasileira (ou com operação forte no Brasil) e o tema for central no produto/serviço \
(ex.: dados cadastrais, enriquecimento, bureau, MDM, qualidade de dados) ou se contrata para o tema. \
No "resumo_pt" diga em 1 frase o que ela faz.

Para cada item, responda um objeto: {"id": <id>, "relevante": bool, "confianca": 0-1, \
"motivo": "1 frase em português", "resumo_pt": "até 2 frases em português, fiel ao texto"}.
Nunca use travessão (— ou –) nos textos: use vírgula, dois-pontos ou ponto.
Responda SOMENTE com um array JSON com um objeto por item, na mesma ordem."""

# empresas brasileiras de referência no tema (descrições curtas e factuais; o link abre a busca do LinkedIn)
REFERENCIAS = [
    ("Neoway", "Empresa brasileira de dados e analytics (B3) que cruza e unifica bases de pessoas e empresas."),
    ("BigDataCorp", "Empresa brasileira de dados públicos e enriquecimento cadastral de pessoas e empresas."),
    ("Serasa Experian", "Bureau de crédito com grandes bases cadastrais e soluções de identidade no Brasil."),
    ("Quod", "Bureau de crédito brasileiro (cadastro positivo) com bases de pessoas e empresas."),
    ("Boa Vista (Equifax)", "Bureau de crédito brasileiro com bases cadastrais e de crédito."),
    ("Assertiva Soluções", "Empresa brasileira de consulta e enriquecimento de dados cadastrais."),
    ("idwall", "Empresa brasileira de verificação de identidade e onboarding (KYC)."),
    ("unico", "Empresa brasileira de identidade digital e biometria."),
    ("Semantix", "Empresa brasileira de dados e IA, com projetos de engenharia e qualidade de dados."),
    ("Dataside", "Consultoria brasileira de dados e analytics."),
    ("BRQ", "Consultoria brasileira de tecnologia com projetos de resolução de identidade de clientes."),
]


# ---------------------------------------------------------------- coleta
def collect(cfg: dict) -> list[dict]:
    bcfg = cfg.get("brasil", {})
    c2 = copy.deepcopy(cfg)
    c2["companies"] = bcfg.get("companies", {})
    out = []
    for fn, c in ((brasil_jobs.inhire, cfg), (brasil_jobs.gupy, cfg), (brasil_jobs.google_jobs_br, cfg),
                  (brasil_jobs.linkedin_jobs_br, cfg), (jobs.greenhouse, c2), (jobs.lever, c2), (jobs.ashby, c2)):
        try:
            got = fn(c)
            log.info("brasil/%s: %d", fn.__name__, len(got))
            out += got
        except Exception as e:
            log.warning("brasil/%s falhou: %s", fn.__name__, str(e)[:200])
    return [r for r in out if r.get("titulo") and r.get("url")]


def _safe(label: str, fn, default=None):
    try:
        return fn()
    except Exception as e:
        import traceback

        log.warning("etapa brasil/%s falhou: %s | %s", label, e, traceback.format_exc(limit=3).replace("\n", " "))
        return default


def _seed_companies(day: str) -> None:
    if COMPANIES.exists():
        return
    seed = [{"nome": n, "titulo": n, "url": f"https://www.linkedin.com/search/results/companies/?keywords={quote_plus(n)}",
             "resumo": r, "fonte": "Referência no Brasil"} for n, r in REFERENCIAS]
    network._merge(COMPANIES, seed, day, len(seed))


def run(cfg: dict, day: str, raw_jobs: list[dict], use_llm: bool) -> dict:
    DIR.mkdir(parents=True, exist_ok=True)
    bcfg = cfg.get("brasil", {})
    extra = _safe("coleta", lambda: collect(cfg), []) or []
    pool = [dict(j) for j in raw_jobs] + extra
    _safe("descobrir empresas InHire", lambda: brasil_jobs.discover_tenants(pool, bcfg.get("inhire", [])))
    bootstrap = not OPEN.exists()
    seen = Seen(SEEN)
    cands = [it for it in unique(pool) if (bootstrap or seen.is_new(it)) and passes(it)]
    cands.sort(key=lambda it: (it["score"], it.get("publicada_em") or ""), reverse=True)
    cands = cands[: bcfg.get("max_julgar_por_dia", 60) * (2 if bootstrap else 1)]
    log.info("brasil: %d brutas, %d candidatas para o juiz", len(pool), len(cands))

    approved = []
    if use_llm:
        approved = _safe("juiz", lambda: llm_judge.judge(cands, cfg, system=SYSTEM, central=central, record=False),
                         []) or []
    rejected = set()
    for it in cands:
        if it.pop("_julgado", False):
            seen.add(it, day)
            if it not in approved:
                rejected.add(_norm_url(it["url"]))
        elif strong(it):
            it.update(nao_verificado=True, motivo="Aprovada pelas regras da aba Brasil (nenhuma IA respondeu); "
                                                  "será reavaliada quando um juiz voltar.")
            approved.append(it)
    for it in approved:
        it["trilha"] = "brasil"
        it.setdefault("termos", hits(it)[0] + hits(it)[1])

    if use_llm:
        _safe("requisitos", lambda: requirements.extract(approved, cfg))
    _safe("requisitos sem IA", lambda: requirements.ensure(approved))
    _safe("compatibilidade", lambda: compat.score_jobs(approved, cfg))

    if rejected:  # aprovada só pelas regras e depois reprovada por um juiz de verdade: sai da lista
        current = open_jobs.load(OPEN)
        keep = [j for j in current if not (j.get("nao_verificado") and _norm_url(j["url"]) in rejected)]
        if len(keep) < len(current):
            log.info("brasil: %d vaga(s) não verificadas removidas após o juiz", len(current) - len(keep))
            open_jobs.save(keep, OPEN)

    max_age = cfg.get("open_jobs", {}).get("max_age_days", 60)
    abertas = _safe("vagas abertas", lambda: open_jobs.update(approved, pool, day, max_age, path=OPEN), None)
    if abertas is None:
        abertas = open_jobs.load(OPEN)

    def rescore():
        requirements.ensure(abertas)
        skills = {s for j in abertas for s in ((j.get("requisitos") or {}).get("obrigatorios", []) +
                                               (j.get("requisitos") or {}).get("desejaveis", []))}
        cache = compat.classify_skills(skills, cfg)
        for j in abertas:
            compat.score(j, cfg, cache)
        abertas.sort(key=lambda j: j.get("encaixe", 0), reverse=True)
        open_jobs.save(abertas, OPEN)

    _safe("compatibilidade das abertas", rescore)
    archive = _safe("arquivo", lambda: job_archive.update(approved, abertas, day, path=ARCHIVE, skills_path=SKILLS),
                    []) or []

    _safe("empresas de referência", lambda: _seed_companies(day))
    net_cfg = copy.deepcopy(cfg)
    net_cfg["queries"]["linkedin_ddg"] = bcfg.get("rede_termos") or net_cfg["queries"].get("linkedin_ddg")
    net_cfg["queries"]["network"] = bcfg.get("empresas_termos") or net_cfg["queries"].get("network")
    judge_net = (lambda items: llm_judge.judge([it for it in unique(items) if seen.is_new(it)], cfg,
                                                system=SYSTEM, record=False)) if use_llm else (lambda items: [])
    rede = _safe("pessoas e empresas", lambda: network.update(net_cfg, day, [], approved, judge_net,
                                                              people_path=PEOPLE, companies_path=COMPANIES), {})
    if use_llm:
        seen.save()
    rep = {"novas": len(approved), "abertas": len(abertas), "arquivadas": len(archive), "rede": rede}
    log.info("brasil: %s", rep)
    return rep
