import { useState, type FormEvent } from "react";
import { del, fmtDate, get, patch, post, put, type Me } from "../api";
import { Field, Notice, Page, useAction, useLoad } from "../ui";

type Status = { code: "ok" | "never" | "idle" | "error" | "disabled"; label: string };
type Node = {
  id: string; ae_title: string; host: string | null; port: number | null; description: string | null;
  name: string | null; manufacturer: string | null; model: string | null; modality: string | null;
  site_id: string | null; site_name: string | null; can_store: boolean; can_query: boolean; can_receive: boolean;
  enabled: boolean; last_seen_at: string | null; last_echo_at: string | null; last_echo_ok: boolean | null;
  last_error: string | null; last_error_at: string | null; status: Status; row_version: number;
};
type Listing = { nodes: Node[]; policy: "any" | "registered"; held: number;
  qr: { port: number | null; ae_title: string; store: { port: number; ae_title: string } } };
type Ev = { id: string; first_at: string; last_at: string; direction: "in" | "out"; service: string; outcome: string;
  calling_ae: string | null; called_ae: string | null; address: string | null; detail: string | null; count: number };
type HoldGroup = { remote_aet: string | null; remote_ip: string | null; called_aet: string | null; reason: string;
  instances: number; first_at: string; last_at: string };
type Site = { id: string; name: string };

const SERVICE: Record<string, string> = { association: "Associação", echo: "Teste C-ECHO", store: "Envio de imagens",
  find: "Consulta", move: "Recuperação (C-MOVE)", get: "Recuperação (C-GET)", mwl: "Worklist", mpps: "MPPS" };
const OUTCOME: Record<string, string> = { accepted: "Aceita", rejected: "Recusada", ok: "Sucesso", failed: "Falha",
  held: "Retida" };
const STATUS_TONE: Record<Status["code"], string> = { ok: "dot-ok", never: "dot-off", idle: "dot-warn", error: "dot-bad",
  disabled: "dot-off" };

type Form = { ae: string; name: string; manufacturer: string; model: string; modality: string; site: string;
  host: string; port: string; description: string; store: boolean; query: boolean; receive: boolean; enabled: boolean };
const EMPTY: Form = { ae: "", name: "", manufacturer: "", model: "", modality: "", site: "", host: "", port: "",
  description: "", store: true, query: true, receive: false, enabled: true };

function toForm(n: Node): Form {
  return { ae: n.ae_title, name: n.name ?? "", manufacturer: n.manufacturer ?? "", model: n.model ?? "",
    modality: n.modality ?? "", site: n.site_id ?? "", host: n.host ?? "", port: n.port ? String(n.port) : "",
    description: n.description ?? "", store: n.can_store, query: n.can_query, receive: n.can_receive, enabled: n.enabled };
}

function body(f: Form) {
  return { ae_title: f.ae, name: f.name || null, manufacturer: f.manufacturer || null, model: f.model || null,
    modality: f.modality || null, site_id: f.site || null, host: f.host || null, port: f.port ? Number(f.port) : null,
    description: f.description || null, can_store: f.store, can_query: f.query, can_receive: f.receive, enabled: f.enabled };
}

export function StationsPage({ me }: { me: Me }) {
  const canSettings = me.permissions.includes("core.settings.manage");
  const list = useLoad(() => get<Listing>("/pacs/nodes"), []);
  const sites = useLoad(() => get<Site[]>("/sites").catch(() => [] as Site[]), []);
  const holds = useLoad(() => get<{ groups: HoldGroup[]; total: number }>("/pacs/holds"), []);
  const problems = useLoad(() => get<{ items: Ev[] }>("/pacs/dicom-events?outcome=problems&limit=20"), []);
  const [editing, setEditing] = useState<{ id: string | null; rv?: number; form: Form } | null>(null);
  const [open, setOpen] = useState<Node | null>(null);
  const [discard, setDiscard] = useState<{ aet: string | null; note: string } | null>(null);
  const act = useAction();

  async function reloadAll() { await Promise.all([list.reload(), holds.reload(), problems.reload()]); }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!editing) return;
    const ok = await act.run(async () => {
      if (editing.id) await patch(`/pacs/nodes/${editing.id}`, { ...body(editing.form), row_version: editing.rv });
      else await post("/pacs/nodes", body(editing.form));
      await reloadAll();
    }, editing.id ? "Equipamento atualizado." : "Equipamento cadastrado.");
    if (ok) setEditing(null);
  }

  async function setPolicy(value: "any" | "registered") {
    await act.run(async () => {
      await put("/settings/pacs/reception", { value: { store_policy: value },
        reason: value === "registered" ? "Recepção só de equipamentos cadastrados" : "Recepção de qualquer equipamento" });
      await list.reload();
    }, value === "registered" ? "Agora só equipamentos cadastrados com “Envia imagens” são aceitos." :
      "Recepção liberada para qualquer equipamento.");
  }

  const d = list.data;
  const f = editing?.form;
  const setF = (p: Partial<Form>) => editing && setEditing({ ...editing, form: { ...editing.form, ...p } });
  const nodes = d?.nodes ?? [];
  return (
    <Page title="Nós DICOM"
      intro="Equipamentos, estações e PACS que conversam com o VYONIX: quem envia imagens, quem consulta e para onde o PACS envia estudos."
      actions={!editing ? <button className="primary" onClick={() => setEditing({ id: null, form: EMPTY })}>Cadastrar equipamento</button> : undefined}>
      {act.view}
      <Notice kind="error">{list.error}</Notice>
      {d && (
        <Notice kind="info">Configure nos equipamentos — <strong>envio de imagens</strong>: AE Title <strong>{d.qr.store.ae_title}</strong>, porta <strong>{d.qr.store.port}</strong>
          {d.qr.port ? <> · <strong>consulta e worklist</strong>: AE Title <strong>{d.qr.ae_title}</strong>, porta <strong>{d.qr.port}</strong></> : null}
          {" "}· endereço deste servidor.</Notice>
      )}

      {d && (
        <div className="panel" role="group" aria-label="Recepção de imagens">
          <strong>Recepção de imagens (C-STORE)</strong>
          <label className="check"><input type="radio" name="policy" checked={d.policy === "any"} disabled={!canSettings || act.busy}
            onChange={() => void setPolicy("any")} /> Aceitar de qualquer equipamento</label>
          <label className="check"><input type="radio" name="policy" checked={d.policy === "registered"} disabled={!canSettings || act.busy}
            onChange={() => void setPolicy("registered")} /> Só de equipamentos cadastrados (os demais ficam retidos para sua decisão; nada é apagado)</label>
        </div>
      )}

      {editing && f && (
        <form className="panel" aria-label={editing.id ? `Editar ${f.ae}` : "Cadastrar equipamento"} onSubmit={submit}>
          <div className="grid2">
            <Field label="Identificação" hint="Como a equipe reconhece o equipamento (ex.: Tomógrafo sala 1)">
              <input maxLength={120} value={f.name} onChange={(e) => setF({ name: e.target.value })} /></Field>
            <Field label="AE Title" hint="Até 16 caracteres, igual ao configurado no equipamento">
              <input required maxLength={16} value={f.ae} onChange={(e) => setF({ ae: e.target.value.toUpperCase() })} /></Field>
            <Field label="Fabricante"><input maxLength={80} value={f.manufacturer} onChange={(e) => setF({ manufacturer: e.target.value })} /></Field>
            <Field label="Modelo"><input maxLength={80} value={f.model} onChange={(e) => setF({ model: e.target.value })} /></Field>
            <Field label="Modalidade" hint="Código DICOM: CT, MR, CR, DX, US, MG…">
              <input maxLength={8} value={f.modality} onChange={(e) => setF({ modality: e.target.value.toUpperCase() })} /></Field>
            <Field label="Unidade">
              <select value={f.site} onChange={(e) => setF({ site: e.target.value })}>
                <option value="">Toda a instituição</option>
                {(sites.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select></Field>
            <Field label="Endereço (IP ou nome)" hint="Se informado, conexões de outro endereço são recusadas">
              <input maxLength={64} value={f.host} onChange={(e) => setF({ host: e.target.value })} /></Field>
            <Field label="Porta DICOM" hint="Necessária para receber estudos e para o teste de conexão">
              <input type="number" min={1} max={65535} value={f.port} onChange={(e) => setF({ port: e.target.value })} /></Field>
            <Field label="Observação"><input maxLength={200} value={f.description} onChange={(e) => setF({ description: e.target.value })} /></Field>
          </div>
          <fieldset className="plain">
            <legend>Serviços permitidos</legend>
            <label className="check"><input type="checkbox" checked={f.store} onChange={(e) => setF({ store: e.target.checked })} /> Envia imagens ao PACS (C-STORE)</label>
            <label className="check"><input type="checkbox" checked={f.query} onChange={(e) => setF({ query: e.target.checked })} /> Consulta estudos e worklist (C-FIND, MWL, MPPS)</label>
            <label className="check"><input type="checkbox" checked={f.receive} onChange={(e) => setF({ receive: e.target.checked })} /> Recebe estudos do PACS (C-MOVE, C-GET)</label>
            <label className="check"><input type="checkbox" checked={f.enabled} onChange={(e) => setF({ enabled: e.target.checked })} /> Equipamento ativo</label>
          </fieldset>
          <div className="row-actions">
            <button className="primary" disabled={act.busy}>Salvar equipamento</button>
            <button type="button" className="link" onClick={() => setEditing(null)}>Cancelar</button>
          </div>
        </form>
      )}

      {(holds.data?.total ?? 0) > 0 && (
        <section className="section" aria-label="Recepções retidas">
          <h2>Imagens retidas de equipamentos não autorizados <span className="count count-warn">{holds.data!.total}</span></h2>
          <p className="intro">Ficam guardadas, sem acesso, até você autorizar (entram no PACS) ou descartar.</p>
          <div className="table-wrap"><table>
            <thead><tr><th>AE Title</th><th>Endereço</th><th>Motivo</th><th>Imagens</th><th>Última</th><th>Ações</th></tr></thead>
            <tbody>{holds.data!.groups.map((g) => (
              <tr key={`${g.remote_aet}-${g.remote_ip}-${g.reason}`}>
                <td className="nowrap">{g.remote_aet ?? "—"}</td><td>{g.remote_ip ?? "—"}</td><td>{g.reason}</td>
                <td>{g.instances}</td><td className="nowrap">{fmtDate(g.last_at)}</td>
                <td className="actions">
                  {g.reason === "AE Title não cadastrado" && g.remote_aet && (
                    <button className="link" onClick={() => setEditing({ id: null, form: { ...EMPTY, ae: g.remote_aet!, host: g.remote_ip ?? "" } })}>Cadastrar equipamento</button>)}
                  <button className="link" disabled={act.busy} onClick={() => void act.run(async () => {
                    await post("/pacs/holds/decide", { remote_aet: g.remote_aet, decision: "release" }); await reloadAll();
                  }, `Imagens de ${g.remote_aet ?? "origem sem AE"} autorizadas e indexadas.`)}>Autorizar imagens</button>
                  <button className="link" onClick={() => setDiscard({ aet: g.remote_aet, note: "" })}>Descartar</button>
                </td>
              </tr>))}
            </tbody>
          </table></div>
          {discard && (
            <form className="panel" aria-label="Descartar imagens retidas" onSubmit={(e) => { e.preventDefault(); void act.run(async () => {
              await post("/pacs/holds/decide", { remote_aet: discard.aet, decision: "discard", note: discard.note });
              setDiscard(null); await reloadAll();
            }, "Imagens descartadas (registrado na auditoria)."); }}>
              <Field label="Motivo do descarte" hint="Obrigatório; fica na auditoria">
                <input required maxLength={300} value={discard.note} onChange={(e) => setDiscard({ ...discard, note: e.target.value })} /></Field>
              <div className="row-actions"><button className="danger" disabled={act.busy}>Descartar imagens de {discard.aet ?? "origem sem AE"}</button>
                <button type="button" className="link" onClick={() => setDiscard(null)}>Cancelar</button></div>
            </form>
          )}
        </section>
      )}

      <div className="table-wrap">
        <table>
          <thead><tr><th>Equipamento</th><th>Modalidade</th><th>Unidade</th><th>Endereço</th><th>Serviços</th><th>Situação</th><th>Ações</th></tr></thead>
          <tbody>
            {nodes.map((n) => (
              <tr key={n.id}>
                <td><strong>{n.name ?? n.ae_title}</strong>{n.name && <div className="muted">{n.ae_title}</div>}
                  {(n.manufacturer || n.model) && <div className="muted">{[n.manufacturer, n.model].filter(Boolean).join(" · ")}</div>}</td>
                <td>{n.modality ?? "—"}</td><td>{n.site_name ?? "Toda a instituição"}</td>
                <td className="nowrap">{n.host ? `${n.host}${n.port ? `:${n.port}` : ""}` : "qualquer"}</td>
                <td><span className="tags">
                  {n.can_store && <span className="pill">Envia imagens</span>}
                  {n.can_query && <span className="pill">Consulta</span>}
                  {n.can_receive && <span className="pill">Recebe estudos</span>}</span></td>
                <td className="nowrap"><span className={`dot ${STATUS_TONE[n.status.code]}`} aria-hidden="true" /> {n.status.label}</td>
                <td className="actions"><button className="link" aria-label={`Detalhes ${n.ae_title}`} onClick={() => setOpen(n)}>Detalhes</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        {!list.loading && !list.error && nodes.length === 0 && <p className="empty">Nenhum equipamento cadastrado.</p>}
      </div>

      <ForwardRules nodes={nodes} onChanged={reloadAll} />

      {(problems.data?.items.length ?? 0) > 0 && (
        <section className="section" aria-label="Conexões recusadas e falhas">
          <h2>Conexões recusadas e falhas recentes</h2>
          <EventTable items={problems.data!.items} />
        </section>
      )}

      {open && <NodeSheet node={nodes.find((x) => x.id === open.id) ?? open} onClose={() => setOpen(null)}
        onEdit={(n) => { setOpen(null); setEditing({ id: n.id, rv: n.row_version, form: toForm(n) }); }}
        onChanged={reloadAll} />}
    </Page>
  );
}

type Rule = { id: string; name: string; enabled: boolean; source: string | null; modality: string | null;
  destination_node_id: string; destination: string | null };
type Job = { id: string; status: "queued" | "done" | "failed" | "cancelled"; attempts: number; next_attempt_at: string;
  instances: number; sent: number; integrity_failures: number; last_error: string | null; done_at: string | null;
  requested_by: string; destination: string | null; accession: string | null; created_at: string };
const JOB: Record<Job["status"], string> = { queued: "Na fila", done: "Enviado", failed: "Falhou", cancelled: "Cancelado" };

/** Regras de encaminhamento automático (roteamento) e envios recentes. */
function ForwardRules({ nodes, onChanged }: { nodes: Node[]; onChanged: () => Promise<void> }) {
  const data = useLoad(() => get<{ items: Rule[]; jobs: Job[] }>("/pacs/forward-rules"), [nodes.length]);
  const dests = nodes.filter((n) => n.can_receive && n.host && n.port);
  const [f, setF] = useState<{ name: string; source: string; modality: string; dest: string } | null>(null);
  const act = useAction();
  async function save(e: FormEvent) {
    e.preventDefault();
    if (!f) return;
    if (await act.run(async () => {
      await post("/pacs/forward-rules", { name: f.name, destination_node_id: f.dest, source: f.source || null, modality: f.modality || null });
      await data.reload();
    }, "Regra de encaminhamento criada.")) setF(null);
  }
  const d = data.data;
  return (
    <section className="section" aria-label="Encaminhamento de estudos">
      <div className="row-actions"><h2>Encaminhamento de estudos</h2>
        {!f && <button disabled={!dests.length} title={!dests.length ? "Cadastre um nó com “Recebe estudos”, endereço e porta" : undefined}
          onClick={() => setF({ name: "", source: "", modality: "", dest: dests[0]?.id ?? "" })}>Nova regra</button>}</div>
      <p className="intro">Envia automaticamente (C-STORE) os estudos recebidos para outro PACS ou estação, depois de terminada a recepção. Falhas são repetidas em 5 min, 15 min, 1 h, 3 h e 12 h.</p>
      {act.view}
      <Notice kind="error">{data.error}</Notice>
      {f && (
        <form className="panel" aria-label="Nova regra de encaminhamento" onSubmit={save}>
          <div className="grid2">
            <Field label="Nome da regra"><input required maxLength={120} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
            <Field label="Destino"><select value={f.dest} onChange={(e) => setF({ ...f, dest: e.target.value })}>
              {dests.map((n) => <option key={n.id} value={n.id}>{n.name ?? n.ae_title} ({n.ae_title})</option>)}</select></Field>
            <Field label="Origem (estação ou AE)" hint="Vazio = qualquer origem"><input maxLength={16} value={f.source} onChange={(e) => setF({ ...f, source: e.target.value.toUpperCase() })} /></Field>
            <Field label="Modalidade do estudo" hint="Vazio = qualquer modalidade"><input maxLength={8} value={f.modality} onChange={(e) => setF({ ...f, modality: e.target.value.toUpperCase() })} /></Field>
          </div>
          <div className="row-actions"><button className="primary" disabled={act.busy || !f.dest}>Salvar regra</button>
            <button type="button" className="link" onClick={() => setF(null)}>Cancelar</button></div>
        </form>)}
      {d && d.items.length === 0 && !f && <p className="empty">Nenhuma regra de encaminhamento.</p>}
      {d && d.items.length > 0 && (
        <div className="table-wrap"><table>
          <thead><tr><th>Regra</th><th>Origem</th><th>Modalidade</th><th>Destino</th><th>Situação</th><th>Ações</th></tr></thead>
          <tbody>{d.items.map((r) => (
            <tr key={r.id}><td>{r.name}</td><td>{r.source ?? "qualquer"}</td><td>{r.modality ?? "qualquer"}</td><td>{r.destination ?? "—"}</td>
              <td>{r.enabled ? "Ativa" : "Pausada"}</td>
              <td className="actions">
                <button className="link" disabled={act.busy} onClick={() => void act.run(async () => {
                  await put(`/pacs/forward-rules/${r.id}`, { name: r.name, destination_node_id: r.destination_node_id, source: r.source, modality: r.modality, enabled: !r.enabled });
                  await data.reload(); await onChanged();
                }, r.enabled ? "Regra pausada." : "Regra ativada.")}>{r.enabled ? "Pausar" : "Ativar"}</button>
                <button className="link danger" disabled={act.busy} onClick={() => void act.run(async () => {
                  await del(`/pacs/forward-rules/${r.id}`); await data.reload();
                }, "Regra removida.")}>Remover</button></td></tr>))}
          </tbody>
        </table></div>)}
      {d && d.jobs.length > 0 && <>
        <h3 className="section">Envios recentes</h3>
        <div className="table-wrap"><table>
          <thead><tr><th>Criado</th><th>Destino</th><th>Origem do pedido</th><th>Situação</th><th>Imagens</th><th>Detalhe</th><th>Ações</th></tr></thead>
          <tbody>{d.jobs.map((j) => (
            <tr key={j.id}><td className="nowrap">{fmtDate(j.created_at)}</td><td>{j.destination ?? "—"}</td><td>{j.requested_by}</td>
              <td><span className={`pill${j.status === "failed" ? " pill-warn" : ""}`}>{JOB[j.status]}</span>
                {j.status === "queued" && j.attempts > 0 && <div className="muted">tentativa {j.attempts + 1} às {fmtDate(j.next_attempt_at)}</div>}</td>
              <td>{j.sent}/{j.instances || "—"}{j.integrity_failures ? ` (${j.integrity_failures} com integridade violada)` : ""}</td>
              <td>{j.last_error ?? "—"}</td>
              <td className="actions">{j.status === "failed" && <button className="link" disabled={act.busy} onClick={() => void act.run(async () => {
                await post(`/pacs/forward-jobs/${j.id}/retry`); await data.reload();
              }, "Envio reagendado.")}>Reenviar</button>}</td></tr>))}
          </tbody>
        </table></div></>}
    </section>
  );
}

function EventTable({ items }: { items: Ev[] }) {
  return (
    <div className="table-wrap"><table>
      <thead><tr><th>Quando</th><th>Sentido</th><th>Serviço</th><th>Resultado</th><th>Origem → destino</th><th>Detalhe</th></tr></thead>
      <tbody>{items.map((e) => (
        <tr key={e.id}>
          <td className="nowrap">{fmtDate(e.last_at)}{e.count > 1 && <div className="muted">{e.count}× desde {fmtDate(e.first_at)}</div>}</td>
          <td>{e.direction === "in" ? "Recebida" : "Enviada"}</td><td>{SERVICE[e.service] ?? e.service}</td>
          <td><span className={`pill${["rejected", "failed", "held"].includes(e.outcome) ? " pill-warn" : ""}`}>{OUTCOME[e.outcome] ?? e.outcome}</span></td>
          <td className="nowrap">{e.calling_ae ?? "?"} → {e.called_ae ?? "?"}{e.address && <div className="muted">{e.address}</div>}</td>
          <td>{e.detail ?? "—"}</td>
        </tr>))}
      </tbody>
    </table></div>
  );
}

function NodeSheet({ node, onClose, onEdit, onChanged }:
  { node: Node; onClose: () => void; onEdit: (n: Node) => void; onChanged: () => Promise<void> }) {
  const events = useLoad(() => get<{ items: Ev[] }>(`/pacs/nodes/${node.id}/events`), [node.id, node.row_version]);
  const act = useAction();
  const [confirmDel, setConfirmDel] = useState(false);
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <section className="sheet sheet-wide" role="dialog" aria-modal="true" aria-label={`Equipamento ${node.ae_title}`} onClick={(e) => e.stopPropagation()}>
        <button type="button" className="sheet-close link" onClick={onClose}>Fechar</button>
        <header className="sheet-head">
          <h2>{node.name ?? node.ae_title}</h2>
          <p>{node.ae_title}{node.modality ? ` · ${node.modality}` : ""}{node.site_name ? ` · ${node.site_name}` : ""}</p>
          <p className="muted">{[node.manufacturer, node.model].filter(Boolean).join(" · ") || "Fabricante e modelo não informados"}</p>
          <div className="sheet-tags"><span className="pill"><span className={`dot ${STATUS_TONE[node.status.code]}`} aria-hidden="true" /> {node.status.label}</span></div>
        </header>
        {act.view}
        <dl className="facts">
          <dt>Endereço</dt><dd>{node.host ? `${node.host}${node.port ? `:${node.port}` : ""}` : "qualquer (sem restrição de endereço)"}</dd>
          <dt>Último contato</dt><dd>{node.last_seen_at ? fmtDate(node.last_seen_at) : "nenhum"}</dd>
          <dt>Último teste</dt><dd>{node.last_echo_at ? `${fmtDate(node.last_echo_at)} — ${node.last_echo_ok ? "sucesso" : "falha"}` : "nunca testado"}</dd>
          {node.last_error && <><dt>Último erro</dt><dd>{node.last_error}{node.last_error_at ? ` (${fmtDate(node.last_error_at)})` : ""}</dd></>}
        </dl>
        <div className="row-actions">
          <button className="primary" disabled={act.busy || !node.host || !node.port} title={!node.host || !node.port ? "Informe endereço e porta" : undefined}
            onClick={() => void act.run(async () => {
              const r = await post<{ ok: boolean; ms: number; detail: string }>(`/pacs/nodes/${node.id}/echo`);
              await onChanged(); await events.reload();
              if (!r.ok) throw new Error(r.detail);
              act.setMsg({ kind: "ok", text: `${r.detail} (${r.ms} ms)` });
            })}>Testar conexão (C-ECHO)</button>
          <button disabled={act.busy} onClick={() => onEdit(node)}>Editar</button>
          <button disabled={act.busy} onClick={() => void act.run(async () => {
            await patch(`/pacs/nodes/${node.id}`, { enabled: !node.enabled, row_version: node.row_version }); await onChanged();
          }, node.enabled ? "Equipamento desativado." : "Equipamento ativado.")}>{node.enabled ? "Desativar" : "Ativar"}</button>
          {!confirmDel ? <button className="link" onClick={() => setConfirmDel(true)}>Remover</button> :
            <button className="danger" disabled={act.busy} onClick={() => void act.run(async () => {
              await del(`/pacs/nodes/${node.id}`); await onChanged(); onClose();
            })}>Confirmar remoção de {node.ae_title}</button>}
        </div>
        <h3 className="section">Histórico de conexões</h3>
        <Notice kind="error">{events.error}</Notice>
        {(events.data?.items.length ?? 0) > 0 ? <EventTable items={events.data!.items} /> :
          !events.loading && <p className="empty">Nenhuma conexão registrada ainda.</p>}
      </section>
    </div>
  );
}
