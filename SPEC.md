# Projeto: Linkage Radar — radar diário de Record Linkage & Geocodificação

> Cole este arquivo no Claude Code (ou salve como `SPEC.md` na raiz do repo e peça: "Implemente o SPEC.md passo a passo").
> **Instrução para o Claude Code:** Implemente, teste localmente e deixe pronto para subir no GitHub.

---

## 0. Contexto do usuário

- **Gabriel**, engenheiro de dados no CIDACS (~3 anos).
- Especialidade: **Record Linkage / Entity Matching / Entity Resolution** (qualquer tipo de entidade) e **Geocodificação de endereços tratada como problema de linkage** (address matching, normalização, fuzzy matching de endereços, blocking etc.).
- Quer um relatório diário, **alta precisão (poucos falsos positivos)**, lido no celular e no computador, e enviado no **WhatsApp às 6h (horário de Brasília)**.

---

## 1. Arquitetura (100% gratuita)

| Parte | Tecnologia |
|---|---|
| Coleta noturna | **Python 3.12** rodando em **GitHub Actions** (cron) |
| Filtro de precisão | Palavras-chave com score + **LLM como juiz** (Claude Haiku via API, ou Gemini free tier — configurável) |
| Armazenamento | Arquivos JSON versionados no próprio repo (`data/`) |
| Site | Página estática **responsiva** (HTML + CSS + JS puro, sem framework) no **GitHub Pages** |
| WhatsApp | **CallMeBot** (grátis) como padrão; **Twilio** como alternativa opcional |
| Configuração | `config.yaml` + **GitHub Secrets** para chaves e número de telefone |

Fluxo:
```
23h BRT (02:00 UTC)  → workflow "coletar"  → busca, filtra, gera data/YYYY-MM-DD.json → commit → Pages atualiza
06h BRT (09:00 UTC)  → workflow "enviar"   → lê o JSON do dia → envia resumo no WhatsApp com link do site
```
Obs.: o cron do GitHub é em UTC e pode atrasar alguns minutos — deixar isso documentado no README.

---

## 2. Estrutura de pastas

```
linkage-radar/
├── config.yaml
├── requirements.txt
├── src/
│   ├── main_collect.py        # orquestra a coleta noturna
│   ├── main_send.py           # envia WhatsApp
│   ├── sources/
│   │   ├── jobs.py
│   │   ├── events.py
│   │   └── papers.py
│   ├── filters/
│   │   ├── keywords.py        # score por termos (etapa 1)
│   │   └── llm_judge.py       # classificação final (etapa 2)
│   ├── lesson.py              # aula do dia
│   ├── dedup.py               # evita repetir itens já vistos (data/seen.json)
│   └── notify/
│       ├── callmebot.py
│       └── twilio.py
├── curriculum/
│   └── lessons.json           # cronograma de aulas (ver seção 6)
├── data/
│   ├── seen.json
│   └── 2026-09-28.json ...
├── site/
│   ├── index.html
│   ├── style.css
│   └── app.js
└── .github/workflows/
    ├── collect.yml
    └── send.yml
```

---

## 3. `config.yaml` (tudo editável sem mexer no código)

```yaml
timezone: America/Sao_Paulo
send_time: "06:00"            # documentar que mudar aqui exige ajustar o cron em send.yml (gerar isso automaticamente num script `scripts/update_cron.py`)
whatsapp:
  enabled: true
  provider: callmebot         # callmebot | twilio
  # número e apikey ficam em GitHub Secrets: WHATSAPP_PHONE, CALLMEBOT_APIKEY
llm:
  provider: anthropic         # anthropic | gemini
  model: claude-haiku-4-5
  min_confidence: 0.8         # só entra no relatório se o juiz der >= 0.8
limits:
  max_jobs: 10
  max_events: 5
  max_papers: 5
site_url: "https://<usuario>.github.io/linkage-radar/"
```

---

## 4. Módulos de coleta

### 4.1 Vagas (mundo todo)
Fontes gratuitas (implementar cada uma como função isolada; se uma falhar, as outras continuam):
- **Adzuna API** (free key) — vários países.
- **RemoteOK API** (`https://remoteok.com/api`).
- **Remotive API**.
- **Greenhouse / Lever / Ashby** job board APIs públicas de uma lista de empresas conhecidas por ER/linkage (lista editável em `config.yaml`: ex. Senzing, Tamr, Quantexa, Zingg, Esri, HERE, Mapbox, Precisely, Melissa, Loqate, Experian, LexisNexis, Palantir…).
- **Hacker News "Who is hiring"** do mês (API Algolia do HN).
- Opcional: **SerpAPI** (Google Jobs, 100 buscas/mês grátis) se houver chave.

Consultas base: `"entity resolution"`, `"record linkage"`, `"entity matching"`, `"data matching"`, `"master data management" matching`, `"geocoding" engineer`, `"address matching"`, `"deduplication" data engineer`.

### 4.2 Eventos e comunidades (somente Brasil — remoto ou presencial)
- **Sympla** e **Even3** (busca por termos), **Meetup** (Brasil), **Doity**.
- Calendários de: SBBD, BRACIS, GEOINFO (INPE), Semana de Dados Abertos, eventos da Fiocruz/CIDACS, PyData Brasil, Python Brasil.
- Aceitar também eventos internacionais online **com organização/participação brasileira clara** apenas se o LLM confirmar.
- Guardar: nome, data, local/online, link, por que é relevante.

### 4.3 Publicações do dia
- **arXiv API** (categorias cs.DB, cs.IR, cs.LG, stat.ME) — publicados nas últimas 24h.
- **OpenAlex API** e **Semantic Scholar API** (filtro por data de publicação = ontem/hoje).
- **Crossref** como fallback.
- Para cada paper aprovado: título, autores (curto), link e **resumo de no máximo 2 frases em português** gerado pelo LLM.

---

## 5. Filtro de precisão (o mais importante)

**Etapa 1 — score por palavras-chave (`keywords.py`)**, barato, elimina o grosso:
- Termos fortes (+3): record linkage, entity resolution, entity matching, probabilistic linkage, Fellegi-Sunter, data linkage, deduplication of records, address matching, geocoding matching, blocking, identity resolution.
- Termos médios (+1): fuzzy matching, string similarity, master data, MDM, geocoding, splink, dedupe, zingg.
- Termos negativos (−3): "data entry", "sales", genérico "data engineer" sem nenhum termo forte, "GIS technician" sem matching.
- Só vai para a etapa 2 quem tiver score ≥ 3.

**Etapa 2 — LLM juiz (`llm_judge.py`)**, prompt fixo retornando JSON:
```
Você avalia se um item é relevante para um especialista em Record Linkage / Entity Matching
e Geocodificação tratada como problema de linkage.
Para VAGAS: aprove SOMENTE se o foco principal da função for entity matching/record linkage/
entity resolution ou geocodificação/address matching. Vagas genéricas de dados = reprovar.
Para EVENTOS: aprove somente se o tema central for isso e for no Brasil (ou online com foco BR).
Para PAPERS: aprove se o problema central for linkage/ER/matching/geocodificação.
Responda JSON: {"relevante": bool, "confianca": 0-1, "motivo": "1 frase", "resumo_pt": "até 2 frases"}
```
Entra no relatório só se `relevante == true` e `confianca >= min_confidence`.

**Dedup:** hash de URL + título normalizado em `data/seen.json` para nunca repetir item.

**Seção vazia é ok:** se não houver nada, mostrar "Nada novo hoje ✅" (preferir silêncio a ruído).

---

## 6. Aula do dia (`curriculum/lessons.json` + `lesson.py`)

- Claude Code deve **gerar uma vez** um cronograma de **365 aulas** (arquivo estático, sem custo diário), dividido em módulos progressivos:
  1. Fundamentos (definições, tipos de linkage, determinístico vs probabilístico)
  2. Pré-processamento e padronização (nomes, datas, endereços, fonética: Soundex, Metaphone, BuscaBR)
  3. Comparação de strings (Jaro-Winkler, Levenshtein, Jaccard, q-grams, TF-IDF)
  4. Blocking e indexação (standard, sorted neighborhood, LSH, canopy)
  5. Modelo Fellegi-Sunter e EM
  6. Avaliação (precisão, recall, F1, clerical review, viés de linkage)
  7. ML/Deep Learning para ER (Magellan, Ditto, embeddings, LLMs para matching)
  8. Geocodificação como linkage (parsing de endereço, gazetteers, libpostal, CNEFE, matching hierárquico)
  9. Escalabilidade (Spark, Splink, Zingg, grafos, clustering transitivo)
  10. Privacidade (PPRL, Bloom filters, LGPD)
  11. Casos reais em saúde pública (coortes, CIDACS, linkage de bases do SUS)
  12. Revisão e tópicos avançados
- Formato de cada aula: `{"dia": n, "modulo": "...", "titulo": "...", "explicacao": "máx. 120 palavras, tom de professor", "exemplo": "curto", "pergunta_reflexao": "1 pergunta"}`
- O dia da aula = dias desde a data de início definida em `config.yaml` (`curriculum_start: 2026-09-28`), em loop.

---

## 7. Site (GitHub Pages) — simples, intuitivo, responsivo

- **Mobile-first**, uma coluna no celular, duas no desktop; fonte legível; modo escuro automático.
- Topo: data + seletor de dias anteriores (lê `data/index.json` com a lista de datas).
- 4 cartões com contador:
  1. 💼 **Vagas** — título, empresa, local/remoto, motivo do match, botão "Ver vaga".
  2. 📅 **Eventos no Brasil** — nome, data, online/presencial, link.
  3. 📄 **Publicações** — título, resumo curto, link.
  4. 🎓 **Aula do dia** — título, explicação, exemplo, pergunta (com "ver aulas anteriores").
- Sem login, sem backend. Carrega o JSON do dia via `fetch`.

---

## 8. WhatsApp

- **CallMeBot** (padrão): o usuário envia uma mensagem de ativação para o bot e recebe uma apikey; guardar `WHATSAPP_PHONE` e `CALLMEBOT_APIKEY` em GitHub Secrets. README deve explicar o passo a passo de ativação.
- Mensagem enviada (curta, texto puro, cabe no WhatsApp):
```
📡 Linkage Radar — 28/09
💼 Vagas: 2 | 📅 Eventos: 1 | 📄 Papers: 3
• [Vaga] Entity Resolution Engineer – Empresa X (Remoto) <link>
• [Evento] ... <link>
• [Paper] título – resumo 1 frase <link>
🎓 Aula 12: Blocking por Sorted Neighborhood — <1 frase>
Ver tudo: <site_url>
```
- Se a mensagem passar de ~1500 caracteres, listar só os top 3 de cada seção e apontar para o site.
- Twilio como provider alternativo (mesma interface `send(text)`).

---

## 9. GitHub Actions

- `collect.yml`: `cron: "0 2 * * *"` (23h BRT) + `workflow_dispatch`. Instala deps, roda `main_collect.py`, faz commit de `data/`.
- `send.yml`: `cron: "0 9 * * *"` (06h BRT) + `workflow_dispatch`. Roda `main_send.py`.
- `pages.yml` (ou Pages via branch) publicando `site/` + `data/`.
- Secrets: `ANTHROPIC_API_KEY` (ou `GEMINI_API_KEY`), `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `WHATSAPP_PHONE`, `CALLMEBOT_APIKEY`, opcional `SERPAPI_KEY`.

---

## 10. Ordem de implementação (passo a passo para o Claude Code)

1. Criar estrutura de pastas, `requirements.txt`, `config.yaml` e loader de config.
2. Implementar `papers.py` (arXiv + OpenAlex) — fonte mais fácil, para validar o pipeline.
3. Implementar `keywords.py` + `llm_judge.py` com testes usando 10 exemplos fixos (5 relevantes, 5 falsos positivos típicos).
4. Implementar `jobs.py` e `events.py`, cada fonte com try/except e timeout.
5. Implementar `dedup.py` e `main_collect.py` gerando `data/YYYY-MM-DD.json` e `data/index.json`.
6. Gerar `curriculum/lessons.json` (365 aulas) e `lesson.py`.
7. Construir o site em `site/` e testar localmente com `python -m http.server`.
8. Implementar notificação WhatsApp e `main_send.py` com flag `--dry-run` (imprime no terminal).
9. Criar os workflows do GitHub Actions.
10. Escrever `README.md` em português: como criar as chaves, configurar Secrets, ativar CallMeBot, ativar GitHub Pages, mudar horário, rodar manualmente.
11. Rodar tudo local com `--dry-run` e mostrar um relatório de exemplo.

## Critérios de pronto
- `python src/main_collect.py` roda local e gera o JSON do dia.
- `python src/main_send.py --dry-run` mostra a mensagem do WhatsApp.
- Site abre bem em tela de 375px e em desktop.