// Linkage Radar — site estático. Lê data/index.json e data/AAAA-MM-DD.json.
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

const jobHTML = (v, withAge = false) => `
    <h3>${withAge && v.nova ? '<span class="badge">NOVA</span>' : ""}${esc(v.titulo)}</h3>
    <p class="meta">${esc(v.empresa)}${v.local ? " · " + esc(v.local) : ""} · ${esc(v.fonte)}${
      withAge && v.desde ? " · desde " + fmtDate(v.desde) : ""}</p>
    ${v.encaixe ? `<p class="why"><span class="fit">Encaixe ${Math.round(v.encaixe * 100)}%</span>${
      v.nota_perfil ? " — " + esc(v.nota_perfil) : ""}</p>` : ""}
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

function lessonHTML(a) {
  if (!a) return `<p class="empty">Sem aula hoje.</p>`;
  return `
    <h3>Aula ${a.dia}: ${esc(a.titulo)}</h3>
    <p class="mod">${esc(a.modulo)}</p>
    ${a.explicacao ? `<p>${esc(a.explicacao)}</p>` : `<p class="meta">Conteúdo ainda não gerado (rode o workflow "Gerar aulas").</p>`}
    ${a.exemplo ? `<blockquote>${esc(a.exemplo)}</blockquote>` : ""}
    ${a.pergunta_reflexao ? `<p class="q">🤔 ${esc(a.pergunta_reflexao)}</p>` : ""}`;
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
    ["vagas", "papers", "eventos", "linkedin"].forEach((k) => renderSection(k, rep[k] || []));
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
    const jobs = await getJSON("data/open_jobs.json");
    $(".count", card).textContent = jobs.length;
    const checked = jobs.map((j) => j.verificada_em).sort().pop();
    $("#abertas-atualizado").textContent = checked ? `Última verificação: ${fmtDate(checked)}.` : "";
    $(".list", card).innerHTML = jobs.length
      ? jobs.map((j) => `<article class="item">${jobHTML(j, true)}</article>`).join("")
      : `<p class="empty">Nenhuma vaga aberta no momento ✅</p>`;
  } catch {
    $(".count", card).textContent = 0;
    $(".list", card).innerHTML = `<p class="meta">A lista aparece após a próxima coleta.</p>`;
  }
}

(async function init() {
  loadOpenJobs();
  const sel = $("#day");
  let dates = [];
  try {
    dates = (await getJSON("data/index.json")).datas;
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
