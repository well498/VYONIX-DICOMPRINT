"use strict";
// Assistente do VYONIX DEPLOY: inventário → plano → aprovação → execução → relatório.
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const app = $("#app");
let state = null;
const LEVEL = { ok: "Atendido", alert: "Alerta", blocker: "Impeditivo", info: "Informação" };
const STATUS = { done: "Aplicado e conferido", already: "Já estava conforme", failed: "Falhou", rolled_back: "Revertido",
  rollback_failed: "Reversão falhou", not_approved: "Não aprovado", pending: "Aguardando", applying: "Aplicando…", planned: "—" };
const OPS = [
  ["install", "Nova instalação", "Instala o VYONIX Core, o banco e os serviços."],
  ["update", "Atualizar", "Faz backup, migra o banco e reinicia os serviços."],
  ["diagnose", "Diagnosticar", "Somente leitura: confere tudo e gera relatório."],
  ["repair", "Reparar", "Diagnostica e propõe o reparo do que divergir."],
  ["reconfigure", "Reconfigurar servidor", "Muda portas, certificado, firewall ou rede."],
  ["restore", "Restaurar backup", "Volta o banco a um backup do DEPLOY (exige confirmação)."],
  ["report", "Exportar relatório", "Baixa o PDF da execução mais recente."],
];

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json",
    "X-Vyonix-Wizard": "1" }, body: JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(data.error || `Erro ${r.status}`); e.data = data; throw e; }
  return data;
}

async function home() {
  state = await api("/api/state");
  $("#ver").textContent = `versão ${state.version}`;
  app.innerHTML = `<h1>${state.installed ? "VYONIX instalado neste servidor" : "Instalar o VYONIX"}</h1>
    <p class="intro">Nada é alterado antes da sua aprovação. Cada execução gera um relatório PDF e um manifesto em
    ProgramData\\VYONIX\\Deploy\\relatorios.</p>
    ${state.pending ? `<div class="notice warn">Há uma execução interrompida. Ela será retomada na próxima operação.</div>` : ""}
    <div class="ops">${OPS.filter(([k]) => state.installed ? k !== "install" : k === "install")
      .map(([k, t, d]) => `<button data-op="${k}"><strong>${t}</strong><span>${d}</span></button>`).join("")}</div>
    <h2>Execuções recentes</h2>${runsTable(state.runs)}`;
  app.querySelectorAll("[data-op]").forEach((b) => b.onclick = () => start(b.dataset.op));
}

function runsTable(runs) {
  if (!runs.length) return `<p class="sub">Nenhuma execução registrada.</p>`;
  return `<table><thead><tr><th>Execução</th><th>Tipo</th><th>Situação</th><th>Quando</th><th></th></tr></thead><tbody>${runs.map((r) =>
    `<tr><td><code>${esc(r.id)}</code></td><td>${esc(r.kind)}</td><td>${esc(r.status)}</td><td>${esc(r.updated_at)}</td>
     <td><a href="/api/report/${esc(r.id)}">PDF</a></td></tr>`).join("")}</tbody></table>`;
}

function optionsForm(kind) {
  const c = state.config;
  const n = c.network || {};
  return `<form id="opts" class="panel"><h2>Opções</h2><div class="grid">
    <label class="f">Código da organização <input name="organization" value="${esc(c.organization)}" ${kind !== "install" ? "readonly" : ""} required pattern="[a-z0-9][a-z0-9-]{1,39}"></label>
    <label class="f">Nome da instituição <input name="organization_name" value="${esc(c.organization_name)}"></label>
    <label class="f">Usuário administrador <input name="admin_user" value="${esc(c.admin_user)}" ${kind !== "install" ? "readonly" : ""}></label>
    <label class="f">Porta HTTPS <input name="https_port" type="number" min="1024" max="65535" value="${c.https_port}"></label>
    <label class="f">Porta do banco (local) <input name="pg_port" type="number" min="1024" max="65535" value="${c.pg_port}"></label>
    <label class="f">Origens permitidas no firewall <span>Vazio = redes privada e de domínio. Ex.: 10.0.0.0/24</span>
      <input name="firewall_sources" value="${esc((c.firewall_sources || []).join(", "))}"></label>
    <label class="f">Certificado da instituição (.pfx) <span>Caminho no servidor. Vazio = autoassinado (pendência registrada).</span>
      <input name="tls_pfx" value="${esc(c.tls_pfx || "")}"></label>
    </div>
    <h2>Backup do PACS</h2><div class="grid">
    <label class="f">Pasta do backup diário das imagens <span>Vazio = ProgramData\\VYONIX\\Backups\\PACS (mesmo disco). Prefira outro disco. Vale quando o PACS estiver ativado.</span>
      <input name="pacs_backup_dir" value="${esc(c.pacs_backup_dir || "")}"></label>
    <label class="f">Hora do backup (0–23, hora local) <input name="pacs_backup_hour" type="number" min="0" max="23" value="${c.pacs_backup_hour ?? 2}"></label>
    </div>
    <h2>Rede</h2>
    <label><input type="radio" name="netmode" value="keep" ${n.mode !== "static" ? "checked" : ""}> Manter o IP atual (recomendado)</label><br>
    <label><input type="radio" name="netmode" value="static" ${n.mode === "static" ? "checked" : ""}> Definir IP fixo (exige confirmação)</label>
    <div class="grid" id="static" style="margin-top:.5rem">
      <label class="f">Interface <input name="interface" value="${esc(n.interface || "")}"></label>
      <label class="f">IP <input name="ip" value="${esc(n.ip || "")}"></label>
      <label class="f">Prefixo <input name="prefix" type="number" min="8" max="30" value="${n.prefix || 24}"></label>
      <label class="f">Gateway <input name="gateway" value="${esc(n.gateway || "")}"></label>
      <label class="f">DNS <span>separados por vírgula</span><input name="dns" value="${esc((n.dns || []).join(", "))}"></label>
    </div>
    ${kind === "install" ? `<h2>Primeiro administrador</h2><div class="grid">
      <label class="f">Senha <span>10+ caracteres, maiúsculas, minúsculas e números</span><input name="admin_password" type="password" autocomplete="new-password"></label>
      <label class="f">Senha do .pfx (se houver) <input name="pfx_password" type="password" autocomplete="off"></label></div>` : ""}
    <div class="actions"><button class="primary">Analisar e gerar plano</button><button type="button" class="ghost" id="back">Voltar</button></div></form>`;
}

function readOptions(f) {
  const v = (k) => f.elements[k]?.value?.trim();
  const list = (k) => (v(k) || "").split(",").map((x) => x.trim()).filter(Boolean);
  const mode = f.querySelector("input[name=netmode]:checked").value;
  return {
    config: { organization: v("organization"), organization_name: v("organization_name"), admin_user: v("admin_user"),
      https_port: Number(v("https_port")), pg_port: Number(v("pg_port")), firewall_sources: list("firewall_sources"),
      tls_pfx: v("tls_pfx") || null, pacs_backup_dir: v("pacs_backup_dir") || null,
      pacs_backup_hour: Number(v("pacs_backup_hour") ?? 2),
      network: mode === "keep" ? { mode: "keep" } : { mode: "static", interface: v("interface"), ip: v("ip"),
        prefix: Number(v("prefix")), gateway: v("gateway"), dns: list("dns"), confirmed: true } },
    secrets: { admin_password: f.elements.admin_password?.value || "", pfx_password: f.elements.pfx_password?.value || "" },
  };
}

async function start(op) {
  if (op === "report") {
    const r = state.runs[0];
    if (r) location.href = `/api/report/${r.id}`; return;
  }
  if (op === "diagnose") return diagnose();
  if (op === "restore") return restoreView();
  if (op === "repair" || op === "update") return planView(op, { config: {} }, {});
  app.innerHTML = `<h1>${OPS.find((o) => o[0] === op)[1]}</h1>${optionsForm(op)}`;
  $("#back").onclick = home;
  $("#opts").onsubmit = (e) => { e.preventDefault(); const o = readOptions(e.target); planView(op, o, o.secrets); };
}

async function restoreView() {
  const list = await api("/api/backups", {});
  app.innerHTML = `<h1>Restaurar backup</h1>
    <div class="notice warn">A restauração substitui os dados atuais do VYONIX pelos do backup escolhido. Antes, o
    plano faz um backup do estado atual. Você precisará digitar a confirmação no plano.</div>
    ${list.length ? `<table><thead><tr><th></th><th>Backup</th><th>Data</th><th>Tamanho</th></tr></thead><tbody>${list.map((b, i) =>
      `<tr><td><input type="radio" name="bk" value="${esc(b.name)}" ${i === 0 ? "checked" : ""}></td><td><code>${esc(b.name)}</code></td>
       <td>${esc(b.at)}</td><td>${(b.bytes / 1048576).toFixed(1)} MB</td></tr>`).join("")}</tbody></table>`
      : `<p class="sub">Nenhum backup do DEPLOY encontrado.</p>`}
    <div class="actions">${list.length ? `<button class="primary" id="go">Planejar a restauração</button>` : ""}<button class="ghost" id="back">Voltar</button></div>`;
  $("#back").onclick = home;
  if ($("#go")) $("#go").onclick = () => planView("restore", { config: { restore_backup: app.querySelector("input[name=bk]:checked").value } }, {});
}

async function diagnose() {
  app.innerHTML = `<h1>Diagnóstico</h1><p class="intro">Conferindo serviços, firewall, portas, certificado, permissões, banco e relatórios… (somente leitura)</p>`;
  try {
    const r = await api("/api/diagnose", {});
    app.innerHTML = `<h1>Diagnóstico</h1>
      <p class="intro">${r.problems.length ? `${r.problems.length} problema(s) encontrado(s).` : "Nenhum problema encontrado."}
      Relatório: <a href="/api/report/${esc(r.run_id)}">baixar PDF</a></p>
      ${r.problems.length ? `<table><thead><tr><th>Gravidade</th><th>Problema</th><th>Reparo proposto</th></tr></thead><tbody>${r.problems.map((p) =>
        `<tr><td><span class="tag ${p.severity === "erro" ? "bad" : "alert"}">${esc(p.severity)}</span></td>
         <td><strong>${esc(p.title)}</strong><br><span class="sub">${esc(p.detail)}</span></td><td>${esc(p.repair)}</td></tr>`).join("")}</tbody></table>` : ""}
      <div class="actions">${r.problems.length ? `<button class="primary" id="rep">Planejar o reparo</button>` : ""}<button class="ghost" id="back">Voltar</button></div>`;
    $("#back").onclick = home;
    if ($("#rep")) $("#rep").onclick = () => planView("repair", { config: {} }, {});
  } catch (e) { error(e); }
}

async function planView(kind, opts, secrets) {
  app.innerHTML = `<h1>Plano</h1><p class="intro">Lendo o estado do servidor e montando o plano… nada é alterado nesta etapa.</p>`;
  let plan;
  try { plan = await api("/api/plan", { kind, config: opts.config }); }
  catch (e) {
    if (e.data && e.data.blockers) {
      app.innerHTML = `<h1>Não é possível continuar</h1><div class="notice err">${esc(e.message)}</div>
        <ul>${e.data.blockers.map((b) => `<li><strong>${esc(b.title)}:</strong> ${esc(b.detail)}</li>`).join("")}</ul>
        <p>Relatório de compatibilidade: <a href="/api/report/${esc(e.data.run_id)}">baixar PDF</a></p><button class="ghost" id="back">Voltar</button>`;
      $("#back").onclick = home; return;
    }
    return error(e);
  }
  const suggested = new Set(plan.suggested || plan.items.filter((i) => !i.already).map((i) => i.id));
  app.innerHTML = `<h1>Plano de mudanças</h1>
    <p class="intro">Revise item por item. Itens já conformes não serão alterados. Plano <code>${plan.plan_sha.slice(0, 16)}…</code></p>
    <h2>Compatibilidade</h2><table><tbody>${plan.compatibility.map((f) => `<tr><td><span class="tag ${f.level}">${LEVEL[f.level]}</span></td>
      <td><strong>${esc(f.title)}</strong><br><span class="sub">${esc(f.detail)}</span></td></tr>`).join("")}</tbody></table>
    <h2>Mudanças</h2><table><thead><tr><th></th><th>Item</th><th>Impacto e reversão</th></tr></thead><tbody>${plan.items.map((i) => `
      <tr><td>${i.already ? `<span class="tag ok">conforme</span>` : `<input type="checkbox" data-id="${esc(i.id)}" ${suggested.has(i.id) ? "checked" : ""} aria-label="Aprovar ${esc(i.title)}">`}</td>
      <td><strong>${esc(i.title)}</strong>${i.reboot ? ` <span class="tag alert">reinicialização</span>` : ""}${i.destructive ? ` <span class="tag bad">destrutivo</span>` : ""}
        ${i.confirm && !i.already ? `<br><label class="sub">Digite <strong>${esc(i.confirm)}</strong> para confirmar: <input data-confirm="${esc(i.id)}"></label>` : ""}</td>
      <td class="sub">${esc(i.impact)}<br>Desfazer: ${esc(i.undo)}</td></tr>`).join("")}</tbody></table>
    <div class="actions"><button class="primary" id="go">Aprovar os itens marcados e aplicar</button><button class="ghost" id="back">Cancelar</button></div>`;
  $("#back").onclick = home;
  $("#go").onclick = async () => {
    const items = [...app.querySelectorAll("input[data-id]:checked")].map((x) => x.dataset.id)
      .concat(plan.items.filter((i) => i.already).map((i) => i.id));
    const confirmations = {};
    app.querySelectorAll("input[data-confirm]").forEach((x) => confirmations[x.dataset.confirm] = x.value);
    try {
      $("#go").disabled = true;
      const r = await api("/api/approve", { run_id: plan.run_id, plan_sha: plan.plan_sha, items, confirmations, secrets });
      progress(r.job);
    } catch (e) { $("#go").disabled = false; error(e, false); }
  };
}

async function progress(job) {
  const j = await api(`/api/job/${job}`);
  app.innerHTML = `<h1>${j.status === "running" ? "Aplicando…" : j.status === "succeeded" ? "Concluído" : "Execução encerrada com falha"}</h1>
    ${j.message ? `<div class="notice ${j.status === "succeeded" ? "" : "err"}">${esc(j.message)}</div>` : ""}
    <table><thead><tr><th>Item</th><th>Situação</th><th>Verificação</th></tr></thead><tbody>${(j.steps || []).map((s) =>
      `<tr><td>${esc(s.title)}</td><td>${esc(STATUS[s.status] || s.status)}</td><td class="sub">${esc(s.verify_msg || s.error || "")}</td></tr>`).join("")}</tbody></table>
    ${j.status !== "running" ? `<div class="actions"><a class="primary" href="/api/report/${esc(j.run_id)}"><button class="primary">Baixar relatório PDF</button></a><button class="ghost" id="back">Início</button></div>` : ""}`;
  if (j.status === "running") setTimeout(() => progress(job), 1500);
  else $("#back").onclick = home;
}

function error(e, replace = true) {
  const html = `<div class="notice err">${esc(e.message)}</div>`;
  if (replace) { app.innerHTML = `<h1>Erro</h1>${html}<button class="ghost" id="back">Voltar</button>`; $("#back").onclick = home; }
  else app.insertAdjacentHTML("afterbegin", html);
}

home().catch(error);
if (location.hash === "#diagnose") diagnose();
