# 📡 Linkage Radar

Radar diário para se tornar especialista em **Entity Resolution / Record Linkage**: vagas no mundo todo com
**compatibilidade realista**, posts com vagas nas redes, eventos no Brasil, papers, pessoas e empresas para seguir,
um **programa de 52 semanas** baseado em Christen (2012) e coaching de carreira. Duas mensagens no WhatsApp às **07h**
(vagas e aula) e tudo no site.

```
~02h (BRT) coletar → 14 fontes de vagas + posts + papers → palavras-chave → Haiku (juiz) → Sonnet (fatos da vaga)
                   → compatibilidade (Python) → pessoas/empresas → pílula de mercado → análise semanal do perfil
07h00      enviar  → já está rodando desde a coleta e dispara exatamente às 07h: 1) vagas  2) aula do dia
```

> O agendamento grátis do GitHub atrasa ~6h neste repositório. Por isso o envio começa logo após a coleta e
> **espera rodando** até `send_time` (scripts/wait_until_send.py). Nunca envia duas vezes no mesmo dia.

---

## 🎓 Programa de 52 semanas (curriculum/plan.py)
- Base: **Christen, P. (2012). Data Matching** (cap. 1 a 10, com páginas), completado com a literatura posterior
  (Fellegi-Sunter, Winkler, Splink, fastLink, Ditto, LLMs, PPRL, ER bayesiano...). Só referências verificadas.
- Semana = 5 aulas de conceito + 1 laboratório com código + 1 revisão ativa com repetição espaçada.
- Cada aula: objetivo, conceito, fórmula/algoritmo, exemplo resolvido com números, prática (Splink 4, PySpark,
  recordlinkage), armadilha, **desafio** e **gabarito no dia seguinte**.
- Geradas uma vez com Claude Sonnet 5 via Batch API (`scripts/build_curriculum.py`). O PDF do livro fica só na
  sua máquina (`.book/`, fora do git: direitos autorais).

## 🎯 Compatibilidade realista (src/compat.py)
O LLM só **extrai fatos** da vaga (requisitos, anos, de onde aceita candidatos, visto, inglês, foco em ER). A nota é
calculada em Python: `habilidades × senioridade × local × inglês × foco`. Vaga remota só para EUA sem visto cai
para ~10%, porque na prática você não seria contratado. O site mostra cada fator e **o que falta**.

## 💰 Quanto custa
| Item | Custo |
|---|---|
| GitHub Actions + Pages (repo público), CallMeBot, fontes de vagas e papers | grátis |
| SerpAPI (plano grátis ~250 buscas/mês; usamos ~240) | grátis |
| Haiku 4.5: juiz de relevância | ≈ US$ 0,70/mês |
| Sonnet 5: fatos das vagas aprovadas + pílula diária + análise semanal | ≈ US$ 1,80/mês |
| **Total mensal** | **≈ US$ 2,50 (≈ R$ 14)** |
| 365 aulas com Sonnet 5 via Batch (uma única vez) | ≈ US$ 7 |

Travas de custo em `config.yaml`: `llm.max_items_per_day`, `serpapi.*`, `network.*`.

---

## 🚀 Passo a passo (uma vez só, ~30 min)

### 1. Chave da API do Claude (obrigatória)
1. Entre em <https://console.anthropic.com> (a conta onde você já tem créditos).
2. **Settings → API Keys → Create Key**. Nome: `linkage-radar`. Copie a chave (`sk-ant-...`) — ela só aparece uma vez.
3. **Recomendado:** *Settings → Limits* → defina um limite mensal de gasto (ex.: US$ 5). Assim é impossível ter surpresa.

### 2. SerpAPI (opcional, mas recomendado — deixa LinkedIn e eventos de graça)
1. Crie conta em <https://serpapi.com/users/sign_up> (plano Free, 100 buscas/mês).
2. Copie a *API Key* em <https://serpapi.com/manage-api-key>.

### 3. Adzuna (opcional — mais vagas)
1. <https://developer.adzuna.com/signup> → copie `app_id` e `app_key`.

### 4. WhatsApp com CallMeBot (grátis)
1. Salve o contato **+34 644 71 81 99** no celular (confira o número atual em <https://www.callmebot.com/blog/free-api-whatsapp-messages/>).
2. Envie para ele no WhatsApp: `I allow callmebot to send me messages`
3. Você recebe a sua **apikey** em alguns segundos (se não chegar em 2 min, tente de novo depois de 24h).
4. Seu número no formato internacional: `+5575XXXXXXXXX`.

### 5. Criar o repositório no GitHub
1. <https://github.com/new> → nome **`linkage-radar`**, **Public** (Pages e Actions ficam grátis). Não marque README.
2. No terminal, dentro desta pasta:
   ```bash
   git remote add origin https://github.com/SEU_USUARIO/linkage-radar.git
   git push -u origin main
   ```
3. Em `config.yaml`, troque `SEU_USUARIO` em `site_url` pelo seu usuário e faça commit/push.

### 6. Secrets (Settings → Secrets and variables → Actions → New repository secret)
| Nome | Valor | Obrigatório |
|---|---|---|
| `ANTHROPIC_API_KEY` | `sk-ant-...` | ✅ |
| `WHATSAPP_PHONE` | `+5575XXXXXXXXX` | ✅ |
| `CALLMEBOT_APIKEY` | apikey do CallMeBot | ✅ |
| `SERPAPI_KEY` | chave SerpAPI | recomendado |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | chaves Adzuna | opcional |

### 7. Ligar o GitHub Pages
**Settings → Pages → Build and deployment → Source: GitHub Actions.**

### 8. Primeira execução (manual)
Aba **Actions**:
1. **"gerar aulas (rodar 1 vez)"** → *Run workflow*. Gera as 335 aulas restantes (as 30 primeiras eu já escrevi).
2. **"coletar"** → *Run workflow*. Ao terminar, o site estará em `https://SEU_USUARIO.github.io/linkage-radar/`.
3. **"enviar"** → *Run workflow*. A mensagem chega no seu WhatsApp.

Pronto. A partir daí tudo roda sozinho todo dia.

---

## 🛠 Uso local

```bash
pip install -r requirements.txt
python src/main_collect.py --no-llm      # coleta só com palavras-chave (grátis)
python src/main_collect.py               # coleta completa (precisa de ANTHROPIC_API_KEY)
python src/main_send.py --dry-run        # mostra a mensagem do WhatsApp no terminal
python -m http.server 8765               # e abra http://localhost:8765/site/
pytest                                   # testes (grátis)
RUN_LLM_TESTS=1 pytest -s                # + teste real do juiz com 10 exemplos (~US$ 0,002)
```

No Windows (PowerShell), defina a chave assim: `$env:ANTHROPIC_API_KEY="sk-ant-..."`.

## ⏰ Mudar horários
Edite `send_time` em `config.yaml` (o envio espera rodando até esse horário) e faça commit + push. A coleta
(`.github/workflows/collect.yml`) precisa terminar antes: hoje ela é agendada para 20:17 e roda de fato ~02h.

## 🎯 Como a precisão é garantida
1. **Palavras-chave** (`src/filters/keywords.py`): termos fortes (+3), médios (+1), negativos (−3). Além do score ≥ 3, o termo forte tem que estar no **título** ou aparecer **2+ vezes** no texto — isso elimina o falso positivo clássico de empresas de MDM cuja descrição institucional ("líderes em entity resolution") aparece em todas as vagas, até de SRE.
2. **Juiz LLM** (`src/filters/llm_judge.py`): Claude Haiku avalia em lotes e só aprova com `confianca ≥ 0.8`. Se a resposta vier quebrada, o lote é descartado (precisão > recall).
3. **Dedup** (`data/seen.json`): item julgado nunca é julgado nem mostrado de novo.
4. **Anti-alucinação** nas buscas web: só entram URLs que realmente apareceram nos resultados.

## 🔗 Sobre o LinkedIn
O LinkedIn não tem API pública de busca e proíbe scraping. O radar busca posts **públicos já indexados** (`linkedin.com/posts` e `/pulse`) via SerpAPI (Google) ou via a busca web do Claude, dos últimos 7 dias, e passa tudo pelo juiz. Alguns posts recentes podem demorar 1–3 dias para aparecer nos buscadores.

## 📁 Estrutura
```
config.yaml            tudo configurável (termos, empresas, limites, horários)
src/main_collect.py    orquestra a coleta
src/main_send.py       envia o WhatsApp (--dry-run)
src/sources/           jobs, papers, events, linkedin, websearch
src/filters/           keywords (etapa 1) e llm_judge (etapa 2)
src/notify/            callmebot e twilio
curriculum/            plan.py (52 semanas) e lessons.json (365 aulas geradas)
profile/curriculo.md   seu currículo sem dados de contato (base da análise de perfil)
src/compat.py          compatibilidade realista vaga x perfil
src/career.py          pílula diária do mercado e análise semanal do perfil
scripts/               build_curriculum.py, rescore_jobs.py, wait_until_send.py
site/                  HTML + CSS + JS puro
.github/workflows/     coletar, enviar, publicar site, gerar aulas
```
