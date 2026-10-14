// Linkage Radar: site estático. Lê data/index.json e data/AAAA-MM-DD.json.
// Localmente (python -m http.server na raiz do repo, abrindo /site/) os dados ficam em ../
const BASE = location.pathname.includes("/site/") ? "../" : "./";
const $ = (sel, root = document) => root.querySelector(sel);

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? esc(u) : "#");
const fmtDate = (iso) => {
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
};

async function getJSON(path) {
  const r = await fetch(BASE + path, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

const reqHTML = (r) => {
  if (!r || !(r.obrigatorios?.length || r.desejaveis?.length)) return "";
  const chips = (xs, cls) => xs.map((x) => `<span class="chip ${cls}">${esc(x)}</span>`).join("");
  return `<p class="reqs">${chips(r.obrigatorios || [], "must")}${chips(r.desejaveis || [], "nice")}</p>`;
};

const compatHTML = (d) => {
  if (!d) return "";
  const falta = d.faltam?.length ? `<br>Falta: ${d.faltam.map(esc).join(", ")}` : "";
  const parcial = d.parciais?.length ? `<br>Parcial: ${d.parciais.map(esc).join(", ")}` : "";
  return `<p class="compat">Habilidades ${d.habilidades}% · Senioridade ${d.senioridade}% (${esc(d.senioridade_txt)})
    · Local ${d.local}% (${esc(d.local_txt)})${d.ingles < 100 ? ` · Inglês ${d.ingles}%` : ""}${falta}${parcial}</p>`;
};

function pubLabel(iso) {
  const ref = LATEST_EDITION ? new Date(LATEST_EDITION + "T12:00:00") : new Date();
  const d = Math.round((ref - new Date(iso + "T12:00:00")) / 864e5);
  return d <= 0 ? "publicada hoje" : d === 1 ? "publicada ontem" : `publicada há ${d} dias (${fmtDate(iso)})`;
}

const jobHTML = (v, withAge = false) => `
    <h3>${withAge && v.nova ? '<span class="badge">NOVA</span>' : ""}${esc(v.titulo)}</h3>
    <p class="meta">${esc(v.empresa)}${v.local ? " · " + esc(v.local) : ""} · ${esc(v.fonte)}${
      withAge && v.desde ? " · no radar desde " + fmtDate(v.desde) : ""}</p>
    ${v.publicada_em ? `<p class="pub">🗓️ ${pubLabel(v.publicada_em)}</p>` : ""}
    ${v.encaixe != null ? `<p class="why"><span class="fit">🎯 ${Math.round(v.encaixe * 100)}% compatível com seu perfil</span></p>` : ""}
    ${compatHTML(v.compat_detalhe)}
    ${reqHTML(v.requisitos)}
    ${v.motivo ? `<p class="why">✔ ${esc(v.motivo)}</p>` : ""}
    <a class="btn" href="${safeUrl(v.url)}" target="_blank" rel="noopener">Ver vaga</a>`;

const RENDER = {
  vagas: (v) => jobHTML(v),
  papers: (p) => `
    <h3>${esc(p.titulo)}</h3>
    <p class="meta">${esc(p.autores)}${p.data ? " · " + esc(p.data) : ""} · ${esc(p.fonte)}</p>
    ${p.resumo ? `<p class="why">${esc(p.resumo)}</p>` : ""}
    <a class="btn" href="${safeUrl(p.url)}" target="_blank" rel="noopener">Ler</a>`,
  eventos: (e) => `
    <h3>${esc(e.titulo)}</h3>
    <p class="meta">${e.data ? esc(e.data) : "data no link"}</p>
    ${e.resumo || e.motivo ? `<p class="why">${esc(e.resumo || e.motivo)}</p>` : ""}
    <a class="btn" href="${safeUrl(e.url)}" target="_blank" rel="noopener">Ver evento</a>`,
  linkedin: (p) => `
    <h3>${esc(p.titulo)}</h3>
    ${p.data ? `<p class="meta">${esc(p.data)}</p>` : ""}
    ${p.resumo ? `<p class="why">${esc(p.resumo)}</p>` : ""}
    <a class="btn" href="${safeUrl(p.url)}" target="_blank" rel="noopener">Abrir post</a>`,
};

function renderSection(key, items) {
  const card = $("#" + key);
  $(".count", card).textContent = items.length;
  $(".list", card).innerHTML = items.length
    ? items.map((it) => `<article class="item">${RENDER[key](it)}</article>`).join("")
    : `<p class="empty">Nada novo hoje ✅</p>`;
}

// Link do livro: fica SÓ no navegador de quem colou (localStorage); nunca é publicado no site.
const BOOK_KEY = "linkageRadar.bookUrl";
const PDF_OFFSET = 16;  // página impressa + 16 = página do PDF
const getBook = () => { try { return localStorage.getItem(BOOK_KEY) || ""; } catch { return ""; } };
function bookHref(page) {
  // abre no visualizador próprio (livro.html), que vai direto à página, inclusive no celular
  return getBook().trim() ? new URL(`livro.html#p=${page}`, location.href).href : "";
}
function bookLinks(a) {
  const refs = (a.fontes || []).filter((f) => f.includes("Christen (2012)"));
  let pages = refs.map((f) => (f.match(/p\.\s*(\d+)/) || [])[1]).filter(Boolean).map(Number);
  if (!pages.length && a.livro?.length) pages = [a.livro[0][0]];
  pages = [...new Set(pages)];
  if (!pages.length) return "";
  const label = refs.length ? esc(refs.join("; ")) : `Christen (2012), p. ${pages[0]}`;
  const links = getBook()
    ? pages.map((p) => `<a class="btn" href="${safeUrl(bookHref(p))}" target="_blank" rel="noopener">Abrir p. ${p}</a>`).join(" ")
    : `<button class="btn set-book" type="button">Configurar link do livro</button>`;
  return `<div class="sec book"><h4>📖 No livro</h4><p class="pre">${label}</p>${links}</div>`;
}
document.addEventListener("click", (e) => {
  if (!e.target.classList.contains("set-book")) return;
  const url = prompt("Cole o link do SEU PDF do livro (Dropbox/OneDrive). Ele fica só neste navegador:", getBook());
  if (url === null) return;
  try { localStorage.setItem(BOOK_KEY, url.trim()); } catch {}
  location.reload();
});

const sec = (title, text, cls = "pre") => text ? `<div class="sec"><h4>${title}</h4><p class="${cls}">${esc(text)}</p></div>` : "";

function lessonHTML(a) {
  if (!a) return `<p class="empty">Sem aula hoje.</p>`;
  if (a.versao !== 2) {  // formato antigo
    return `
    <h3>Aula ${a.dia}: ${esc(a.titulo)}</h3>
    <p class="mod">${esc(a.modulo || "")}</p>
    ${a.explicacao ? `<p>${esc(a.explicacao)}</p>` : ""}
    ${a.exemplo ? `<blockquote>${esc(a.exemplo)}</blockquote>` : ""}`;
  }
  const head = `<h3>Aula ${a.dia} de 365: ${esc(a.titulo)}</h3>
    <p class="mod">Semana ${a.semana} de 52 · ${esc(a.tema)} · ${{conceito: "conceito", laboratorio: "laboratório", revisao: "revisão ativa"}[a.tipo]}</p>`;
  if (!a.gerada) return head + `<p class="meta">Conteúdo desta aula ainda está sendo gerado.</p>`;
  let body = bookLinks(a) + sec("🎯 Objetivo", a.objetivo);
  if (a.tipo === "conceito") {
    body += sec("📖 Conceito", a.conceito) + sec("🧮 Como funciona", a.como_funciona) +
      sec("✍️ Exemplo resolvido", a.exemplo) + sec("🛠️ Na prática", a.na_pratica, "pre code") +
      sec("⚠️ Armadilha", a.armadilha);
  } else if (a.tipo === "laboratorio") {
    body += sec("🧪 Contexto", a.contexto) +
      `<div class="sec"><h4>📋 Passos</h4><ol>${a.passos.map((p) => `<li>${esc(p)}</li>`).join("")}</ol></div>` +
      sec("💻 Código inicial", a.codigo, "pre code") + sec("📏 Como avaliar", a.como_avaliar);
  } else {
    body += sec("🗺️ Mapa da semana", a.conexao) +
      `<div class="sec"><h4>❓ Responda antes de abrir</h4>${a.perguntas.map((q, i) =>
        `<details class="qa"><summary>${i + 1}. ${esc(q.pergunta)}</summary><p class="pre">${esc(q.resposta)}</p></details>`).join("")}</div>`;
  }
  body += `<div class="sec"><h4>🧠 Desafio</h4><p class="pre">${esc(a.desafio)}</p>
    <details class="qa"><summary>Ver gabarito</summary><p class="pre">${esc(a.gabarito)}</p></details></div>`;
  if (a.fontes?.length) body += `<p class="meta">📚 ${a.fontes.map(esc).join("; ")}</p>`;
  return head + body;
}

async function renderPastLessons(current) {
  const list = $(".past-list");
  if (!current || list.dataset.for == current.dia) return;
  list.dataset.for = current.dia;
  try {
    const all = await getJSON("curriculum/lessons.json");
    const past = all.filter((l) => l.dia < current.dia).reverse();
    list.innerHTML = past.length
      ? past.map((l) => `<li value="${l.dia}"><details><summary>${esc(l.titulo)}</summary>${lessonHTML(l)}</details></li>`).join("")
      : "<li>Esta é a primeira aula.</li>";
  } catch {
    list.innerHTML = "<li>Não foi possível carregar as aulas.</li>";
  }
}

async function load(day) {
  $("#status").textContent = "Carregando…";
  try {
    const rep = await getJSON(`data/${day}.json`);
    const byCompat = (xs) => [...xs].sort((a, b) => (b.encaixe || 0) - (a.encaixe || 0));
    // vagas novas agora ficam dentro da seção única de vagas (loadOpenJobs)
    ["papers", "eventos", "linkedin"].forEach((k) => renderSection(k, rep[k] || []));
    $("#aula .lesson").innerHTML = lessonHTML(rep.aula);
    renderPastLessons(rep.aula);
    $("#status").textContent = `Edição de ${fmtDate(rep.data)}` + (rep.llm ? "" : " · ⚠ sem juiz LLM");
    const s = rep.estatisticas || {};
    const total = Object.values(s).reduce((a, x) => a + (x.brutos || 0), 0);
    $("#stats").textContent = total ? `${total} itens analisados nesta edição.` : "";
    history.replaceState(null, "", "#" + day);
  } catch (e) {
    $("#status").textContent = "Não foi possível carregar este dia.";
  }
}

async function loadOpenJobs() {
  const card = $("#abertas");
  try {
    const jobs = (await getJSON("data/open_jobs.json")).sort((a, b) => (b.encaixe || 0) - (a.encaixe || 0));
    $(".count", card).textContent = jobs.length;
    const checked = jobs.map((j) => j.verificada_em).sort().pop();
    $("#abertas-atualizado").textContent = checked ? `Última verificação: ${fmtDate(checked)}.` : "";
    if (!jobs.length) {
      $(".list", card).innerHTML = `<p class="empty">Nenhuma vaga aberta no momento ✅</p>`;
      return;
    }
    jobs.forEach((j) => (j.nova = !!LATEST_EDITION && j.desde === LATEST_EDITION));
    const FRESH_DAYS = 2;
    const ref = LATEST_EDITION ? new Date(LATEST_EDITION + "T12:00:00") : new Date();
    const ageDays = (j) => j.publicada_em ? Math.round((ref - new Date(j.publicada_em + "T12:00:00")) / 864e5) : null;
    const frescas = jobs.filter((j) => ageDays(j) !== null && ageDays(j) <= FRESH_DAYS)
      .sort((a, b) => (b.publicada_em || "").localeCompare(a.publicada_em || "") || (b.encaixe || 0) - (a.encaixe || 0));
    const novas = jobs.filter((j) => j.nova && !frescas.includes(j));
    const top = jobs.filter((j) => !j.nova && !frescas.includes(j)).slice(0, 4);
    const shownSet = new Set([...frescas, ...novas, ...top]);
    const rest = jobs.filter((j) => !shownSet.has(j));
    const block = (title, list) => list.length
      ? `<h3 class="sub">${title}</h3><div class="grid2">${list.map((j) => `<article class="item${j.nova ? " is-new" : ""}">${jobHTML(j, true)}</article>`).join("")}</div>` : "";
    const render = (all) => {
      $(".list", card).innerHTML =
        (frescas.length ? block(`🔥 Publicadas nos últimos ${FRESH_DAYS + 1} dias: candidate-se cedo (${frescas.length})`, frescas)
                        : `<p class="empty">Nenhuma vaga publicada nos últimos ${FRESH_DAYS + 1} dias ✅</p>`) +
        block(`🆕 Novas no radar, publicadas há mais tempo (${novas.length})`, novas) +
        block("🏆 As 4 mais compatíveis entre as que você já viu", top) +
        (all ? block(`Todas as outras (${rest.length})`, rest)
             : rest.length ? `<button class="btn more" type="button">Ver todas as ${jobs.length} vagas abertas</button>` : "");
      $(".more", card)?.addEventListener("click", () => render(true));
    };
    render(false);
  } catch {
    $(".count", card).textContent = 0;
    $(".list", card).innerHTML = `<p class="meta">A lista aparece após a próxima coleta.</p>`;
  }
}

let skillsData = null;
const LEVEL = { tem: "✅ você tem", parcial: "🟡 parcial", nao: "⭕ falta" };

function barRows(rows, withLevel = true) {
  const max = Math.max(...rows.map((s) => s.vagas), 1);
  return rows.map((s) => `
    <div class="bar-row lvl-${s.voce || "nao"}" title="${s.obrigatorio ?? ""} obrigatório, ${s.desejavel ?? ""} desejável">
      <span class="bar-name">${esc(s.nome)}${withLevel ? `<small>${LEVEL[s.voce] || ""}</small>` : ""}</span>
      <span class="bar">${s.obrigatorio != null
        ? `<span class="bar-must" style="width:${(100 * s.obrigatorio) / max}%"></span><span class="bar-nice" style="width:${(100 * s.desejavel) / max}%"></span>`
        : `<span class="bar-must" style="width:${(100 * s.vagas) / max}%"></span>`}</span>
      <span class="bar-pct">${s.pct}%</span>
    </div>`).join("");
}

function renderSkills(view) {
  const d = skillsData;
  const card = $("#skills");
  if (!d?.geral?.ranking?.length) {
    $(".list", card).innerHTML = `<p class="meta">O ranking aparece após a próxima coleta.</p>`;
    return;
  }
  const g = d.ganhos || {};
  let html = "";
  if (view === "plano") {
    $("#skills-n").textContent = `Hoje você cobre ${g.cobertura_atual}% dos requisitos das ${g.vagas_analisadas} vagas do nicho e cumpre TODOS os obrigatórios em ${g.vagas_completas_hoje}.`;
    const row = (x) => `<li><b>${esc(x.nome)}</b> <small>(${LEVEL[x.voce] || ""}, pedido em ${x.pct_nicho}% das vagas)</small><br>
      +${x.ganho_cobertura} pontos de cobertura${x.vagas_completas_a_mais ? ` · +${x.vagas_completas_a_mais} vaga(s) em que você passa a cumprir todos os obrigatórios` : ""}</li>`;
    html = `<div class="sec"><h4>1º Famílias (aprender uma ferramenta da família já conta)</h4><ol>${(g.familias || []).slice(0, 8).map(row).join("")}</ol></div>
      <div class="sec"><h4>2º Habilidades específicas</h4><ol>${(g.habilidades || []).slice(0, 12).map(row).join("")}</ol></div>
      <p class="meta">Quando estudar algo, declare em <code>config.yaml</code> → <code>niveis_declarados</code> (ou atualize <code>profile/curriculo.md</code>): todas as compatibilidades são recalculadas na coleta seguinte.</p>`;
  } else if (view === "familias") {
    $("#skills-n").textContent = `${d.geral.vagas_analisadas} vagas do nicho. Uma vaga conta uma vez por família.`;
    html = (d.geral.familias || []).map((f) => `
      <div class="bar-row lvl-${f.voce}"><span class="bar-name">${esc(f.nome)}<small>${LEVEL[f.voce] || ""} · ${f.exemplos.map(esc).join(", ")}</small></span>
      <span class="bar"><span class="bar-must" style="width:${f.pct}%"></span></span><span class="bar-pct">${f.pct}%</span></div>`).join("");
  } else {
    const src = d[view] || d.geral;
    $("#skills-n").textContent = view === "mercado_amplo"
      ? `${src.vagas_analisadas} vagas de engenharia/ciência de dados em geral (amostra semanal), para comparar com o nicho.`
      : `${src.vagas_analisadas} vagas do nicho analisadas.`;
    html = src.ranking?.length ? barRows(src.ranking.slice(0, 35)) : `<p class="meta">A amostra aparece após a próxima coleta de domingo.</p>`;
  }
  $(".list", card).innerHTML = html;
}

async function loadSkills() {
  try {
    skillsData = await getJSON("data/skills.json");
  } catch {}
  const sel = $("#skills-period");
  sel.addEventListener("change", () => renderSkills(sel.value));
  renderSkills(sel.value);
}

// Link curto do WhatsApp: #vaga-<sha1[:6] da URL> redireciona direto para a vaga
async function sha1(text) {
  const buf = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function redirectToJob(id) {
  $("#status").textContent = "Abrindo a vaga…";
  const lists = await Promise.all(["data/open_jobs.json", "data/jobs_archive.json"].map((f) => getJSON(f).catch(() => [])));
  for (const job of lists.flat()) {
    if ((await sha1(job.url)).startsWith(id)) {
      location.replace(job.url);
      return true;
    }
  }
  $("#status").textContent = "Vaga não encontrada (pode ter sido encerrada). Veja a lista abaixo.";
  return false;
}

function marketHTML(m) {
  const list = (xs) => `<ul>${xs.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
  return `<h3>${esc(m.habilidade)}</h3>
    <p class="mod">Aparece em ${m.pct_vagas}% das vagas do nicho · você hoje: ${esc(m.nivel_atual)} · ${fmtDate(m.data)}</p>
    ${sec("O que é", m.o_que_e)}${sec("Por que pedem", m.por_que_pedem)}
    ${sec("Ponte com o que você já sabe", m.ponte_com_o_que_voce_sabe)}
    <div class="sec"><h4>Mínimo para ficar apto</h4>${list(m.minimo_para_ficar_apto)}</div>
    <div class="sec"><h4>Plano rápido</h4>${list(m.plano_rapido)}</div>
    ${sec("Mini-projeto de portfólio", m.mini_projeto)}${sec("Como colocar no currículo", m.como_colocar_no_curriculo)}
    <div class="sec"><h4>Perguntas de entrevista</h4>${m.perguntas_de_entrevista.map((q) =>
      `<details class="qa"><summary>${esc(q.pergunta)}</summary><p class="pre">${esc(q.resposta)}</p></details>`).join("")}</div>
    <p class="meta">Para estudar: ${m.fontes_para_estudar.map(esc).join("; ")}</p>`;
}

async function loadMarket() {
  const card = $("#pilula");
  try {
    const all = await getJSON("data/market_lessons.json");
    $(".content", card).innerHTML = all.length ? marketHTML(all[0]) +
      (all.length > 1 ? `<details class="past"><summary>Pílulas anteriores</summary>${all.slice(1).map((m) =>
        `<details class="qa"><summary>${esc(m.habilidade)} (${fmtDate(m.data)})</summary>${marketHTML(m)}</details>`).join("")}</details>` : "")
      : `<p class="meta">A primeira pílula aparece após a próxima coleta.</p>`;
  } catch {
    $(".content", card).innerHTML = `<p class="meta">A primeira pílula aparece após a próxima coleta.</p>`;
  }
}

async function loadTips() {
  const card = $("#perfil");
  let t;
  try {
    t = await getJSON("data/profile_tips.json");
  } catch {
    $(".content", card).innerHTML = `<p class="meta">A primeira análise aparece no próximo domingo.</p>`;
    return;
  }
  const list = (xs) => `<ul>${xs.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
  $(".content", card).innerHTML = `
    <p class="mod">Atualizado em ${fmtDate(t.data)} · ${t.perfis_analisados} perfis de especialistas analisados</p>
    ${sec("Diagnóstico", t.diagnostico)}
    <div class="sec"><h4>Headline (LinkedIn, inglês)</h4>${list(t.headlines_en)}<p class="pre">PT: ${esc(t.headline_pt)}</p></div>
    ${sec("About (LinkedIn, inglês)", t.sobre_en)}
    <div class="sec"><h4>Competências, nesta ordem</h4><p>${t.competencias_linkedin.map((c) => `<span class="chip must">${esc(c)}</span>`).join(" ")}</p></div>
    <div class="sec"><h4>Bullets do currículo (troque [X] pelos seus números reais)</h4>${t.bullets_experiencia.map((b) =>
      `<p class="pre"><s>${esc(b.antes)}</s><br>✅ ${esc(b.depois)}</p>`).join("")}</div>
    <div class="sec"><h4>Lacunas prioritárias</h4>${t.lacunas_prioritarias.map((l) =>
      `<p class="pre"><b>${esc(l.habilidade)}</b>: ${esc(l.por_que)}<br>Como fechar: ${esc(l.como_fechar)}</p>`).join("")}</div>
    <div class="sec"><h4>O que os especialistas destacam e você não</h4>${list(t.padroes_dos_especialistas)}</div>
    <div class="sec"><h4>Ajustes no currículo</h4>${list(t.ajustes_curriculo)}</div>
    <div class="sec"><h4>Palavras-chave para ATS</h4><p>${t.palavras_chave_ats.map((c) => `<span class="chip nice">${esc(c)}</span>`).join(" ")}</p></div>
    <div class="sec"><h4>Plano de 30 dias</h4>${list(t.plano_30_dias)}</div>`;
}

const NET_LIMIT = 15;
let LATEST_EDITION = "";

async function loadHealth() {
  const card = $("#saude");
  let h;
  try {
    h = await getJSON("data/health.json");
  } catch {
    card.hidden = true;
    return;
  }
  const icon = { ok: "✅", atencao: "⚠️", problema: "🚨" }[h.status] || "❔";
  const label = { ok: "tudo funcionando", atencao: "atenção", problema: "problema" }[h.status] || h.status;
  const rows = (h.checks || []).filter((c) => c.status !== "ok");
  const fontes = Object.entries(h.fontes || {}).sort()
    .map(([k, v]) => `<span class="chip ${v > 0 ? "must" : "nice"}">${esc(k.split("/")[1])}: ${v < 0 ? "erro" : v}</span>`).join(" ");
  $(".content", card).innerHTML = `
    <p class="mod">${icon} ${label} · coleta de ${fmtDate(h.data)}</p>
    ${rows.length ? `<ul>${rows.map((c) => `<li><b>${esc(c.nome)}</b>: ${esc(c.detalhe)}</li>`).join("")}</ul>` : ""}
    <details class="qa"><summary>Itens por fonte nesta coleta</summary><p>${fontes}</p></details>`;
  if (h.status !== "ok") card.classList.add("alerta");
  if (h.status === "problema") card.parentNode.prepend(card);  // problema sobe para o topo
}

async function loadNetwork(file, cardId, button) {
  const card = $("#" + cardId);
  let items = [];
  try {
    items = await getJSON(file);
  } catch {}
  $(".count", card).textContent = items.length;
  if (!items.length) {
    $(".list", card).innerHTML = `<p class="meta">A lista aparece após a próxima coleta.</p>`;
    return;
  }
  const latest = LATEST_EDITION;
  items.forEach((x) => (x.novo = !!latest && x.desde === latest));
  items.sort((a, b) => (b.novo - a.novo) || (b.desde || "").localeCompare(a.desde || ""));
  const nNew = items.filter((x) => x.novo).length;
  $(".novos-hoje", card).innerHTML = nNew
    ? `✨ <b>${nNew} ${nNew === 1 ? "novo" : "novos"}</b> em ${fmtDate(latest)}: siga ${nNew === 1 ? "ele" : "eles"} primeiro`
    : "";
  const row = (x) => `<article class="item${x.novo ? " is-new" : ""}">
      <h3>${x.novo ? '<span class="badge">NOVO</span>' : ""}${esc(x.nome || x.titulo)}</h3>
      ${x.resumo ? `<p class="why">${esc(x.resumo)}</p>` : ""}
      <p class="meta">${esc(x.fonte || "")}${x.desde ? " · desde " + fmtDate(x.desde) : ""}</p>
      <a class="btn" href="${safeUrl(x.url)}" target="_blank" rel="noopener">${button}</a></article>`;
  const render = (all) => {
    const shown = all ? items : items.filter((x) => x.novo);
    $(".list", card).innerHTML = (shown.length ? shown.map(row).join("")
      : `<p class="empty">Nenhum novo nesta edição ✅ (você já viu todos)</p>`) +
      (!all && items.length > shown.length
        ? `<button class="btn more" type="button">Ver todos (${items.length})</button>` : "");
    $(".more", card)?.addEventListener("click", () => render(true));
  };
  render(false);
}

(async function init() {
  if (location.hash.startsWith("#vaga-") && (await redirectToJob(location.hash.slice(6)))) return;
  loadSkills();
  loadHealth();
  loadMarket();
  loadTips();
  const sel = $("#day");
  let dates = [];
  try {
    dates = (await getJSON("data/index.json")).datas;
    LATEST_EDITION = dates[0] || "";
    loadOpenJobs();
    loadNetwork("data/people.json", "pessoas", "Ver perfil");
    loadNetwork("data/companies.json", "empresas", "Ver empresa");
  } catch {
    $("#status").textContent = "Nenhuma edição publicada ainda.";
    return;
  }
  sel.innerHTML = dates.map((d) => `<option value="${d}">${fmtDate(d)}</option>`).join("");
  const wanted = location.hash.slice(1);
  sel.value = dates.includes(wanted) ? wanted : dates[0];
  sel.addEventListener("change", () => load(sel.value));
  load(sel.value);
})();
