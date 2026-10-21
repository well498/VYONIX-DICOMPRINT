/* VYONIX Reception — painel da recepção (sem bibliotecas externas; nenhum dado é inserido como HTML). */
"use strict";
(function () {
  const $ = (id) => document.getElementById(id);
  let me = null, csrf = "", meta = null, tab = "print", current = null, modality = "", timer = null;

  function el(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "class") e.className = v;
      else if (k === "on") for (const [ev, fn] of Object.entries(v)) e.addEventListener(ev, fn);
      else if (v !== null && v !== undefined && v !== false) e.setAttribute(k, v);
    }
    for (const k of kids.flat()) if (k !== null && k !== undefined) e.append(k instanceof Node ? k : String(k));
    return e;
  }
  const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random());
  const when = (iso) => { if (!iso) return "—"; const d = new Date(iso); return isNaN(d) ? iso : d.toLocaleString("pt-BR", {dateStyle: "short", timeStyle: "short"}); };
  const can = (p) => me && me.perms.includes(p);
  function toast(msg, err) { const t = $("toast"); t.textContent = msg; t.className = "toast" + (err ? " err" : ""); clearTimeout(t._h); t._h = setTimeout(() => t.classList.add("hidden"), 5000); }

  async function api(path, opts) {
    const o = Object.assign({headers: {}}, opts || {});
    if (o.body !== undefined) { o.method = o.method || "POST"; o.headers["Content-Type"] = "application/json"; o.headers["X-CSRF-Token"] = csrf; o.body = JSON.stringify(o.body); }
    const r = await fetch(path, Object.assign({credentials: "same-origin"}, o));
    let data = {};
    try { data = await r.json(); } catch (e) { /* vazio */ }
    if (r.status === 401) { showLogin(); throw Object.assign(new Error(data.error || "Sessão expirada"), {status: 401}); }
    if (!r.ok) throw Object.assign(new Error(data.error || ("Erro " + r.status)), {status: r.status, data});
    return data;
  }

  // ---------------------------------------------------------------- login
  function showLogin() { $("app").classList.add("hidden"); $("login").classList.remove("hidden"); clearInterval(timer); }
  $("login-form").addEventListener("submit", async (ev) => {
    ev.preventDefault(); $("login-error").textContent = "";
    try {
      const d = await api("/api/login", {body: {username: $("login-user").value, password: $("login-pass").value}});
      $("login-pass").value = ""; await start(d);
    } catch (e) { $("login-error").textContent = e.message; }
  });
  $("btn-logout").addEventListener("click", async () => { try { await api("/api/logout", {body: {}}); } catch (e) { /* */ } showLogin(); });
  $("btn-password").addEventListener("click", () => {
    const old = el("input", {type: "password"}), nw = el("input", {type: "password"});
    modal("Alterar senha", [el("label", {}, "Senha atual", old), el("label", {}, "Nova senha (8+ caracteres, letras e números)", nw)], async () => {
      await api("/api/password", {body: {old: old.value, new: nw.value}}); toast("Senha alterada.");
    });
  });

  async function start(d) {
    me = d; csrf = d.csrf;
    $("user-name").textContent = `${d.name} (${d.role_label})`;
    $("login").classList.add("hidden"); $("app").classList.remove("hidden");
    document.querySelectorAll("[data-perm]").forEach((b) => b.classList.toggle("hidden", !can(b.dataset.perm)));
    meta = await api("/api/meta");
    fillSelect($("f-print"), meta.print_states); fillSelect($("f-pickup"), meta.pickup_states);
    const rs = $("f-rule"); while (rs.options.length > 1) rs.remove(1);
    meta.rules.forEach((r) => rs.append(el("option", {value: r.id}, r.name)));
    const ln = $("license-notice"); ln.textContent = meta.license_notice || ""; ln.classList.toggle("hidden", !meta.license_notice);
    if (d.must_change) toast("Sua senha é provisória: altere-a em “Senha”.");
    search(); alerts();
    clearInterval(timer); timer = setInterval(() => { if (!document.hidden) { search(true); alerts(); } }, 15000);
  }
  function fillSelect(sel, map) { while (sel.options.length > 1) sel.remove(1); for (const [k, v] of Object.entries(map)) sel.append(el("option", {value: k}, v)); }

  // ---------------------------------------------------------------- abas
  document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => {
    tab = b.dataset.tab;
    document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === b));
    const list = tab === "print" || tab === "pickup";
    $("search").classList.toggle("hidden", !list); $("view-list").classList.toggle("hidden", !list);
    $("view-reports").classList.toggle("hidden", tab !== "reports"); $("view-alerts").classList.toggle("hidden", tab !== "alerts");
    if (!list) $("detail").classList.add("hidden");
    if (list) search(); if (tab === "alerts") alerts();
  }));

  // ---------------------------------------------------------------- pesquisa
  $("btn-search").addEventListener("click", () => search());
  $("f-q").addEventListener("keydown", (e) => { if (e.key === "Enter") search(); });
  async function search(quiet) {
    const p = new URLSearchParams();
    const add = (k, v) => { if (v) p.set(k, v); };
    add("q", $("f-q").value.trim()); add("rule", $("f-rule").value); add("from", $("f-from").value); add("to", $("f-to").value);
    add("print_state", $("f-print").value); add("pickup_state", $("f-pickup").value); add("modality", modality);
    try { render(await api("/api/exams?" + p)); } catch (e) { if (!quiet && e.status !== 401) toast(e.message, true); }
  }
  function render(d) {
    const chips = $("chips"); chips.replaceChildren();
    const all = el("button", {class: "chip" + (modality ? "" : " on"), on: {click: () => { modality = ""; search(); }}}, `Todas (${d.total})`);
    chips.append(all);
    Object.entries(d.by_modality).sort().forEach(([m, n]) => chips.append(el("button", {class: "chip" + (modality === m ? " on" : ""), on: {click: () => { modality = modality === m ? "" : m; search(); }}}, `${m} (${n})`)));
    const tb = $("exam-table").querySelector("tbody"); tb.replaceChildren();
    $("empty").classList.toggle("hidden", d.exams.length > 0);
    for (const x of d.exams) {
      const tr = el("tr", {class: current === x.id ? "sel" : "", on: {click: () => openExam(x.id)}},
        el("td", {}, when(x.first_received_at)), el("td", {}, x.patient_name || "—"), el("td", {}, x.patient_id || "—"),
        el("td", {}, [x.admission_id, x.accession].filter(Boolean).join(" / ") || "—"), el("td", {}, x.modality || "—"),
        el("td", {}, x.rule_name || "—"),
        el("td", {}, el("span", {class: "st st-" + x.print_state}, x.print_state_label), x.printed_count > 1 ? el("span", {class: "small muted"}, ` ${x.printed_count}×`) : null),
        el("td", {}, el("span", {class: "st st-" + x.pickup_state}, x.pickup_label)),
        el("td", {class: "actions-col"}, tab === "pickup" ? pickupButtons(x, true) : null));
      tb.append(tr);
    }
  }

  // ---------------------------------------------------------------- detalhe
  $("detail-close").addEventListener("click", () => { $("detail").classList.add("hidden"); current = null; search(true); });
  async function openExam(id) {
    current = id;
    let d; try { d = await api("/api/exams/" + id); } catch (e) { toast(e.message, true); return; }
    const x = d.exam; $("detail").classList.remove("hidden");
    $("d-title").textContent = x.patient_name || "Paciente não informado";
    const info = $("d-info"); info.replaceChildren();
    const row = (k, v) => info.append(el("div", {}, el("b", {}, k), v || "—"));
    row("ID do paciente", x.patient_id); row("Atendimento", x.admission_id); row("Accession Number", x.accession);
    row("Exame", [x.modality, x.study_desc].filter(Boolean).join(" — ")); row("Data do exame", x.study_date);
    row("Regra / origem", `${x.rule_name || "sem regra"} · ${x.calling_ae || "—"} → ${x.called_ae || "—"}`);
    row("Imagens recebidas", `${x.instances} (${d.series.length} série(s)) em ${when(x.first_received_at)}`);
    info.append(el("div", {}, el("b", {}, "Impressão"), el("span", {class: "st st-" + x.print_state}, x.print_state_label)));
    info.append(el("div", {}, el("b", {}, "Retirada"), el("span", {class: "st st-" + x.pickup_state}, x.pickup_label),
      x.delivered_to ? ` — entregue a ${x.delivered_to} em ${when(x.pickup_at)}` : ""));
    if (d.last_print) info.append(el("div", {class: "warnbox"}, `Já impresso ${d.last_print.count}× — última em ${when(d.last_print.at)} (${d.last_print.printer || "impressora padrão"}, ${d.last_print.copies} cópia(s), ${d.last_print.by}).`));
    const busy = ["receiving", "awaiting"].includes(x.print_state);
    $("btn-print").disabled = busy; $("btn-print-now").disabled = busy;
    $("btn-print").onclick = () => doPrint(x, false); $("btn-print-now").onclick = () => printNow(x); $("btn-preview").onclick = () => preview(x);
    const pb = $("pickup-buttons"); pb.replaceChildren(pickupButtons(x, false));
    const ht = $("d-history").querySelector("tbody"); ht.replaceChildren();
    for (const h of d.history) ht.append(el("tr", {}, el("td", {}, when(h.at)), el("td", {}, h.actor.replace("usuario:", "")), el("td", {}, label(h.action)), el("td", {}, detailText(h.detail))));
    const jt = $("d-jobs").querySelector("tbody"); jt.replaceChildren();
    for (const j of d.jobs) jt.append(el("tr", {}, el("td", {}, "#" + j.id), el("td", {}, j.state_label), el("td", {}, j.printer || "padrão"), el("td", {}, j.copies), el("td", {}, j.page_count || "—"), el("td", {}, (j.requested_by || "automática").replace("usuario:", ""))));
    document.querySelectorAll("#exam-table tbody tr").forEach((tr) => tr.classList.remove("sel"));
  }
  const ACTIONS = {print: "Impressão solicitada", print_now: "IMPRIMIR AGORA", reprint: "Reimpressão (duplicada)", view: "Consulta"};
  function label(a) { if (a.startsWith("pickup.")) return "Retirada: " + (meta.pickup_states[a.slice(7)] || a); return ACTIONS[a] || a; }
  function detailText(s) { if (!s) return ""; try { const o = JSON.parse(s); return Object.entries(o).filter(([, v]) => v !== null && v !== false && v !== "").map(([k, v]) => `${k}: ${v}`).join("; "); } catch (e) { return s; } }

  function pickupButtons(x, compact) {
    const wrap = el("div", {class: "buttons"});
    const b = (state, text, cls) => wrap.append(el("button", {class: cls || "", on: {click: (ev) => { ev.stopPropagation(); setPickup(x, state); }}}, text));
    if (x.pickup_state !== "entregue") {
      if (!compact || x.pickup_state === "aguardando_preparacao") b("em_preparacao", "Em preparação");
      if (x.pickup_state !== "pronto") b("pronto", "Pronto p/ retirada");
      b("entregue", "Entregar…", "primary");
      if (!compact) b("entrega_pendente", "Entrega pendente");
    }
    if (can("pickup_cancel") && (x.pickup_state === "entregue" || !compact)) b("entrega_cancelada", "Cancelar entrega", "danger");
    return wrap;
  }
  async function setPickup(x, state) {
    const key = uuid();
    const send = async (extra) => {
      await api(`/api/exams/${x.id}/pickup`, {body: Object.assign({state, request_key: key}, extra)});
      toast(`${x.patient_name || "Exame"}: ${meta.pickup_states[state]}.`); search(true); if (current === x.id) openExam(x.id);
    };
    if (state === "entregue" || state === "entrega_cancelada" || state === "entrega_pendente") {
      const who = el("input", {placeholder: state === "entregue" ? "Nome e/ou documento de quem retirou" : ""});
      const note = el("input", {placeholder: "Observação (opcional)"});
      const body = [el("p", {}, `${x.patient_name || "Exame"} — ${x.modality || ""}`)];
      if (state === "entregue") body.push(el("label", {}, "Entregue a *", who));
      body.push(el("label", {}, "Observação", note));
      modal(meta.pickup_states[state], body, () => send({delivered_to: who.value, note: note.value}));
    } else {
      try { await send({}); } catch (e) { toast(e.message, true); }
    }
  }

  async function doPrint(x, now, extra) {
    const key = (extra && extra.request_key) || uuid();
    const btn = now ? $("btn-print-now") : $("btn-print");
    btn.disabled = true;
    try {
      const body = Object.assign({request_key: key}, extra || {});
      const r = await api(`/api/exams/${x.id}/${now ? "print-now" : "print"}`, {body});
      toast(r.replayed ? "Pedido já registrado (clique repetido ignorado)." : `Enviado para impressão: trabalho(s) #${r.jobs.join(", #")}.`);
      openExam(x.id); search(true);
    } catch (e) {
      if (e.status === 409 && e.data && e.data.duplicate) {
        if (!can("reprint")) { toast(e.message + " A reimpressão exige um supervisor.", true); return; }
        const reason = el("input", {placeholder: "Motivo da reimpressão"});
        modal("Impressão duplicada", [el("div", {class: "warnbox"}, e.message), el("label", {}, "Motivo *", reason)],
          () => doPrint(x, now, Object.assign({}, extra || {}, {request_key: key, confirm_duplicate: true, reason: reason.value})));
      } else toast(e.message, true);
    } finally { btn.disabled = false; }
  }
  async function printNow(x) {
    let printers = [];
    try { printers = (await api("/api/printers")).printers; } catch (e) { /* */ }
    const sel = el("select", {}, el("option", {value: ""}, "Impressora da regra"), printers.map((p) => el("option", {value: p}, p)));
    const copies = el("input", {type: "number", min: 1, max: 99, value: 1});
    modal("IMPRIMIR AGORA — impressão excepcional", [el("p", {class: "muted"}, "Imprime este exame agora, sem alterar a configuração permanente da regra."),
      el("label", {}, "Impressora", sel), el("label", {}, "Cópias", copies)],
      () => doPrint(x, true, {printer: sel.value, copies: parseInt(copies.value, 10) || 1}));
  }
  async function preview(x) {
    modal("Composição das páginas", [el("p", {class: "muted"}, "Montando a pré-visualização…")], null);
    try {
      const d = await api(`/api/exams/${x.id}/preview`);
      const body = $("m-body"); body.replaceChildren();
      if (d.warnings.length) body.append(el("div", {class: "warnbox"}, d.warnings.join("; ")));
      const box = el("div", {class: "pages"}); d.pages.forEach((src) => box.append(el("img", {src, alt: "Página"})));
      body.append(d.pages.length ? box : el("p", {}, "Sem páginas para mostrar."));
    } catch (e) { $("m-body").replaceChildren(el("p", {class: "error"}, e.message)); }
  }

  // ---------------------------------------------------------------- modal
  function modal(title, body, onOk) {
    $("m-title").textContent = title; $("m-body").replaceChildren(...body);
    $("m-ok").classList.toggle("hidden", !onOk); $("m-cancel").textContent = onOk ? "Cancelar" : "Fechar";
    $("modal").classList.remove("hidden");
    $("m-cancel").onclick = () => $("modal").classList.add("hidden");
    $("m-ok").onclick = async () => {
      $("m-ok").disabled = true;
      try { await onOk(); $("modal").classList.add("hidden"); } catch (e) { toast(e.message, true); } finally { $("m-ok").disabled = false; }
    };
  }

  // ---------------------------------------------------------------- alertas e relatórios
  async function alerts() {
    try {
      const d = await api("/api/alerts");
      const n = d.alerts.filter((a) => a.level !== "info").length;
      $("alert-count").textContent = n; $("alert-count").classList.toggle("hidden", n === 0);
      const ul = $("alert-list"); ul.replaceChildren();
      if (!d.alerts.length) ul.append(el("li", {class: "al-info"}, "Nenhum alerta."));
      d.alerts.forEach((a) => ul.append(el("li", {class: "al-" + a.level, on: a.exam_id ? {click: () => { document.querySelector('[data-tab="print"]').click(); openExam(a.exam_id); }} : {}}, a.text)));
    } catch (e) { /* silencioso */ }
  }
  function reportQuery(fmt) { const p = new URLSearchParams({group: $("r-group").value}); if ($("r-from").value) p.set("from", $("r-from").value); if ($("r-to").value) p.set("to", $("r-to").value); if (fmt) p.set("format", fmt); return "/api/reports?" + p; }
  $("btn-report").addEventListener("click", async () => {
    try {
      const d = await api(reportQuery());
      const tb = $("r-table").querySelector("tbody"); tb.replaceChildren();
      d.rows.forEach((r) => tb.append(el("tr", {}, el("td", {}, String(r.chave).replace("usuario:", "")), el("td", {}, r.exames), el("td", {}, r.trabalhos), el("td", {}, r.folhas_enviadas), el("td", {}, r.folhas_confirmadas), el("td", {}, r.reimpressoes), el("td", {}, r.falhas))));
      $("r-saved").textContent = `Economia estimada pela impressão sob demanda: ${d.saved_estimate.sheets} folha(s) em ${d.saved_estimate.exams} exame(s) não impresso(s) (estimativa).`;
      $("r-note").textContent = d.note;
    } catch (e) { toast(e.message, true); }
  });
  $("btn-report-csv").addEventListener("click", () => { window.location.href = reportQuery("csv"); });

  // ---------------------------------------------------------------- início
  api("/api/me").then(start).catch(() => showLogin());
})();
