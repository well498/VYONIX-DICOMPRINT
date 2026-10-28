import { useState, type FormEvent } from "react";
import { fmtDate, get, post, put, upload, type Me } from "../api";
import { Field, Notice, Page, useAction, useLoad } from "../ui";
import { BrandingPanel } from "./branding";
import { MySignaturePanel, PhysiciansPanel } from "./physicians";

type Row = { study_id: string; study_instance_uid: string; accession: string | null; modality: string | null;
  study_date: string | null; description: string | null; patient_name: string | null; report_id: string | null;
  report_status: "pending" | "draft" | "final"; critical: boolean };
type Version = { version: number; kind: "final" | "addendum"; body: string; critical: boolean; signed_by: string;
  signed_at: string; sha256: string };
type Report = { id: string; study_id: string; study_instance_uid: string | null; status: "draft" | "final"; body: string;
  critical: boolean; critical_note: string | null; author: string; version: number; finalized_by: string | null;
  finalized_at: string | null; row_version: number; versions: Version[] };
type Alert = { id: string; report_id: string; version: number; note: string | null; created_at: string;
  patient_name: string | null; accession: string | null; modality: string | null; requester: string | null;
  signed_by: string | null };
type Template = { id: string; name: string; modality: string | null; body: string; active: boolean };

const STATUS: Record<string, string> = { pending: "Sem laudo", draft: "Rascunho", final: "Liberado" };

function day(d: string | null) { return d ? fmtDate(d + "T12:00:00", false) : "—"; }

export function ReportsPage({ me }: { me: Me }) {
  const can = (p: string) => me.permissions.includes(p);
  const [filters, setFilters] = useState({ status: "pending", modality: "" });
  const [query, setQuery] = useState(filters);
  const [open, setOpen] = useState<{ row: Row; report: Report | null } | null>(null);
  const [showTemplates, setShowTemplates] = useState(false);
  const [tick, setTick] = useState(0);
  const [showPhysicians, setShowPhysicians] = useState(false);
  const [showBranding, setShowBranding] = useState(false);
  const [showSignature, setShowSignature] = useState(false);
  const act = useAction();

  const list = useLoad(async () => {
    const q = new URLSearchParams();
    if (query.status !== "all") q.set("status", query.status);
    if (query.modality) q.set("modality", query.modality.toUpperCase());
    return (await get<{ items: Row[] }>(`/report/worklist?${q}`)).items;
  }, [query]);

  async function openRow(row: Row) {
    await act.run(async () => {
      const report = row.report_id ? await get<Report>(`/report/reports/${row.report_id}`) : null;
      setOpen({ row, report });
    });
  }

  return (
    <Page title="Laudos"
      intro="Laudos dos estudos de imagem: rascunho a partir de modelos, liberação com confirmação de senha e adendos. Não é assinatura digital ICP-Brasil. Não liberado para uso clínico."
      actions={<>
        {can("report.sign") && <button onClick={() => setShowSignature(!showSignature)}>
          {showSignature ? "Fechar assinatura" : "Minha assinatura"}</button>}
        {can("report.branding.manage") && <button onClick={() => setShowBranding(!showBranding)}>
          {showBranding ? "Fechar identidade" : "Identidade visual"}</button>}
        {can("report.physicians.manage") && <button onClick={() => setShowPhysicians(!showPhysicians)}>
          {showPhysicians ? "Fechar médicos" : "Médicos"}</button>}
        {can("report.templates.manage") && <button onClick={() => setShowTemplates(!showTemplates)}>
          {showTemplates ? "Fechar modelos" : "Modelos de laudo"}</button>}</>}>
      {act.view}
      {can("report.sign") && showSignature && <MySignaturePanel />}
      {showBranding && <BrandingPanel />}
      {showPhysicians && <PhysiciansPanel me={me} />}
      {showTemplates && <Templates />}
      <CriticalAlerts canAck={can("report.write")} tick={tick} />
      {open && <Editor me={me} row={open.row} initial={open.report}
        onClose={() => { setOpen(null); setTick(tick + 1); void list.reload(); }} />}
      <form className="filters" role="search" aria-label="Filtrar laudos" onSubmit={(e) => { e.preventDefault(); setQuery(filters); }}>
        <select aria-label="Situação do laudo" value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}>
          <option value="pending">Sem laudo</option><option value="draft">Rascunho</option>
          <option value="final">Liberado</option><option value="all">Todos</option>
        </select>
        <input placeholder="Modalidade" aria-label="Modalidade" maxLength={16} value={filters.modality}
          onChange={(e) => setFilters({ ...filters, modality: e.target.value })} />
        <button>Filtrar</button>
      </form>
      <Notice kind="error">{list.error}</Notice>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Data</th><th>Paciente</th><th>Modalidade</th><th>Descrição</th><th>Accession</th>
            <th>Laudo</th><th>Ações</th></tr></thead>
          <tbody>
            {(list.data ?? []).map((r) => (
              <tr key={r.study_id}>
                <td className="nowrap">{day(r.study_date)}</td><td>{r.patient_name ?? "—"}</td><td>{r.modality ?? "—"}</td>
                <td>{r.description ?? "—"}</td><td className="nowrap">{r.accession ?? "—"}</td>
                <td>{STATUS[r.report_status]}{r.critical && <span className="tag tag-warn">Achado crítico</span>}</td>
                <td className="actions"><div className="row-actions">
                  {(r.report_id || can("report.write")) &&
                    <button onClick={() => void openRow(r)}>{r.report_status === "final" ? "Ver laudo" : "Laudar"}</button>}
                  {can("pacs.studies.read") && <a href={`/viewer/viewer?StudyInstanceUIDs=${encodeURIComponent(r.study_instance_uid)}`}
                    target="_blank" rel="noopener">Abrir no Viewer</a>}
                </div></td>
              </tr>
            ))}
          </tbody>
        </table>
        {!list.loading && !list.error && (list.data ?? []).length === 0 && <p className="empty">Nenhum estudo nessa situação.</p>}
      </div>
    </Page>
  );
}

function Editor({ me, row, initial, onClose }: { me: Me; row: Row; initial: Report | null; onClose: () => void }) {
  const can = (p: string) => me.permissions.includes(p);
  const [report, setReport] = useState<Report | null>(initial);
  const [draft, setDraft] = useState({ body: initial?.body ?? "", critical: initial?.critical ?? false,
    note: initial?.critical_note ?? "" });
  const [template, setTemplate] = useState("auto");
  const [password, setPassword] = useState("");
  const [add, setAdd] = useState({ text: "", critical: false, password: "" });
  const act = useAction();
  const templates = useLoad(async () => (!report && can("report.write")
    ? (await get<{ items: Template[] }>(`/report/templates?${new URLSearchParams({ published: "true", ...(row.modality ? { modality: row.modality } : {}) })}`)).items
    : []), [report]);
  const suggestion = useLoad(async () => (!report && can("report.write")
    ? await get<{ status: string; name?: string; level?: string; message?: string }>(`/report/suggest?study_id=${row.study_id}`) : null), [report]);
  const title = `Laudo — ${row.patient_name ?? "paciente"} — ${row.modality ?? ""} ${day(row.study_date)}`;

  async function create() {
    await act.run(async () => {
      const r = await post<Report>("/report/reports", template === "auto" ? { study_id: row.study_id, auto: true }
        : { study_id: row.study_id, template_id: template || null });
      setReport(r); setDraft({ body: r.body, critical: r.critical, note: r.critical_note ?? "" });
    }, "Rascunho criado.");
  }
  async function save() {
    if (!report) return;
    await act.run(async () => {
      const r = await put<Report>(`/report/reports/${report.id}`, { body: draft.body, critical: draft.critical,
        critical_note: draft.critical ? draft.note : null, row_version: report.row_version });
      setReport(r);
    }, "Rascunho salvo.");
  }
  async function finalize(e: FormEvent) {
    e.preventDefault();
    if (!report) return;
    const ok = await act.run(async () => {
      const saved = await put<Report>(`/report/reports/${report.id}`, { body: draft.body, critical: draft.critical,
        critical_note: draft.critical ? draft.note : null, row_version: report.row_version });
      setReport(saved);                                  // mantém a versão atual mesmo se a senha for recusada
      const r = await post<Report>(`/report/reports/${report.id}/finalize`, { password, row_version: saved.row_version });
      setReport(r);
    }, "Laudo liberado.");
    setPassword("");
    void ok;
  }
  async function addendum(e: FormEvent) {
    e.preventDefault();
    if (!report) return;
    await act.run(async () => {
      const r = await post<Report>(`/report/reports/${report.id}/addenda`, add);
      setReport(r); setAdd({ text: "", critical: false, password: "" });
    }, "Adendo registrado.");
  }

  return (
    <section className="panel" aria-label="Laudo">
      <div className="row-actions"><h2>{title}</h2><button type="button" className="link" onClick={onClose}>Fechar</button></div>
      {act.view}
      {!report && (can("report.write") ? (
        <div className="grid2">
          <Field label="Modelo" hint="Opcional: o texto do modelo vira o rascunho">
            <select value={template} onChange={(e) => setTemplate(e.target.value)}>
              <option value="auto">Automático (regras da organização)</option>
              <option value="">Sem modelo</option>
              {(templates.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </Field>
          <div><button className="primary" disabled={act.busy} onClick={() => void create()}>Iniciar laudo</button>
            {template === "auto" && suggestion.data && <p className="field-hint">{suggestion.data.status === "selected"
              ? `Modelo selecionado: ${suggestion.data.name} (regra: ${suggestion.data.level}).` : suggestion.data.message}</p>}</div>
        </div>) : <Notice kind="info">Sem laudo para este estudo.</Notice>)}
      {report?.status === "draft" && (
        <>
          <Field label="Texto do laudo">
            <textarea rows={14} value={draft.body} readOnly={!can("report.write")}
              onChange={(e) => setDraft({ ...draft, body: e.target.value })} />
          </Field>
          <label className="check"><input type="checkbox" checked={draft.critical} disabled={!can("report.write")}
            onChange={(e) => setDraft({ ...draft, critical: e.target.checked })} /> Achado crítico</label>
          {draft.critical && <Field label="Descrição do achado crítico" hint="Obrigatória para liberar; gera aviso ao solicitante">
            <input maxLength={300} value={draft.note} onChange={(e) => setDraft({ ...draft, note: e.target.value })} /></Field>}
          <div className="row-actions">
            {can("report.write") && <button disabled={act.busy} onClick={() => void save()}>Salvar rascunho</button>}
          </div>
          {can("report.sign") && (
            <form className="filters" aria-label="Liberar laudo" onSubmit={finalize}>
              <input type="password" required autoComplete="current-password" aria-label="Sua senha para liberar"
                placeholder="Sua senha" value={password} onChange={(e) => setPassword(e.target.value)} />
              <button className="primary" disabled={act.busy}>Liberar laudo</button>
            </form>)}
        </>
      )}
      {report?.status === "final" && (
        <>
          <Notice kind="ok">Liberado por {report.finalized_by} em {fmtDate(report.finalized_at)}. O texto liberado não muda; correções são adendos.</Notice>
          <div className="row-actions"><a className="button" href={`/api/v1/report/reports/${report.id}/pdf`}>Baixar PDF do laudo</a></div>
          {report.versions.map((v) => (
            <article key={v.version} aria-label={`Versão ${v.version}`} className="card">
              <span className="card-label">{v.kind === "final" ? "Laudo" : "Adendo"} — versão {v.version} — {v.signed_by}, {fmtDate(v.signed_at)}
                {v.critical && <span className="tag tag-warn">Achado crítico</span>}</span>
              <pre className="report-text">{v.body}</pre>
              <span className="field-hint" title={v.sha256}>SHA-256 {v.sha256.slice(0, 16)}…</span>
            </article>
          ))}
          {can("report.sign") && (
            <form className="panel" aria-label="Registrar adendo" onSubmit={addendum}>
              <Field label="Adendo"><textarea rows={4} required value={add.text} onChange={(e) => setAdd({ ...add, text: e.target.value })} /></Field>
              <label className="check"><input type="checkbox" checked={add.critical}
                onChange={(e) => setAdd({ ...add, critical: e.target.checked })} /> Achado crítico</label>
              <div className="filters">
                <input type="password" required autoComplete="current-password" aria-label="Sua senha para o adendo"
                  placeholder="Sua senha" value={add.password} onChange={(e) => setAdd({ ...add, password: e.target.value })} />
                <button className="primary" disabled={act.busy}>Registrar adendo</button>
              </div>
            </form>)}
        </>
      )}
    </section>
  );
}

type TplItem = Template & { published_version: number | null; preferred: boolean; procedure_id: string | null; site_id: string | null;
  draft: null | { version: number; technique: string; findings: string; conclusion: string;
    import_report: null | { issues: string[]; fields: string[]; header: string; footer: string } };
  versions: { version: number; status: string; created_by: string; published_by: string | null; published_at: string | null }[] };
const TPL_STATUS: Record<string, string> = { draft: "rascunho", published: "publicada", archived: "arquivada" };

/** Modelos de laudo com versões (TELELAUDO T3): rascunho, pré-visualização A4 e publicação após conferência. */
function Templates() {
  const list = useLoad(async () => await get<{ items: TplItem[]; fields: Record<string, string> }>("/report/templates?include_inactive=true"), []);
  const empty = { id: "", name: "", modality: "", technique: "", findings: "", conclusion: "", procedure_id: "", site_id: "", preferred: false };
  const procs = useLoad(async () => await get<{ id: string; name: string }[]>("/procedures").catch(() => []), []);
  const sites = useLoad(async () => await get<{ id: string; name: string }[]>("/sites").catch(() => []), []);
  const [form, setForm] = useState(empty);
  const [reviewed, setReviewed] = useState(false);
  const act = useAction();
  function edit(t: TplItem) {
    const d = t.draft;
    const pub = t.body;
    setForm({ id: t.id, name: t.name, modality: t.modality ?? "", technique: d?.technique ?? "", findings: d?.findings ?? (d ? "" : pub),
      conclusion: d?.conclusion ?? "", procedure_id: t.procedure_id ?? "", site_id: t.site_id ?? "", preferred: t.preferred });
    setReviewed(false);
  }
  async function save(e: FormEvent) {
    e.preventDefault();
    await act.run(async () => {
      const body = { name: form.name, modality: form.modality || null, technique: form.technique, findings: form.findings,
        conclusion: form.conclusion, procedure_id: form.procedure_id || null, site_id: form.site_id || null, preferred: form.preferred };
      const r = form.id ? await put<{ id: string }>(`/report/templates/${form.id}`, body) : await post<{ id: string }>("/report/templates", body);
      setForm({ ...form, id: r.id }); setReviewed(false);
      await list.reload();
    }, "Rascunho do modelo salvo. Confira a pré-visualização e publique.");
  }
  async function publish() {
    await act.run(async () => { await post(`/report/templates/${form.id}/publish`, { reviewed }); await list.reload(); setReviewed(false); },
      "Modelo publicado. Novos laudos passam a usar esta versão.");
  }
  const current = list.data?.items.find((t) => t.id === form.id);
  async function importDocx(f: File | undefined) {
    if (!f) return;
    await act.run(async () => {
      const r = await upload<{ id: string }>(`/report/templates/import-docx?${new URLSearchParams(form.modality ? { modality: form.modality } : {})}`, f);
      await list.reload();
      const items = (await get<{ items: TplItem[] }>("/report/templates?include_inactive=true")).items;
      const t = items.find((x) => x.id === r.id);
      if (t) edit(t);
    }, "DOCX importado como rascunho. Confira as incompatibilidades e a pré-visualização antes de publicar.");
  }
  return (
    <section className="panel" aria-label="Modelos de laudo">
      <h2>Modelos de laudo</h2>
      {act.view}
      <ul className="history">{(list.data?.items ?? []).map((t) => (
        <li key={t.id}><button className="link" onClick={() => edit(t)}>{t.name}</button>{t.modality ? ` (${t.modality})` : ""}
          {" — "}{t.published_version ? `publicada v${t.published_version}` : "sem versão publicada"}{t.draft ? ` · rascunho v${t.draft.version}` : ""}{t.active ? "" : " — inativo"}</li>))}
      </ul>
      <div className="filters" role="group" aria-label="Importar DOCX">
        <label className="field"><span className="field-label">Importar modelo do Word (DOCX)</span>
          <input type="file" accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            aria-label="Arquivo DOCX" onChange={(e) => void importDocx(e.target.files?.[0])} /></label>
      </div>
      {current?.draft?.import_report && (
        <Notice kind="warn"><strong>Importado do DOCX — confira antes de publicar:</strong>
          <ul>{current.draft.import_report.issues.map((i, k) => <li key={k}>{i}</li>)}</ul>
          {(current.draft.import_report.header || current.draft.import_report.footer) &&
            <span>Sugestão para a identidade visual — cabeçalho: “{current.draft.import_report.header || "—"}”; rodapé: “{current.draft.import_report.footer || "—"}”.</span>}
        </Notice>)}
      <form onSubmit={save} aria-label="Editar modelo">
        <div className="grid2">
          <Field label="Nome do modelo"><input required maxLength={120} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Modalidade" hint="Vazio = todas"><input maxLength={16} value={form.modality} onChange={(e) => setForm({ ...form, modality: e.target.value.toUpperCase() })} /></Field>
          <Field label="Procedimento" hint="Regra mais específica">
            <select value={form.procedure_id} onChange={(e) => setForm({ ...form, procedure_id: e.target.value })}>
              <option value="">Qualquer procedimento</option>
              {(procs.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
          <Field label="Unidade" hint="Vazio = toda a organização">
            <select value={form.site_id} onChange={(e) => setForm({ ...form, site_id: e.target.value })}>
              <option value="">Toda a organização</option>
              {(sites.data ?? []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>
        </div>
        <label className="check"><input type="checkbox" checked={form.preferred} onChange={(e) => setForm({ ...form, preferred: e.target.checked })} /> Preferencial (desempata modelos da mesma regra)</label>
        <p className="field-hint">Campos dinâmicos (preenchidos com os dados do exame): {Object.keys(list.data?.fields ?? {}).map((f) => `{{${f}}}`).join("  ")}</p>
        <Field label="Técnica"><textarea rows={3} value={form.technique} onChange={(e) => setForm({ ...form, technique: e.target.value })} /></Field>
        <Field label="Achados"><textarea rows={5} value={form.findings} onChange={(e) => setForm({ ...form, findings: e.target.value })} /></Field>
        <Field label="Conclusão"><textarea rows={3} value={form.conclusion} onChange={(e) => setForm({ ...form, conclusion: e.target.value })} /></Field>
        <div className="row-actions">
          <button className="primary" disabled={act.busy}>Salvar rascunho</button>
          {form.id && <button type="button" className="link" onClick={() => { setForm(empty); setReviewed(false); }}>Novo modelo</button>}
        </div>
      </form>
      {form.id && current?.draft && (
        <div className="row-actions" role="group" aria-label="Publicar modelo">
          <a className="button" href={`/api/v1/report/templates/${form.id}/preview`} target="_blank" rel="noopener">Pré-visualizar A4</a>
          <label className="check"><input type="checkbox" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} /> Conferi o texto e a pré-visualização</label>
          <button className="primary" disabled={!reviewed || act.busy} onClick={() => void publish()}>Publicar versão {current.draft.version}</button>
        </div>)}
      {current && <p className="field-hint">Versões: {current.versions.map((v) => `v${v.version} ${TPL_STATUS[v.status] ?? v.status}${v.published_by ? ` por ${v.published_by}` : ""}`).join(" · ")}</p>}
    </section>
  );
}

const CHANNELS = ["telefone", "presencial", "mensagem", "e-mail", "outro"];

function CriticalAlerts({ canAck, tick }: { canAck: boolean; tick: number }) {
  const list = useLoad(async () => (await get<{ items: Alert[] }>("/report/critical")).items, [tick]);
  const [form, setForm] = useState<{ id: string; to: string; channel: string; note: string } | null>(null);
  const act = useAction();
  if (!list.data?.length && !act.view) return null;
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!form) return;
    const ok = await act.run(async () => {
      await post(`/report/critical/${form.id}/communicate`, { notified_to: form.to, channel: form.channel, note: form.note || null });
      await list.reload();
    }, "Comunicação do achado crítico registrada.");
    if (ok) setForm(null);
  }
  return (
    <section className="panel" aria-label="Achados críticos a comunicar">
      <h2>Achados críticos a comunicar</h2>
      {act.view}
      <ul className="history">
        {(list.data ?? []).map((a) => (
          <li key={a.id}>
            <strong>{a.patient_name ?? "Paciente"}</strong> — {a.modality ?? ""} {a.accession ?? ""} — {a.note ?? "achado crítico"}
            {" "}(liberado por {a.signed_by ?? "—"}, {fmtDate(a.created_at)}; solicitante: {a.requester ?? "não informado"})
            {canAck && form?.id !== a.id && <> <button className="link" onClick={() => setForm({ id: a.id, to: a.requester ?? "", channel: "telefone", note: "" })}>Registrar comunicação</button></>}
            {form?.id === a.id && (
              <form className="filters" aria-label="Registrar comunicação do achado crítico" onSubmit={submit}>
                <input required maxLength={200} aria-label="Comunicado a" placeholder="Comunicado a (nome e função)"
                  value={form.to} onChange={(e) => setForm({ ...form, to: e.target.value })} />
                <select aria-label="Meio" value={form.channel} onChange={(e) => setForm({ ...form, channel: e.target.value })}>
                  {CHANNELS.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
                <input maxLength={500} aria-label="Observação" placeholder="Observação" value={form.note}
                  onChange={(e) => setForm({ ...form, note: e.target.value })} />
                <button className="primary" disabled={act.busy}>Confirmar</button>
              </form>)}
          </li>))}
      </ul>
    </section>
  );
}
