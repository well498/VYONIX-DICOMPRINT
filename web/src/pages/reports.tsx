import { useState, type FormEvent } from "react";
import { fmtDate, get, post, put, type Me } from "../api";
import { Field, Notice, Page, useAction, useLoad } from "../ui";

type Row = { study_id: string; study_instance_uid: string; accession: string | null; modality: string | null;
  study_date: string | null; description: string | null; patient_name: string | null; report_id: string | null;
  report_status: "pending" | "draft" | "final"; critical: boolean };
type Version = { version: number; kind: "final" | "addendum"; body: string; critical: boolean; signed_by: string;
  signed_at: string; sha256: string };
type Report = { id: string; study_id: string; study_instance_uid: string | null; status: "draft" | "final"; body: string;
  critical: boolean; critical_note: string | null; author: string; version: number; finalized_by: string | null;
  finalized_at: string | null; row_version: number; versions: Version[] };
type Template = { id: string; name: string; modality: string | null; body: string; active: boolean };

const STATUS: Record<string, string> = { pending: "Sem laudo", draft: "Rascunho", final: "Liberado" };

function day(d: string | null) { return d ? fmtDate(d + "T12:00:00", false) : "—"; }

export function ReportsPage({ me }: { me: Me }) {
  const can = (p: string) => me.permissions.includes(p);
  const [filters, setFilters] = useState({ status: "pending", modality: "" });
  const [query, setQuery] = useState(filters);
  const [open, setOpen] = useState<{ row: Row; report: Report | null } | null>(null);
  const [showTemplates, setShowTemplates] = useState(false);
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
      actions={can("report.templates.manage") ? <button onClick={() => setShowTemplates(!showTemplates)}>
        {showTemplates ? "Fechar modelos" : "Modelos de laudo"}</button> : undefined}>
      {act.view}
      {showTemplates && <Templates />}
      {open && <Editor me={me} row={open.row} initial={open.report}
        onClose={() => { setOpen(null); void list.reload(); }} />}
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
  const [template, setTemplate] = useState("");
  const [password, setPassword] = useState("");
  const [add, setAdd] = useState({ text: "", critical: false, password: "" });
  const act = useAction();
  const templates = useLoad(async () => (!report && can("report.write")
    ? (await get<{ items: Template[] }>(`/report/templates?${new URLSearchParams(row.modality ? { modality: row.modality } : {})}`)).items
    : []), [report]);
  const title = `Laudo — ${row.patient_name ?? "paciente"} — ${row.modality ?? ""} ${day(row.study_date)}`;

  async function create() {
    await act.run(async () => {
      const r = await post<Report>("/report/reports", { study_id: row.study_id, template_id: template || null });
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
              <option value="">Sem modelo</option>
              {(templates.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </Field>
          <div><button className="primary" disabled={act.busy} onClick={() => void create()}>Iniciar laudo</button></div>
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

function Templates() {
  const list = useLoad(async () => (await get<{ items: Template[] }>("/report/templates?include_inactive=true")).items, []);
  const [form, setForm] = useState({ name: "", modality: "", body: "" });
  const act = useAction();
  async function submit(e: FormEvent) {
    e.preventDefault();
    const ok = await act.run(async () => { await post("/report/templates", form); await list.reload(); }, "Modelo salvo.");
    if (ok) setForm({ name: "", modality: "", body: "" });
  }
  return (
    <section className="panel" aria-label="Modelos de laudo">
      <h2>Modelos de laudo</h2>
      {act.view}
      <ul className="history">{(list.data ?? []).map((t) => <li key={t.id}>{t.name}{t.modality ? ` (${t.modality})` : ""}{t.active ? "" : " — inativo"}</li>)}</ul>
      <form onSubmit={submit} aria-label="Novo modelo">
        <div className="grid2">
          <Field label="Nome do modelo"><input required maxLength={120} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Modalidade" hint="Vazio = todas"><input maxLength={16} value={form.modality} onChange={(e) => setForm({ ...form, modality: e.target.value.toUpperCase() })} /></Field>
        </div>
        <Field label="Texto do modelo"><textarea rows={6} value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} /></Field>
        <button className="primary" disabled={act.busy}>Salvar modelo</button>
      </form>
    </section>
  );
}
