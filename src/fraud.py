"""Trilha de FRAUDE: a aba "Fraude" do site (área para onde você está migrando).

Mesmo radar do nicho principal, mas focado em vagas TÉCNICAS de dados em prevenção a fraude, AML/PLD,
KYC/KYB, sanções, monitoramento de transações e risco de identidade, com prioridade para as que usam
entity resolution, grafos e identidade (o seu diferencial).

Tudo fica em data/fraude/:
    open_jobs.json   vagas abertas (revalidadas todo dia)      archive.json   todas as vagas que já apareceram
    skills.json      o que o mercado de fraude pede x você     people.json / companies.json   quem seguir
    plano.json       próximos passos (calculados toda coleta; análise de IA 1x por semana quando houver IA)
    seen.json        o que já foi julgado (separado do nicho principal)

Funciona sem IA: se nenhum juiz responder, regras rígidas aprovam só o que é claramente "dados + fraude"
(marcado como não verificado) e a compatibilidade sai estimada.
"""
from __future__ import annotations

import copy
import json
import re
from datetime import date, timedelta
from urllib.parse import quote_plus

import compat
import job_archive
import open_jobs
from common import DATA, ROOT, log, no_dash
from dedup import Seen, _norm_url, unique
from filters import llm_judge, requirements
from filters.keywords import _has, normalize
from sources import jobs, network

DIR = DATA / "fraude"
OPEN, ARCHIVE, SKILLS = DIR / "open_jobs.json", DIR / "archive.json", DIR / "skills.json"
PEOPLE, COMPANIES, PLAN, SEEN = DIR / "people.json", DIR / "companies.json", DIR / "plano.json", DIR / "seen.json"

# ---------------------------------------------------------------- regras (sem IA)
DOMAIN = [
    "fraud", "fraude", "fraudes", "fraudulent", "antifraude", "anti-fraude", "anti-fraud", "antifraud",
    "aml", "anti-money laundering", "anti money laundering", "money laundering", "lavagem de dinheiro", "pld",
    "pld/ft", "kyc", "kyb", "know your customer", "financial crime", "financial crimes", "fincrime",
    "anti-financial crime", "sanctions screening", "sanctions", "transaction monitoring",
    "monitoramento transacional", "monitoramento de transacoes", "trust and safety", "trust & safety",
    "identity verification", "scam", "scams", "chargeback", "chargebacks", "prevencao a fraude",
    "prevencao a fraudes", "prevencao a lavagem", "fraud detection", "fraud prevention", "money mule",
    "account takeover", "risk intelligence", "financial intelligence", "compliance analytics",
]
TECH = [
    "data engineer", "data engineering", "engenheiro de dados", "engenheira de dados", "engenheiro(a) de dados",
    "data scientist", "data science", "cientista de dados", "machine learning", "ml engineer", "mlops",
    "analytics engineer", "data analyst", "analista de dados", "data platform", "applied scientist",
    "research scientist", "data architect", "arquiteto de dados", "big data", "ai engineer", "ml scientist",
    "decision scientist", "data infrastructure", "engenheiro de machine learning", "modelagem", "data modeler",
    "analytics", "quantitative", "inteligencia artificial", "ciencia de dados", "engenharia de dados",
]
ER = [
    "entity resolution", "identity resolution", "record linkage", "entity matching", "graph", "graphs",
    "graph analytics", "network analytics", "network analysis", "link analysis", "knowledge graph", "neo4j",
    "quantexa", "senzing", "deduplication", "matching", "identity graph", "name matching", "name screening",
    "fuzzy matching", "grafos", "resolucao de entidades",
]
NEG_TITLE = [
    "account executive", "sales", "vendas", "sdr", "business development", "counsel", "legal", "juridico",
    "recruiter", "recrutador", "customer success", "marketing", "designer", "accountant", "contador",
    "product manager", "gerente de produto", "solutions consultant", "partnerships", "estagio", "intern",
]
# empresas cujo produto central é antifraude/identidade: vaga técnica de dados nelas já é da área
FRAUD_COMPANIES = {"feedzai", "alloy", "complyadvantage", "riskified", "forter", "sardine", "socure", "sift",
                   "seon", "quantexa", "persona", "elliptic", "senzing", "clearsale", "idwall", "unico",
                   "featurespace", "unit21", "hawk ai", "chainalysis", "trm labs", "signifyd", "onfido",
                   "ravelin", "gbg", "datavisor", "jumio", "sumsub", "veriff", "kount", "biocatch", "neuro-id"}
# ferramentas de ER/grafos que, no título, já dizem que a vaga é do mundo de fraude/AML
ER_FRAUD_TOOLS = ["quantexa", "senzing"]
# sinais de que a vaga usa o SEU diferencial (aparece como selo no site)
ER_SIGNALS = ["entity resolution", "identity resolution", "record linkage", "entity matching", "identity graph",
              "graph analytics", "network analytics", "network analysis", "link analysis", "knowledge graph",
              "graph database", "graph databases", "neo4j", "quantexa", "senzing", "deduplication", "name matching",
              "name screening", "fuzzy matching", "resolucao de entidades", "grafos", "graph neural"]


def _hits(terms: list[str], text: str) -> int:
    return sum(1 for t in terms if _has(t, text))


def _facts(it: dict) -> dict:
    t, x = normalize(it.get("titulo", "")), normalize(it.get("texto", ""))
    company = normalize(it.get("empresa", ""))
    return {
        "dom_title": _hits(DOMAIN, t) > 0,
        "dom_text": sum(len(re.findall(rf"(?<![a-z0-9]){re.escape(d)}(?![a-z0-9])", x)) for d in DOMAIN),
        "fraud_co": any(c in company for c in FRAUD_COMPANIES),
        "tech_title": _hits(TECH, t) > 0 or _hits(ER, t) > 0,
        "neg_title": _hits(NEG_TITLE, t) > 0,
        "er": _hits(ER, t + " " + x),
        "er_tool_title": _hits(ER_FRAUD_TOOLS, t) > 0,
    }


def er_signals(it: dict) -> list[str]:
    text = normalize(f"{it.get('titulo', '')} {it.get('texto', '')}")
    return [s for s in ER_SIGNALS if _has(s, text)]


def score(it: dict) -> int:
    f = _facts(it)
    return 3 * f["dom_title"] + 2 * f["fraud_co"] + min(f["dom_text"], 5) + 2 * min(f["er"], 3)


def passes(it: dict) -> bool:
    """Função técnica de dados + tema de fraude no título, na empresa ou repetido no texto."""
    f = _facts(it)
    it["score"] = score(it)
    return f["tech_title"] and not f["neg_title"] and (f["dom_title"] or f["fraud_co"] or f["er_tool_title"]
                                                       or f["dom_text"] >= 2)


def central(it: dict) -> bool:
    """Regra rígida para juízes reserva: fraude no título, empresa de antifraude ou tema muito repetido."""
    f = _facts(it)
    return f["dom_title"] or f["fraud_co"] or f["er_tool_title"] or f["dom_text"] >= 3


def strong(it: dict) -> bool:
    """Contingência sem IA: só o que é inequivocamente 'vaga de dados em fraude'."""
    f = _facts(it)
    return f["tech_title"] and not f["neg_title"] and (f["dom_title"] or f["fraud_co"] or f["er_tool_title"])


SYSTEM = """Você avalia itens para a trilha de FRAUDE de um engenheiro de dados especialista em entity resolution \
e record linkage que está migrando para prevenção a fraude, PLD/AML, KYC/KYB e crimes financeiros.
O leitor quer ALTA PRECISÃO: na dúvida, reprove.

Regras por tipo:
- vaga: aprove se a função for TÉCNICA de dados (engenharia de dados, ciência de dados, machine learning, \
analytics engineering, plataforma de dados, entity resolution, grafos) E o trabalho for em fraude, prevenção à \
lavagem de dinheiro, KYC/KYB, sanções, monitoramento de transações, risco de identidade ou trust & safety. \
Também aprove função técnica de dados em empresa cujo produto central é antifraude/identidade/AML (ex.: Feedzai, \
Sardine, Quantexa, Socure, Sift, ComplyAdvantage). Reprove vendas, jurídico, produto, design, suporte, operação \
manual de análise de casos sem engenharia/ciência de dados, risco de crédito/mercado sem relação com fraude e vagas \
que citam fraude só de passagem. NÃO reprove por local, senioridade ou idioma (a compatibilidade é calculada depois).
- vaga vinda de POST em rede social: aprove só se anunciar uma vaga concreta e aberta com esse foco.
- pessoa (perfil do LinkedIn): aprove se a pessoa claramente trabalha, pesquisa ou lidera dados/ML/engenharia em \
fraude, AML/PLD, KYC, crimes financeiros, identidade ou entity resolution aplicada a risco. No "resumo_pt" diga em \
1 frase quem é (cargo e empresa SOMENTE se estiverem escritos no texto). Recrutador genérico = reprovar.
- empresa: aprove se o produto/serviço central for antifraude, AML/PLD, KYC/KYB, verificação de identidade, \
inteligência de risco, ou se for banco/fintech com time de prevenção a fraude reconhecido. No "resumo_pt" diga em \
1 frase o que ela faz.

Para cada item, responda um objeto: {"id": <id>, "relevante": bool, "confianca": 0-1, \
"motivo": "1 frase em português", "resumo_pt": "até 2 frases em português, fiel ao texto"}.
Nunca use travessão (— ou –) nos textos: use vírgula, dois-pontos ou ponto.
Responda SOMENTE com um array JSON com um objeto por item, na mesma ordem."""

# Empresas de referência para seguir desde o 1º dia (descrições curtas e factuais; o link abre a busca do LinkedIn)
REFERENCIAS = [
    ("Quantexa", "Plataforma de decision intelligence com entity resolution e análise de redes para AML, KYC e fraude."),
    ("Senzing", "Motor de entity resolution embutível, muito usado em AML, KYC e investigação."),
    ("Feedzai", "Plataforma de prevenção a fraude e lavagem de dinheiro com machine learning, fundada em Portugal."),
    ("Sardine", "Prevenção a fraude e compliance com sinais de dispositivo e comportamento."),
    ("Sift", "Plataforma de trust and safety e prevenção a fraude digital."),
    ("Alloy", "Orquestração de verificação de identidade (KYC/KYB) e risco para bancos e fintechs."),
    ("Socure", "Verificação de identidade e prevenção a fraude com machine learning."),
    ("ComplyAdvantage", "Dados de risco (sanções, PEP, mídia adversa) e monitoramento de transações para AML."),
    ("SEON", "Prevenção a fraude com enriquecimento de dados e pegada digital."),
    ("Elliptic", "Análise de blockchain para prevenção à lavagem de dinheiro com criptoativos."),
    ("Nubank", "Maior banco digital do Brasil, com times de dados em prevenção a fraude e PLD."),
    ("ClearSale", "Empresa brasileira de antifraude para e-commerce e meios de pagamento."),
    ("idwall", "Empresa brasileira de verificação de identidade e onboarding (KYC)."),
    ("unico", "Empresa brasileira de identidade digital e biometria contra fraude."),
    ("Serasa Experian", "Bureau de crédito com soluções de identidade e antifraude no Brasil."),
]

# Plano de carreira base (análise de out/2026; fica sempre visível, mesmo sem IA)
FASES = [
    {"fase": "Fase 1: preparar a migração", "quando": "0 a 6 meses, sem sair do emprego",
     "itens": [
         "Inglês para entrevista técnica: é o que mais destrava vagas melhores (meta: conversar 30 min sobre seu trabalho).",
         "Grafos e análise de redes: Neo4j ou GraphFrames, componentes conexos e centralidade sobre a saída do seu matching.",
         "Domínio de fraude e PLD: tipologias (contas laranja, golpe via Pix, account takeover), KYC/KYB, listas de sanções e PEP, regras de PLD no Brasil.",
         "Nuvem: uma certificação (AWS Data Engineer ou Databricks Data Engineer Associate).",
         "Projeto de portfólio: detectar redes de contas laranja com entity resolution + grafo em dados sintéticos (ex.: PaySim ou IBM AML synthetic data).",
     ]},
    {"fase": "Fase 2: entrar na área", "quando": "6 a 18 meses",
     "itens": [
         "Candidatar-se a vagas de dados em times de fraude, PLD ou identidade de bancos e fintechs (de preferência remotas).",
         "Contar a sua história como 'resolução de identidade em bilhões de registros sem chave única': é o mesmo problema de KYC e de redes de fraude.",
         "Preparar 2 cases de entrevista: seu pipeline de linkage em produção e o projeto de grafo de contas laranja.",
     ]},
    {"fase": "Fase 3: virar referência", "quando": "18 a 36 meses",
     "itens": [
         "Sênior/staff em identidade e fraude, publicando (artigo do mestrado, palestras, posts técnicos).",
         "Com inglês fluente: vagas remotas em dólar em empresas como Quantexa, Sardine, Feedzai e Socure.",
     ]},
]
CURRICULO_DICAS = [
    "Traduza seu trabalho para a linguagem de fraude: 'resolução de identidade em bilhões de registros' = base de KYC, detecção de contas duplicadas e redes de fraude.",
    "Coloque números: volume de registros, precisão/recall do matching, tempo de processamento, redução de duplicatas.",
    "Inclua 'Identity Resolution', 'Entity Resolution', 'Graph Analytics' e os termos do domínio (AML, KYC, Fraud Detection) quando tiver estudado.",
    "Destaque o projeto de portfólio de fraude (com link no GitHub) logo abaixo da experiência atual.",
]


# ---------------------------------------------------------------- coleta
def collect(cfg: dict) -> list[dict]:
    """Fontes extras com busca por termos de fraude e páginas de vagas de empresas de antifraude/identidade.
    (As listagens completas do radar principal, como RemoteOK, Jobicy e WWR, já chegam em raw_jobs.)"""
    fcfg = cfg.get("fraude", {})
    c2 = copy.deepcopy(cfg)
    c2["queries"]["jobs"] = fcfg.get("queries", [])
    c2["companies"] = fcfg.get("companies", {})
    c2["gupy_titles"] = fcfg.get("gupy_titles", [])
    c2["adzuna_countries"] = ["br", "us", "gb"]
    c2.setdefault("serpapi", {}).update(jobs_searches_per_day=fcfg.get("google_jobs_por_dia", 1), jobs_pages_per_term=1)
    small = copy.deepcopy(c2)
    small["queries"]["jobs"] = c2["queries"]["jobs"][:4]  # Adzuna/HN: poucas consultas (limite das APIs)
    out = []
    for fn, c in ((jobs.greenhouse, c2), (jobs.lever, c2), (jobs.ashby, c2), (jobs.remotive, c2),
                  (jobs.himalayas, c2), (jobs.workable, c2), (jobs.gupy, c2), (jobs.hn_who_is_hiring, small),
                  (jobs.adzuna, small), (jobs.serpapi_google_jobs, c2)):
        try:
            got = fn(c)
            log.info("fraude/%s: %d", fn.__name__, len(got))
            out += got
        except Exception as e:
            log.warning("fraude/%s falhou: %s", fn.__name__, str(e)[:200])
    return [r for r in out if r.get("titulo") and r.get("url")]


def _load(path, default):
    try:
        return json.loads(path.read_text("utf-8")) if path.exists() else default
    except Exception as e:
        log.warning("fraude: %s ilegível (%s)", path.name, e)
        return default


def _safe(label: str, fn, default=None):
    try:
        return fn()
    except Exception as e:
        import traceback

        log.warning("etapa fraude/%s falhou: %s | %s", label, e, traceback.format_exc(limit=3).replace("\n", " "))
        return default


def _seed_companies(day: str) -> None:
    if COMPANIES.exists():
        return
    seed = [{"nome": n, "titulo": n, "url": f"https://www.linkedin.com/search/results/companies/?keywords={quote_plus(n)}",
             "resumo": r, "fonte": "Referência no setor"} for n, r in REFERENCIAS]
    network._merge(COMPANIES, seed, day, len(seed))


def run(cfg: dict, day: str, raw_jobs: list[dict], use_llm: bool) -> dict:
    DIR.mkdir(parents=True, exist_ok=True)
    fcfg = cfg.get("fraude", {})
    extra = _safe("coleta", lambda: collect(cfg), []) or []
    pool = [dict(j) for j in raw_jobs] + extra
    bootstrap = not OPEN.exists()
    seen = Seen(SEEN)
    cands = [it for it in unique(pool) if (bootstrap or seen.is_new(it)) and passes(it)]
    cands.sort(key=lambda it: (it.get("publicada_em") or "", it["score"]), reverse=True)
    cands = cands[: fcfg.get("max_julgar_por_dia", 40) * (2 if bootstrap else 1)]  # 1ª vez: monta a carteira
    log.info("fraude: %d brutas, %d candidatas para o juiz", len(pool), len(cands))

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
            it.update(nao_verificado=True, motivo="Aprovada pelas regras da trilha de fraude (nenhuma IA respondeu); "
                                                  "será reavaliada quando um juiz voltar.")
            approved.append(it)
    for it in approved:
        it["trilha"] = "fraude"
        it["usa_er"] = er_signals(it)  # selo "usa entity resolution/grafos" (antes de descartar o texto)

    if use_llm:
        _safe("requisitos", lambda: requirements.extract(approved, cfg))
    _safe("requisitos sem IA", lambda: requirements.ensure(approved))
    _safe("compatibilidade", lambda: compat.score_jobs(approved, cfg))

    # vaga aprovada só pelas regras e depois reprovada por um juiz de verdade sai da lista
    if rejected:
        current = open_jobs.load(OPEN)
        keep = [j for j in current if not (j.get("nao_verificado") and _norm_url(j["url"]) in rejected)]
        if len(keep) < len(current):
            log.info("fraude: %d vaga(s) não verificadas removidas após o juiz", len(current) - len(keep))
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
    net_cfg["queries"]["linkedin_ddg"] = fcfg.get("rede_termos") or net_cfg["queries"].get("linkedin_ddg")
    net_cfg["queries"]["network"] = fcfg.get("empresas_termos") or net_cfg["queries"].get("network")
    net_cfg["_prioridade"] = "baixa"  # não disputa a cota da SerpAPI com o radar principal
    judge_net = (lambda items: llm_judge.judge([it for it in unique(items) if seen.is_new(it)], cfg,
                                                system=SYSTEM, record=False)) if use_llm else (lambda items: [])
    rede = _safe("pessoas e empresas", lambda: network.update(net_cfg, day, [], approved, judge_net,
                                                              people_path=PEOPLE, companies_path=COMPANIES), {})
    plan = _safe("próximos passos", lambda: build_plan(cfg, day, abertas, use_llm), {})
    if use_llm:
        seen.save()
    rep = {"novas": len(approved), "abertas": len(abertas), "arquivadas": len(archive),
           "rede": rede, "acoes": len((plan or {}).get("esta_semana", []))}
    log.info("fraude: %s", rep)
    return rep


# ---------------------------------------------------------------- próximos passos
def build_plan(cfg: dict, day: str, abertas: list[dict], use_llm: bool = True) -> dict:
    min_c = cfg.get("fraude", {}).get("min_compat", cfg.get("whatsapp", {}).get("min_compat", 0.25))
    stats = _load(SKILLS, {})
    g = stats.get("ganhos") or {}
    ref = date.fromisoformat(day)
    fresh = [j for j in abertas if j.get("publicada_em") and (ref - date.fromisoformat(j["publicada_em"])).days <= 2]
    good = [j for j in abertas if j.get("encaixe", 0) >= min_c]
    people = _load(PEOPLE, [])
    companies = _load(COMPANIES, [])
    acoes = []
    for j in sorted([j for j in fresh if j.get("encaixe", 0) >= min_c], key=lambda j: -j.get("encaixe", 0))[:3]:
        acoes.append({"tipo": "candidatar", "texto": f"Candidatar-se cedo: {j['titulo']} ({j.get('empresa') or j.get('fonte')}), "
                                                    f"{round(j.get('encaixe', 0) * 100)}% compatível.", "url": j["url"]})
    for j in [j for j in good if j not in fresh][:3]:
        acoes.append({"tipo": "candidatar", "texto": f"Vaga acessível: {j['titulo']} ({j.get('empresa') or j.get('fonte')}), "
                                                    f"{round(j.get('encaixe', 0) * 100)}% compatível.", "url": j["url"]})
    # maior ganho primeiro; habilidade já coberta por uma família escolhida (ex.: Tableau dentro de BI) não repete
    opcoes = sorted((g.get("familias") or []) + (g.get("habilidades") or []),
                    key=lambda s: (s.get("ganho_cobertura", 0), s.get("vagas_completas_a_mais", 0)), reverse=True)
    estudar = []
    for s in opcoes:
        if len(estudar) >= 4:
            break
        if not any(s["nome"].lower() in e["nome"].lower() or e["nome"].lower() in s["nome"].lower() for e in estudar):
            estudar.append(s)
    for s in estudar:
        acoes.append({"tipo": "estudar", "texto": f"Estudar {s['nome']}: pedido em {s.get('pct_nicho', 0)}% das vagas de "
                                                 f"fraude; +{s.get('ganho_cobertura', 0)} pontos de cobertura"
                                                 + (f" e +{s['vagas_completas_a_mais']} vaga(s) com todos os obrigatórios"
                                                    if s.get("vagas_completas_a_mais") else "") + "."})
    new_p = [p for p in people if p.get("desde") == day]
    new_c = [c for c in companies if c.get("desde") == day]
    if new_p or new_c:
        acoes.append({"tipo": "seguir", "texto": f"Seguir no LinkedIn: {len(new_p)} pessoa(s) e {len(new_c)} empresa(s) novas "
                                                f"da área de fraude (aba Fraude)."})
    plan = _load(PLAN, {})
    plan.update({
        "atualizado_em": day,
        "resumo": {"vagas_abertas": len(abertas), "frescas": len(fresh), "acessiveis": len(good),
                   "compat_media": round(100 * sum(j.get("encaixe", 0) for j in abertas) / len(abertas)) if abertas else None,
                   "cobertura": g.get("cobertura_atual"), "vagas_analisadas": g.get("vagas_analisadas", 0),
                   "vagas_completas": g.get("vagas_completas_hoje")},
        "esta_semana": acoes,
        "fases": FASES,
        "curriculo": CURRICULO_DICAS,
    })
    if use_llm:
        _safe("análise semanal da IA", lambda: _weekly_analysis(cfg, day, plan, stats))
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=1), "utf-8")
    return plan


ANALYSIS_SYSTEM = """Você é um mentor de carreira em dados para prevenção a fraude e PLD/AML. O candidato é engenheiro \
de dados especialista em entity resolution (bilhões de registros de saúde pública no Brasil) e quer migrar para fraude. \
Com base no currículo e no que as vagas de fraude pedem, responda SOMENTE JSON: \
{"diagnostico": "3 a 4 frases honestas sobre onde ele está", "proximos_passos": ["5 ações concretas para as \
próximas 4 semanas, em ordem"], "curriculo": ["3 ajustes específicos no currículo para vagas de fraude"]}. \
Português do Brasil, sem travessão (— ou –), sem markdown, sem inventar experiências."""


def _weekly_analysis(cfg: dict, day: str, plan: dict, stats: dict) -> None:
    last = (plan.get("analise_ia") or {}).get("data", "")
    if last and last > (date.fromisoformat(day) - timedelta(days=7)).isoformat():
        return
    ranking = (stats.get("geral") or {}).get("ranking", [])[:30]
    if len(ranking) < 5:
        return  # ainda há poucas vagas de fraude para uma análise que valha a pena
    from filters import providers

    cv = ROOT / "profile" / "curriculo.md"
    user = json.dumps({"curriculo": cv.read_text("utf-8") if cv.exists() else cfg.get("perfil", ""),
                       "o_que_as_vagas_de_fraude_pedem": [{"habilidade": r["nome"], "pct_vagas": r["pct"],
                                                           "voce": r["voce"]} for r in ranking],
                       "resumo": plan.get("resumo")}, ensure_ascii=False)
    text = providers.complete(cfg, ANALYSIS_SYSTEM, user, max_tokens=2500)
    if not text:
        return
    data = json.loads(text[text.index("{"): text.rindex("}") + 1])
    clean = lambda v: [no_dash(str(x)) for x in v][:6] if isinstance(v, list) else []
    if isinstance(data, dict) and data.get("diagnostico"):
        plan["analise_ia"] = {"data": day, "juiz": providers.LAST_USED["nome"],
                              "diagnostico": no_dash(str(data["diagnostico"])),
                              "proximos_passos": clean(data.get("proximos_passos")),
                              "curriculo": clean(data.get("curriculo"))}
