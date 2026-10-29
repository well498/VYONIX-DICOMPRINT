import { useState, type FormEvent } from "react";
import { del, fmtDate, get, post, put, upload, type Me } from "../api";
import { asHtml, RichEditor, RichView, type Phrase } from "../richtext";
import { Priors } from "./prep";
import { Field, Notice, Page, useAction, useLoad } from "../ui";
import { BrandingPanel } from "./branding";
import { MySignaturePanel, PhysiciansPanel } from "./physicians";

type Row = { study_id: string; study_instance_uid: string; accession: string | null; modality: string | null;
  study_date: string | null; description: string | null; patient_name: string | null; report_id: string | null;
  report_status: "pending" | "draft" | "review" | "final"; critical: boolean;
  assignment: null | { physician: string; priority: string; due_at: string; overdue: boolean } };
type Version = { version: number; kind: "final" | "addendum"; body: string; critical: boolean; signed_by: string;
  signed_at: string; sha256: string; signature_mode?: "password" | "handwritten_image"; body_format?: string;
  author?: string | null; reviewer?: string | null;
  changes?: null | { revisions: number; editors: string[]; review_rounds: number; returns: number;
    reviewer_edited?: boolean; reviewer_added_lines?: number; reviewer_removed_lines?: number } };
type Review = { requested_by: string | null; note: string | null; requested_at: string | null; reviewer_id: string | null };
type Report = { id: string; study_id: string; study_instance_uid: string | null; status: "draft" | "review" | "final";
  body: string; body_format?: string; critical: boolean; critical_note: string | null; author: string; version: number;
  finalized_by: string | null; finalized_at: string | null; row_version: number; versions: Version[];
  draft_revision?: number; review?: Review | null };
type Revision = { revision: number; author: string; event: string; at: string; body: string; body_format: string };
const REV_EVENT: Record<string, string> = { save: "gravação", review_request: "enviado para revisão", return: "devolvido pelo revisor" };
type Alert = { id: string; report_id: string; version: number; note: string | null; created_at: string;
  patient_name: string | null; accession: string | null; modality: string | null; requester: string | null;
  signed_by: string | null };
type Template = { id: string; name: string; modality: string | null; body: string; active: boolean };

const PRIORITY: Record<string, string> = { routine: "rotina", urgent: "urgente", stat: "imediato" };
const STATUS: Record<string, string> = { pending: "Sem laudo", draft: "Rascunho", review: "Em revisão", final: "Liberado" };
const MODE: Record<string, string> = { password: "Liberado com confirmação de senha",
  handwritten_image: "Senha + imagem da assinatura manuscrita (visual; não é assinatura digital)" };
type Block = { show_image: boolean; position: "block" | "footer"; align: "left" | "center" | "right"; height_mm: number;
  show_name: boolean; show_crm: boolean; show_specialty: boolean; show_rqe: boolean };
const BLOCK: Block = { show_image: true, position: "block", align: "left", height_mm: 14, show_name: true, show_crm: true,
  show_specialty: false, show_rqe: true };

function day(d: string | null) { return d ? fmtDate(d + "T12:00:00", false) : "—"; }

export function ReportsPage({ me }: { me: Me }) {
  const can = (p: string) => me.permissions.includes(p);
  const [filters, setFilters] = useState({ status: "pending", modality: "", mine: false });
  const [assignFor, setAssignFor] = useState<{ study: string; physician: string; priority: string } | null>(null);
  const docs = useLoad(async () => (can("report.assign") && assignFor ? (await get<{ items: { id: string; name: string }[] }>("/report/assignable-physicians")).items : []),
    [assignFor?.study]);   // recarrega ao abrir a atribuição (médicos recém-cadastrados aparecem)
  const [query, setQuery] = useState(filters);
  const [open, setOpen] = useState<{ row: Row; report: Report | null } | null>(null);
  const [showTemplates, setShowTemplates] = useState(false);
  const [tick, setTick] = useState(0);
  const [showPhysicians, setShowPhysicians] = useState(false);
  const [showBranding, setShowBranding] = useState(false);
  const [showSignature, setShowSignature] = useState(false);
  const [showPhrases, setShowPhrases] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [batch, setBatch] = useState({ confirm: false, password: "" });
  const act = useAction();

  const list = useLoad(async () => {
    const q = new URLSearchParams();
    if (query.status !== "all") q.set("status", query.status);
    if (query.modality) q.set("modality", query.modality.toUpperCase());
    if (query.mine) q.set("mine", "true");
    return (await get<{ items: Row[] }>(`/report/worklist?${q}`)).items;
  }, [query]);

  async function assign() {
    if (!assignFor) return;
    const ok = await act.run(async () => {
      await post("/report/assignments", { study_id: assignFor.study, physician_id: assignFor.physician, priority: assignFor.priority });
      await list.reload();
    }, "Exame atribuído.");
    if (ok) setAssignFor(null);
  }

  async function finalizeBatch(e: FormEvent) {
    e.preventDefault();
    await act.run(async () => {
      const r = await post<{ released: number; results: { report_id: string; ok: boolean; message?: string }[] }>(
        "/report/reports/finalize-batch", { report_ids: picked, password: batch.password, confirm: batch.confirm });
      const bad = r.results.filter((x) => !x.ok);
      setPicked(bad.map((x) => x.report_id)); setBatch({ confirm: false, password: "" });
      await list.reload();
      if (bad.length) throw new Error(`${r.released} liberado(s); ${bad.length} não: ${bad.map((x) => x.message).join("; ")}`);
    }, "Laudos selecionados liberados, cada um registrado individualmente na auditoria.");
    setBatch((b) => ({ ...b, password: "" }));
  }

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
        {(can("report.templates.manage") || can("report.templates.own")) && <button onClick={() => setShowTemplates(!showTemplates)}>
          {showTemplates ? "Fechar modelos" : "Modelos de laudo"}</button>}
        {(can("report.phrases.own") || can("report.phrases.manage")) && <button onClick={() => setShowPhrases(!showPhrases)}>
          {showPhrases ? "Fechar frases" : "Frases rápidas"}</button>}</>}>
      {act.view}
      {can("report.sign") && showSignature && <MySignaturePanel />}
      {showBranding && <BrandingPanel />}
      {showPhysicians && <PhysiciansPanel me={me} />}
      {showTemplates && <Templates me={me} />}
      {showPhrases && <Phrases me={me} />}
      <CriticalAlerts canAck={can("report.write")} tick={tick} />
      {open && <Editor me={me} row={open.row} initial={open.report}
        onClose={() => { setOpen(null); setTick(tick + 1); void list.reload(); }} />}
      <form className="filters" role="search" aria-label="Filtrar laudos" onSubmit={(e) => { e.preventDefault(); setQuery(filters); }}>
        <select aria-label="Situação do laudo" value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}>
          <option value="pending">Sem laudo</option><option value="draft">Rascunho</option>
          <option value="review">Em revisão</option><option value="final">Liberado</option><option value="all">Todos</option>
        </select>
        <input placeholder="Modalidade" aria-label="Modalidade" maxLength={16} value={filters.modality}
          onChange={(e) => setFilters({ ...filters, modality: e.target.value })} />
        {can("report.sign") && <label className="check"><input type="checkbox" checked={filters.mine}
          onChange={(e) => setFilters({ ...filters, mine: e.target.checked })} /> Atribuídos a mim</label>}
        <button>Filtrar</button>
      </form>
      <Notice kind="error">{list.error}</Notice>
      {can("report.sign") && picked.length > 0 && (
        <form className="panel" aria-label="Liberar laudos selecionados" onSubmit={finalizeBatch}>
          <strong>{picked.length} rascunho(s) selecionado(s)</strong>
          <label className="check"><input type="checkbox" checked={batch.confirm} onChange={(e) => setBatch({ ...batch, confirm: e.target.checked })} />
            {" "}Revisei e libero, em meu nome ({me.display_name}), os {picked.length} laudos selecionados</label>
          <div className="filters">
            <input type="password" required autoComplete="current-password" aria-label="Sua senha para liberar os selecionados"
              placeholder="Sua senha" value={batch.password} onChange={(e) => setBatch({ ...batch, password: e.target.value })} />
            <button className="primary" disabled={!batch.confirm || act.busy}>Liberar selecionados</button>
            <button type="button" className="link" onClick={() => setPicked([])}>Limpar seleção</button>
          </div>
          <span className="field-hint">Cada laudo é liberado e auditado individualmente; um erro em um não afeta os demais. Máximo de 50.</span>
        </form>)}
      <div className="table-wrap">
        <table>
          <thead><tr><th>Data</th><th>Paciente</th><th>Modalidade</th><th>Descrição</th><th>Accession</th>
            <th>Laudo</th><th>Fila</th><th>Ações</th></tr></thead>
          <tbody>
            {(list.data ?? []).map((r) => (
              <tr key={r.study_id}>
                <td className="nowrap">{can("report.sign") && r.report_status === "draft" && r.report_id &&
                  <input type="checkbox" aria-label={`Selecionar laudo de ${r.patient_name ?? "paciente"}`} checked={picked.includes(r.report_id)}
                    onChange={(e) => setPicked(e.target.checked ? [...picked, r.report_id!].slice(0, 50) : picked.filter((x) => x !== r.report_id))} />}
                  {" "}{day(r.study_date)}</td><td>{r.patient_name ?? "—"}</td><td>{r.modality ?? "—"}</td>
                <td>{r.description ?? "—"}</td><td className="nowrap">{r.accession ?? "—"}</td>
                <td>{STATUS[r.report_status]}{r.critical && <span className="tag tag-warn">Achado crítico</span>}</td>
                <td>{r.assignment ? <>{r.assignment.physician} · {PRIORITY[r.assignment.priority] ?? r.assignment.priority} · até {fmtDate(r.assignment.due_at)}
                  {r.assignment.overdue && <span className="tag tag-warn">Atrasado</span>}</> : "—"}
                  {can("report.assign") && r.report_status !== "final" && (assignFor?.study === r.study_id ? (
                    <form className="filters" aria-label="Atribuir exame" onSubmit={(e) => { e.preventDefault(); void assign(); }}>
                      <select aria-label="Médico" required value={assignFor.physician} onChange={(e) => setAssignFor({ ...assignFor, physician: e.target.value })}>
                        <option value="">Médico…</option>{(docs.data ?? []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select>
                      <select aria-label="Prioridade" value={assignFor.priority} onChange={(e) => setAssignFor({ ...assignFor, priority: e.target.value })}>
                        <option value="routine">Rotina (48 h)</option><option value="urgent">Urgente (4 h)</option><option value="stat">Imediato (1 h)</option></select>
                      <button className="primary" disabled={act.busy}>Atribuir</button>
                    </form>) : <> <button className="link" onClick={() => setAssignFor({ study: r.study_id, physician: "", priority: "routine" })}>
                      {r.assignment ? "Reatribuir" : "Atribuir"}</button></>)}</td>
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
  const [draft, setDraft] = useState({ body: asHtml(initial?.body ?? "", initial?.body_format), critical: initial?.critical ?? false,
    note: initial?.critical_note ?? "" });
  const [review, setReview] = useState({ reviewer: "", note: "" });
  const [showRevs, setShowRevs] = useState(false);
  const phrases = useLoad(async () => (can("report.write")
    ? (await get<{ items: Phrase[] }>(`/report/phrases?${new URLSearchParams(row.modality ? { modality: row.modality } : {})}`)).items : []), []);
  const reviewers = useLoad(async () => (report?.status === "draft" && can("report.write")
    ? (await get<{ items: { id: string; name: string }[] }>("/report/reviewers")).items : []), [report?.status]);
  const fields = useLoad(async () => (report && report.status !== "final" && can("report.write")
    ? (await get<{ fields: Record<string, string | null> }>(`/report/reports/${report.id}/fields`)).fields : {}), [report?.id]);
  const revs = useLoad(async () => (showRevs && report ? (await get<{ items: Revision[] }>(`/report/reports/${report.id}/revisions`)).items : []),
    [showRevs, report?.row_version]);
  const editable = report?.status === "draft" ? can("report.write") : report?.status === "review" && can("report.review");
  const [template, setTemplate] = useState("auto");
  const [password, setPassword] = useState("");
  const [add, setAdd] = useState({ text: "", critical: false, password: "" });
  const act = useAction();
  const templates = useLoad(async () => (!report && can("report.write")
    ? (await get<{ items: Template[] }>(`/report/templates?${new URLSearchParams({ published: "true", ...(row.modality ? { modality: row.modality } : {}) })}`)).items
    : []), [report]);
  const suggestion = useLoad(async () => (!report && can("report.write")
    ? await get<{ status: string; name?: string; level?: string; message?: string }>(`/report/suggest?study_id=${row.study_id}`) : null), [report]);
  const sig = useLoad(async () => (can("report.sign") ? await get<{ has_image: boolean; use_signature_image: boolean }>(
    "/report/physicians/me/signature").catch(() => null) : null), []);
  const title = `Laudo — ${row.patient_name ?? "paciente"} — ${row.modality ?? ""} ${day(row.study_date)}`;

  async function create() {
    await act.run(async () => {
      const r = await post<Report>("/report/reports", template === "auto" ? { study_id: row.study_id, auto: true }
        : { study_id: row.study_id, template_id: template || null });
      setReport(r); setDraft({ body: asHtml(r.body, r.body_format), critical: r.critical, note: r.critical_note ?? "" });
    }, "Rascunho criado.");
  }
  async function save() {
    if (!report) return;
    await act.run(async () => {
      const r = await put<Report>(`/report/reports/${report.id}`, { body: draft.body, body_format: "html", critical: draft.critical,
        critical_note: draft.critical ? draft.note : null, row_version: report.row_version });
      setReport(r);
    }, "Rascunho salvo.");
  }
  async function sendReview(e: FormEvent) {
    e.preventDefault();
    if (!report) return;
    await act.run(async () => {
      const saved = await put<Report>(`/report/reports/${report.id}`, { body: draft.body, body_format: "html", critical: draft.critical,
        critical_note: draft.critical ? draft.note : null, row_version: report.row_version });
      const r = await post<Report>(`/report/reports/${report.id}/review`, { reviewer_id: review.reviewer || null,
        note: review.note || null, row_version: saved.row_version });
      setReport(r); setReview({ reviewer: "", note: "" });
    }, "Laudo enviado para revisão. O texto fica bloqueado para você até a devolução.");
  }
  async function returnReview(e: FormEvent) {
    e.preventDefault();
    if (!report) return;
    await act.run(async () => {
      const r = await post<Report>(`/report/reports/${report.id}/review/return`, { note: review.note });
      setReport(r); setReview({ reviewer: "", note: "" });
    }, "Laudo devolvido ao autor com a sua observação.");
  }
  async function finalize(e: FormEvent) {
    e.preventDefault();
    if (!report) return;
    const ok = await act.run(async () => {
      const saved = await put<Report>(`/report/reports/${report.id}`, { body: draft.body, body_format: "html", critical: draft.critical,
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
      <details className="prior-box"><summary>Exames anteriores do paciente</summary><Priors studyId={row.study_id} /></details>
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
      {report && report.status !== "final" && (
        <>
          {report.status === "review" && <Notice kind="info">Em revisão — enviado por {report.review?.requested_by ?? "—"} em {fmtDate(report.review?.requested_at)}
            {report.review?.note ? `. Observação: ${report.review.note}` : ""}. {editable ? "Você pode ajustar o texto, devolver ao autor ou liberar." : "O texto fica bloqueado até a devolução ou a liberação pelo revisor."}</Notice>}
          {report.status === "draft" && report.review?.note && <Notice kind="warn">Devolvido pelo revisor: {report.review.note}</Notice>}
          <RichEditor label="Texto do laudo" value={draft.body} readOnly={!editable} rows={14}
            phrases={phrases.data ?? []} fields={fields.data ?? {}} onChange={(h) => setDraft((d) => ({ ...d, body: h }))}
            hint="Negrito, itálico, sublinhado, listas e tabelas aparecem iguais no PDF. Frases: escolha na lista ou digite o atalho (ex.: /normal) e espaço." />
          <label className="check"><input type="checkbox" checked={draft.critical} disabled={!editable}
            onChange={(e) => setDraft({ ...draft, critical: e.target.checked })} /> Achado crítico</label>
          {draft.critical && <Field label="Descrição do achado crítico" hint="Obrigatória para liberar; gera aviso ao solicitante">
            <input maxLength={300} value={draft.note} readOnly={!editable} onChange={(e) => setDraft({ ...draft, note: e.target.value })} /></Field>}
          <div className="row-actions">
            {editable && <button disabled={act.busy} onClick={() => void save()}>Salvar rascunho</button>}
            <a className="link" href={`/api/v1/report/reports/${report.id}/draft-pdf`} target="_blank" rel="noopener">Prévia do rascunho (sem assinatura)</a>
            <button type="button" className="link" onClick={() => setShowRevs(!showRevs)}>
              {showRevs ? "Ocultar histórico" : `Histórico do rascunho (${report.draft_revision ?? 0})`}</button>
          </div>
          {showRevs && (
            <section className="panel-inset" aria-label="Histórico do rascunho">
              {(revs.data ?? []).length === 0 && <p className="empty">Sem revisões gravadas.</p>}
              {(revs.data ?? []).slice().reverse().map((x) => (
                <details key={x.revision}><summary>Revisão {x.revision} — {x.author}, {fmtDate(x.at)} ({REV_EVENT[x.event] ?? x.event})</summary>
                  <RichView html={x.body} format={x.body_format} label={`Revisão ${x.revision}`} /></details>))}
            </section>)}
          {report.status === "draft" && can("report.write") && (
            <form className="filters" aria-label="Enviar para revisão" onSubmit={sendReview}>
              <select aria-label="Revisor" value={review.reviewer} onChange={(e) => setReview({ ...review, reviewer: e.target.value })}>
                <option value="">Qualquer revisor</option>
                {(reviewers.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}</select>
              <input aria-label="Observação para o revisor" placeholder="Observação (opcional)" maxLength={1000} value={review.note}
                onChange={(e) => setReview({ ...review, note: e.target.value })} />
              <button disabled={act.busy}>Enviar para revisão</button>
            </form>)}
          {report.status === "review" && editable && (
            <form className="filters" aria-label="Devolver ao autor" onSubmit={returnReview}>
              <input aria-label="O que precisa ser revisto" required placeholder="O que precisa ser revisto" maxLength={1000}
                value={review.note} onChange={(e) => setReview({ ...review, note: e.target.value })} />
              <button disabled={act.busy}>Devolver ao autor</button>
            </form>)}
          {can("report.sign") && (report.status === "draft" || editable) && (
            <form className="filters" aria-label="Liberar laudo" onSubmit={finalize}>
              <input type="password" required autoComplete="current-password" aria-label="Sua senha para liberar"
                placeholder="Sua senha" value={password} onChange={(e) => setPassword(e.target.value)} />
              <button className="primary" disabled={act.busy}>Liberar laudo</button>
              <span className="field-hint">Confirmação por senha (não é assinatura digital ICP-Brasil).{" "}
                {sig.data?.has_image && sig.data.use_signature_image
                  ? "A imagem da sua assinatura manuscrita será inserida como elemento visual."
                  : "Sem imagem de assinatura manuscrita (não cadastrada ou não autorizada)."}</span>
            </form>)}
        </>
      )}
      {report?.status === "final" && (
        <>
          <Notice kind="ok">Liberado por {report.finalized_by} em {fmtDate(report.finalized_at)}. O texto liberado não muda; correções são adendos.</Notice>
          <div className="row-actions" role="group" aria-label="Saídas do laudo">
            <a className="button" href={`/api/v1/report/reports/${report.id}/pdf`}>Baixar PDF do laudo</a>
            <a className="link" href={`/api/v1/report/reports/${report.id}/fhir`} target="_blank" rel="noopener">FHIR (JSON)</a>
            <a className="link" href={`/api/v1/report/reports/${report.id}/hl7`}>HL7 v2 (ORU)</a>
            {can("report.write") && <button className="link" disabled={act.busy} onClick={() => void act.run(async () => {
              await post(`/report/reports/${report.id}/send-to-pacs`, {});
            }, "Laudo guardado no PACS (DICOM Encapsulated PDF) no mesmo estudo.")}>Guardar no PACS</button>}
          </div>
          {report.versions.map((v) => (
            <article key={v.version} aria-label={`Versão ${v.version}`} className="card">
              <span className="card-label">{v.kind === "final" ? "Laudo" : "Adendo"} — versão {v.version} — {v.signed_by}, {fmtDate(v.signed_at)}
                {v.critical && <span className="tag tag-warn">Achado crítico</span>}</span>
              {v.signature_mode && <span className="field-hint">{MODE[v.signature_mode]}</span>}
              <RichView html={v.body} format={v.body_format} />
              <span className="field-hint">{v.reviewer
                ? <>Redigido por {v.author ?? "—"} · revisado e liberado por {v.reviewer}</>
                : <>Redigido e liberado por {v.signed_by}</>}
                {v.changes && <> · {v.changes.revisions} gravação(ões) do rascunho{v.changes.editors.length ? ` (${v.changes.editors.join(", ")})` : ""}
                  {v.changes.review_rounds > 0 && `; ${v.changes.review_rounds} envio(s) para revisão, ${v.changes.returns} devolução(ões)`}
                  {v.changes.reviewer_edited !== undefined && (v.changes.reviewer_edited
                    ? `; o revisor alterou o texto (+${v.changes.reviewer_added_lines}/−${v.changes.reviewer_removed_lines} linhas)`
                    : "; o revisor não alterou o texto")}</>}
                . Liberação por senha{v.signature_mode === "handwritten_image" ? " + imagem da assinatura manuscrita" : ""}; não é assinatura digital ICP-Brasil.</span>
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
  content_format?: string; personal?: boolean;
  draft: null | { version: number; technique: string; findings: string; conclusion: string; signature_block?: Block; content_format?: string;
    import_report: null | { issues: string[]; fields: string[]; header: string; footer: string } };
  signature_block?: Block;
  versions: { version: number; status: string; created_by: string; published_by: string | null; published_at: string | null }[] };
const TPL_STATUS: Record<string, string> = { draft: "rascunho", published: "publicada", archived: "arquivada" };

/** Modelos de laudo com versões (TELELAUDO T3): rascunho, pré-visualização A4 e publicação após conferência. */
function Templates({ me }: { me: Me }) {
  const can = (p: string) => me.permissions.includes(p);
  const list = useLoad(async () => await get<{ items: TplItem[]; fields: Record<string, string> }>("/report/templates?include_inactive=true"), []);
  const empty = { id: "", name: "", modality: "", technique: "", findings: "", conclusion: "", procedure_id: "", site_id: "", preferred: false,
    personal: !can("report.templates.manage") };
  const procs = useLoad(async () => await get<{ id: string; name: string }[]>("/procedures").catch(() => []), []);
  const sites = useLoad(async () => await get<{ id: string; name: string }[]>("/sites").catch(() => []), []);
  const [form, setForm] = useState(empty);
  const [block, setBlock] = useState<Block>(BLOCK);
  const [reviewed, setReviewed] = useState(false);
  const act = useAction();
  function edit(t: TplItem) {
    const d = t.draft;
    const pub = t.body;
    const f = d?.content_format ?? t.content_format;
    setForm({ id: t.id, name: t.name, modality: t.modality ?? "", technique: asHtml(d?.technique ?? "", f),
      findings: asHtml(d?.findings ?? (d ? "" : pub), f), conclusion: asHtml(d?.conclusion ?? "", f), procedure_id: t.procedure_id ?? "",
      site_id: t.site_id ?? "", preferred: t.preferred, personal: Boolean(t.personal) });
    setBlock(d?.signature_block ?? t.signature_block ?? BLOCK);
    setReviewed(false);
  }
  async function save(e: FormEvent) {
    e.preventDefault();
    await act.run(async () => {
      const body = { name: form.name, modality: form.modality || null, technique: form.technique, findings: form.findings,
        conclusion: form.conclusion, procedure_id: form.personal ? null : form.procedure_id || null,
        site_id: form.personal ? null : form.site_id || null, preferred: !form.personal && form.preferred,
        signature_block: block, content_format: "html", personal: form.personal };
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
  async function importMine(f: File | undefined) {
    if (!f) return;
    await act.run(async () => {
      const r = await upload<{ created: { name: string }[] }>("/report/templates/mine/import", f);
      await list.reload();
      act.setMsg({ kind: "ok", text: `${r.created.length} modelo(s) recuperado(s) como rascunhos pessoais: ${r.created.map((x) => x.name).join(", ")}.` });
    });
  }
  async function propose() {
    await act.run(async () => {
      const r = await post<{ name: string }>(`/report/templates/${form.id}/propose`, {});
      await list.reload();
      act.setMsg({ kind: "ok", text: `Cópia oferecida à instituição como “${r.name}” (inativa, em rascunho). Quem gerencia os modelos confere e publica; seu modelo continua pessoal.` });
    });
  }
  async function importDocx(f: File | undefined) {
    if (!f) return;
    await act.run(async () => {
      const q = new URLSearchParams(form.modality ? { modality: form.modality } : {});
      if (form.personal) q.set("personal", "true");
      const r = await upload<{ id: string }>(`/report/templates/import-docx?${q}`, f);
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
          {t.personal && <span className="tag">pessoal</span>}
          {" — "}{t.published_version ? `publicada v${t.published_version}` : "sem versão publicada"}{t.draft ? ` · rascunho v${t.draft.version}` : ""}{t.active ? "" : " — inativo"}</li>))}
      </ul>
      {can("report.templates.own") && (
        <div className="filters" role="group" aria-label="Meus modelos pessoais">
          <a className="button" href="/api/v1/report/templates/mine/export">Exportar meus modelos pessoais</a>
          <label className="field"><span className="field-label">Recuperar de uma exportação</span>
            <input type="file" accept=".json,application/json" aria-label="Arquivo de exportação de modelos"
              onChange={(e) => void importMine(e.target.files?.[0])} /></label>
          <span className="field-hint">A exportação é sua cópia de segurança (com verificação de integridade). Ninguém mais exporta ou lê seus modelos pessoais.</span>
        </div>)}
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
        {can("report.templates.own") && can("report.templates.manage") && !form.id && (
          <label className="check"><input type="checkbox" checked={form.personal} onChange={(e) => setForm({ ...form, personal: e.target.checked })} />
            {" "}Modelo pessoal (só eu vejo e uso; não entra na seleção automática)</label>)}
        {form.personal && <p className="field-hint">Modelo pessoal: visível apenas para você.</p>}
        <div className="grid2">
          <Field label="Nome do modelo"><input required maxLength={120} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Modalidade" hint="Vazio = todas"><input maxLength={16} value={form.modality} onChange={(e) => setForm({ ...form, modality: e.target.value.toUpperCase() })} /></Field>
          {!form.personal && <>
          <Field label="Procedimento" hint="Regra mais específica">
            <select value={form.procedure_id} onChange={(e) => setForm({ ...form, procedure_id: e.target.value })}>
              <option value="">Qualquer procedimento</option>
              {(procs.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
          <Field label="Unidade" hint="Vazio = toda a organização">
            <select value={form.site_id} onChange={(e) => setForm({ ...form, site_id: e.target.value })}>
              <option value="">Toda a organização</option>
              {(sites.data ?? []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>
          </>}
        </div>
        {!form.personal && <label className="check"><input type="checkbox" checked={form.preferred} onChange={(e) => setForm({ ...form, preferred: e.target.checked })} /> Preferencial (desempata modelos da mesma regra)</label>}
        <p className="field-hint">Campos dinâmicos (preenchidos com os dados do exame): {Object.keys(list.data?.fields ?? {}).map((f) => `{{${f}}}`).join("  ")}</p>
        <RichEditor label="Técnica" rows={3} value={form.technique} onChange={(h) => setForm((f) => ({ ...f, technique: h }))} />
        <RichEditor label="Achados" rows={5} value={form.findings} onChange={(h) => setForm((f) => ({ ...f, findings: h }))} />
        <RichEditor label="Conclusão" rows={3} value={form.conclusion} onChange={(h) => setForm((f) => ({ ...f, conclusion: h }))} />
        <fieldset className="panel-inset" aria-label="Bloco de assinatura">
          <legend>Bloco de assinatura no PDF</legend>
          <p className="field-hint">Aparece só no laudo liberado. Rascunhos nunca têm assinatura. A imagem só entra se o próprio médico que liberou autorizou o uso.</p>
          <div className="grid2">
            <Field label="Posição"><select value={block.position} onChange={(e) => setBlock({ ...block, position: e.target.value as Block["position"] })}>
              <option value="block">Bloco profissional após o texto</option><option value="footer">Rodapé da última página</option></select></Field>
            <Field label="Alinhamento"><select value={block.align} onChange={(e) => setBlock({ ...block, align: e.target.value as Block["align"] })}>
              <option value="left">Esquerda</option><option value="center">Centro</option><option value="right">Direita</option></select></Field>
            <Field label={`Altura da imagem: ${block.height_mm} mm`} hint="Largura proporcional">
              <input type="range" min={8} max={30} value={block.height_mm} aria-label="Altura da imagem da assinatura"
                onChange={(e) => setBlock({ ...block, height_mm: Number(e.target.value) })} /></Field>
          </div>
          <div className="filters">
            {([["show_image", "Imagem da assinatura manuscrita"], ["show_name", "Nome completo"], ["show_crm", "CRM e UF"],
              ["show_specialty", "Especialidade"], ["show_rqe", "RQE"]] as [keyof Block, string][]).map(([k, label]) => (
              <label key={k} className="check"><input type="checkbox" checked={Boolean(block[k])}
                onChange={(e) => setBlock({ ...block, [k]: e.target.checked })} /> {label}</label>))}
          </div>
        </fieldset>
        <div className="row-actions">
          <button className="primary" disabled={act.busy}>Salvar rascunho</button>
          {form.id && <button type="button" className="link" onClick={() => { setForm(empty); setReviewed(false); }}>Novo modelo</button>}
          {form.id && current?.personal && <button type="button" className="link" disabled={act.busy} onClick={() => void propose()}>Oferecer cópia à instituição</button>}
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

type PhraseItem = Phrase & { modality: string | null; active: boolean; text: string; phrase_shortcut: string | null;
  my_shortcut: string | null };

/** Frases rápidas: as pessoais do médico e (com permissão) as da instituição; busca, categorias, favoritas,
 * duplicar e atalho próprio. Campos: {{paciente.nome}} (dados do exame) e [[rótulo]] (preenchido ao inserir). */
function Phrases({ me }: { me: Me }) {
  const can = (p: string) => me.permissions.includes(p);
  const [filter, setFilter] = useState({ q: "", category: "", favorites: false });
  const list = useLoad(async () => {
    const q = new URLSearchParams({ include_inactive: "true" });
    if (filter.q) q.set("q", filter.q);
    if (filter.category) q.set("category", filter.category);
    if (filter.favorites) q.set("favorites", "true");
    return await get<{ items: PhraseItem[]; categories: string[] }>(`/report/phrases?${q}`);
  }, [filter]);
  const empty = { id: "", title: "", shortcut: "", modality: "", category: "", body: "", active: true, personal: can("report.phrases.own") };
  const [form, setForm] = useState(empty);
  const [mine, setMine] = useState<{ id: string; shortcut: string } | null>(null);
  const act = useAction();
  const editable = (p: PhraseItem) => (p.personal ? can("report.phrases.own") : can("report.phrases.manage"));
  async function save(e: FormEvent) {
    e.preventDefault();
    await act.run(async () => {
      const body = { title: form.title, shortcut: form.shortcut || null, modality: form.modality || null, category: form.category || null,
        body: form.body, active: form.active, personal: form.personal };
      if (form.id) await put(`/report/phrases/${form.id}`, body); else await post("/report/phrases", body);
      setForm(empty); await list.reload();
    }, "Frase salva.");
  }
  async function remove(id: string) {
    await act.run(async () => { await del(`/report/phrases/${id}`); setForm(empty); await list.reload(); }, "Frase excluída.");
  }
  async function duplicate(p: PhraseItem) {
    await act.run(async () => {
      const d = await post<PhraseItem>(`/report/phrases/${p.id}/duplicate`, {});
      await list.reload();
      setForm({ id: d.id, title: d.title, shortcut: "", modality: d.modality ?? "", category: d.category ?? "", body: d.body, active: true, personal: true });
    }, "Cópia pessoal criada: personalize e salve.");
  }
  async function pref(p: PhraseItem, body: Record<string, unknown>, ok: string) {
    await act.run(async () => { await put(`/report/phrases/${p.id}/prefs`, body); setMine(null); await list.reload(); }, ok);
  }
  const items = list.data?.items ?? [];
  return (
    <section className="panel" aria-label="Frases rápidas">
      <h2>Frases rápidas</h2>
      <p className="field-hint">No editor do laudo: lista “Inserir frase…” ou atalho seguido de espaço. Use {"{{paciente.nome}}"} e outros campos do exame
        (preenchidos ao inserir) e [[rótulo]] para campos que você completa na hora (ex.: [[medida em mm]]). Frases pessoais só você vê.</p>
      {act.view}
      <form className="filters" role="search" aria-label="Buscar frases" onSubmit={(e) => e.preventDefault()}>
        <input aria-label="Buscar frase" placeholder="Buscar por título, atalho ou texto" value={filter.q}
          onChange={(e) => setFilter({ ...filter, q: e.target.value })} />
        <select aria-label="Categoria" value={filter.category} onChange={(e) => setFilter({ ...filter, category: e.target.value })}>
          <option value="">Todas as categorias</option>
          {(list.data?.categories ?? []).map((c) => <option key={c} value={c}>{c}</option>)}</select>
        <label className="check"><input type="checkbox" checked={filter.favorites}
          onChange={(e) => setFilter({ ...filter, favorites: e.target.checked })} /> Só favoritas</label>
      </form>
      <ul className="history" aria-label="Lista de frases">{items.map((p) => (
        <li key={p.id}>
          <button type="button" className="link" aria-label={`${p.favorite ? "Desmarcar" : "Marcar"} favorita: ${p.title}`}
            onClick={() => void pref(p, { favorite: !p.favorite }, p.favorite ? "Removida das favoritas." : "Marcada como favorita.")}>{p.favorite ? "★" : "☆"}</button>
          {" "}{p.category ? `${p.category} › ` : ""}<strong>{p.title}</strong>
          {p.shortcut && <code> {p.shortcut}</code>}{p.my_shortcut && <span className="field-hint"> (meu atalho)</span>}
          {p.modality ? ` (${p.modality})` : ""}<span className="tag">{p.personal ? "minha" : "instituição"}</span>{p.active ? "" : " — inativa"}
          <span className="row-actions">
            {editable(p) && <button type="button" className="link" onClick={() => setForm({ id: p.id, title: p.title, shortcut: p.phrase_shortcut ?? "",
              modality: p.modality ?? "", category: p.category ?? "", body: p.body, active: p.active, personal: p.personal })}>Editar</button>}
            {can("report.phrases.own") && <button type="button" className="link" onClick={() => void duplicate(p)}>Duplicar</button>}
            {!p.personal && <button type="button" className="link" onClick={() => setMine({ id: p.id, shortcut: p.my_shortcut ?? "" })}>Meu atalho</button>}
            {editable(p) && <button type="button" className="link" onClick={() => void remove(p.id)}>Excluir</button>}
          </span>
          {mine?.id === p.id && (
            <span className="filters" role="group" aria-label={`Meu atalho para ${p.title}`}>
              <input aria-label="Meu atalho" placeholder="/atalho" maxLength={31} value={mine.shortcut}
                onChange={(e) => setMine({ ...mine, shortcut: e.target.value.toLowerCase() })} />
              <button type="button" onClick={() => void pref(p, mine.shortcut ? { shortcut: mine.shortcut } : { clear_shortcut: true }, "Atalho pessoal salvo.")}>Salvar atalho</button>
              <button type="button" className="link" onClick={() => setMine(null)}>Cancelar</button>
            </span>)}
        </li>))}
      </ul>
      {!list.loading && items.length === 0 && <p className="empty">Nenhuma frase encontrada.</p>}
      <form onSubmit={save} aria-label="Editar frase">
        {!form.id && can("report.phrases.own") && can("report.phrases.manage") && (
          <label className="check"><input type="checkbox" checked={!form.personal} onChange={(e) => setForm({ ...form, personal: !e.target.checked })} />
            {" "}Frase da instituição (todos os médicos usam)</label>)}
        <div className="grid2">
          <Field label="Título da frase"><input required maxLength={120} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
          <Field label="Atalho" hint="Ex.: /normal"><input maxLength={31} value={form.shortcut} onChange={(e) => setForm({ ...form, shortcut: e.target.value.toLowerCase() })} /></Field>
          <Field label="Categoria" hint="Ex.: Abdome, Tórax"><input maxLength={60} list="phrase-categories" value={form.category}
            onChange={(e) => setForm({ ...form, category: e.target.value })} /></Field>
          <Field label="Modalidade da frase" hint="Vazio = todas"><input maxLength={16} value={form.modality} onChange={(e) => setForm({ ...form, modality: e.target.value.toUpperCase() })} /></Field>
        </div>
        <datalist id="phrase-categories">{(list.data?.categories ?? []).map((c) => <option key={c} value={c} />)}</datalist>
        <RichEditor label="Texto da frase" rows={4} value={form.body} onChange={(h) => setForm((f) => ({ ...f, body: h }))} />
        <label className="check"><input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} /> Ativa</label>
        <div className="row-actions">
          <button className="primary" disabled={act.busy}>Salvar frase</button>
          {form.id && <button type="button" className="link" onClick={() => setForm(empty)}>Nova frase</button>}
        </div>
      </form>
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
