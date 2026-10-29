import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { blob, del, errorText, fmtDate, get, post, upload } from "../api";
import { Notice, useAction, useLoad } from "../ui";
import { OpenImages } from "../viewer";

export type PrepDetail = {
  study_id: string; study_instance_uid: string;
  patient: { name: string | null; identifier: string | null; birth_date: string | null; sex: string | null };
  encounter: string | null; accession: string | null; modality: string | null; description: string | null;
  institution: string | null; site: string | null; physician: string | null; due_at: string | null;
  priority: string; stage: string; stage_label: string; reason: string | null;
  checklist: { code: string; label: string; required: boolean; done: boolean; by: string | null }[];
  system_checks: { code: string; label: string; ok: boolean; detail?: string }[];
  duplicates: { study_id: string; accession: string | null; modality: string | null; study_date: string | null; reason: string }[];
  duplicate_checked: boolean;
  attachments: { id: string; kind: string; media_type: string; filename: string; size: number; by: string; at: string }[];
  comments: { id: string; author: string; text: string; at: string; institution: string | null; unread: boolean }[];
  flags: { id: string; code: string; label: string; note: string | null; status: string; by: string; at: string; resolved_by: string | null }[];
  shares: { id: string; user_id: string; scope: string; expires_at: string }[];
  flag_types: Record<string, string>;
  can: Record<"prepare" | "priority" | "cancel" | "share" | "assign" | "return" | "viewer", boolean>;
};

export const PRIORITY: Record<string, string> = { routine: "Rotina", urgent: "Urgente", stat: "Imediato" };
const TECH_FLAGS = ["missing_images", "incomplete_series", "identity_mismatch", "artifacts", "acquisition", "transmission", "duplicate", "other"];

/** Ícones de traço simples (desenho próprio do VYONIX). */
const ICON: Record<string, string> = {
  viewer: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zm10 3a3 3 0 100-6 3 3 0 000 6z",
  audio: "M12 3a3 3 0 00-3 3v6a3 3 0 006 0V6a3 3 0 00-3-3zM5 11a7 7 0 0014 0M12 18v3",
  photo: "M4 7h3l2-2h6l2 2h3v12H4zM12 17a4 4 0 100-8 4 4 0 000 8z",
  attach: "M16 7l-7.5 7.5a2.5 2.5 0 003.5 3.5L19 11a4.5 4.5 0 00-6.4-6.4L5 12",
  comment: "M4 5h16v11H9l-5 4z",
  priority: "M12 7v5l3 2M12 21a9 9 0 110-18 9 9 0 010 18z",
  checklist: "M9 4h6v3H9zM6 6h12v15H6zM9 13l2 2 4-4",
  duplicate: "M8 8h11v11H8zM5 5h11M5 5v11",
  doctor: "M12 12a4 4 0 100-8 4 4 0 000 8zM4 21a8 8 0 0116 0",
  share: "M18 8a3 3 0 10-2.8-4M6 15a3 3 0 100-6 3 3 0 000 6zM18 21a3 3 0 100-6 3 3 0 000 6zM8.6 13.5l6.8 4M15.4 6.5l-6.8 4",
  flag: "M12 3l10 18H2zM12 10v5M12 18v.5",
  cancel: "M5 7h14M10 7V4h4v3M7 7l1 14h8l1-14",
  timeline: "M6 4v16M6 7h4M6 12h8M6 17h6M18 7a1 1 0 100 .1",
  priors: "M4 6h10v13H4zM8 3h12v13",
};

function Icon({ name }: { name: string }) {
  return <svg viewBox="0 0 24 24" aria-hidden="true" className="ico"><path d={ICON[name]} /></svg>;
}

function Row({ icon, label, badge, tone, onClick, href }: { icon: string; label: string; badge?: ReactNode; tone?: "warn" | "danger";
  onClick?: () => void; href?: string }) {
  const inner = <><span className="act-ico"><Icon name={icon} /></span><span className="act-label">{label}</span>
    {badge}<span className="act-go" aria-hidden="true">›</span></>;
  return href
    ? <a className={`act ${tone ?? ""}`} href={href} target="_blank" rel="noopener">{inner}</a>
    : <button type="button" className={`act ${tone ?? ""}`} onClick={onClick}>{inner}</button>;
}

/** Preparação do estudo: cabeçalho + ações. No celular ocupa a tela; no computador abre ao lado da lista. */
export function PrepSheet({ studyId, onClose, onChanged }: { studyId: string; onClose: () => void; onChanged: () => void }) {
  const d = useLoad(async () => await get<PrepDetail>(`/ris/prep/${studyId}`), [studyId]);
  const [tool, setTool] = useState<string | null>(null);
  const act = useAction();
  const x = d.data;
  async function reload() { await d.reload(); onChanged(); }
  async function run(fn: () => Promise<unknown>, ok: string, close = true) {
    const done = await act.run(async () => { await fn(); await reload(); }, ok);
    if (done && close) setTool(null);
    return done;
  }
  const openFlags = x?.flags.filter((f) => f.status === "open") ?? [];
  const unread = x?.comments.filter((c) => c.unread).length ?? 0;
  const ready = x ? x.system_checks.every((c) => c.ok) && x.checklist.every((i) => !i.required || i.done) : false;
  const closed = x ? ["cancelled", "reported"].includes(x.stage) : true;
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <section className="sheet" role="dialog" aria-modal="true" aria-label="Preparação do estudo" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-grip" aria-hidden="true" />
        <button type="button" className="sheet-close link" onClick={onClose}>Fechar</button>
        <Notice kind="error">{d.error}</Notice>
        {x && <>
          <header className="sheet-head">
            <h2>{x.patient.name ?? "Paciente não identificado"}</h2>
            <p>{[x.modality, x.description].filter(Boolean).join(" · ") || "Exame"}</p>
            <p className="sub">{[x.patient.identifier, x.encounter && `Atendimento ${x.encounter}`, x.accession && `Acesso ${x.accession}`].filter(Boolean).join(" · ")}</p>
            <p className="sub">{[x.institution, x.site && `Unidade: ${x.site}`].filter(Boolean).join(" · ")}</p>
            <p className="sub">Médico: {x.physician ?? "não atribuído"}</p>
            <div className="sheet-tags">
              <span className={`pill pill-${x.priority}`}>{PRIORITY[x.priority] ?? x.priority}</span>
              <span className={`pill stage-${x.stage}`}>{x.stage_label}</span>
              {x.due_at && <span className="pill">Prazo: {fmtDate(x.due_at)}</span>}
            </div>
            {x.reason && <Notice kind="warn">{x.stage === "returned" ? "Devolvido: " : "Motivo: "}{x.reason}</Notice>}
          </header>
          {act.view}
          {tool === null && (
            <nav className="acts" aria-label="Ações do estudo">
              {x.can.viewer && <div className="act act-images"><span className="act-ico"><Icon name="viewer" /></span><OpenImages studyUid={x.study_instance_uid} /></div>}
              {x.can.prepare && !closed && <Row icon="audio" label="Gravar áudio" onClick={() => setTool("audio")} />}
              {x.can.prepare && !closed && <Row icon="photo" label="Fotografar documento" onClick={() => setTool("photo")} />}
              <Row icon="attach" label="Anexos" onClick={() => setTool("attach")}
                badge={x.attachments.length ? <span className="count">{x.attachments.length}</span> : undefined} />
              <Row icon="comment" label="Comentários" onClick={() => { setTool("comment"); void post(`/ris/prep/${studyId}/read`).then(reload); }}
                badge={<>{unread > 0 && <span className="count count-new" title="Não lidos">{unread} novo(s)</span>}
                  {x.comments.length > 0 && <span className="count">{x.comments.length}</span>}</>} />
              <Row icon="priority" label={x.can.priority ? "Alterar prioridade" : "Solicitar mudança de prioridade"} onClick={() => setTool("priority")} />
              {x.can.prepare && <Row icon="checklist" label="Preparação do estudo" onClick={() => setTool("checklist")}
                badge={<span className={`count ${ready ? "count-ok" : ""}`}>{ready ? "pronto" : `${x.checklist.filter((i) => i.done).length}/${x.checklist.length}`}</span>} />}
              {x.can.prepare && <Row icon="duplicate" label="Duplicidade de exame" onClick={() => setTool("duplicate")}
                badge={x.duplicates.length > 0 && !x.duplicate_checked ? <span className="count count-warn">{x.duplicates.length} possível</span> : undefined} />}
              <Row icon="doctor" label={x.can.assign ? "Trocar médico" : "Solicitar troca de médico"} onClick={() => setTool("doctor")} />
              {x.can.share && <Row icon="share" label="Compartilhar exame" onClick={() => setTool("share")}
                badge={x.shares.length ? <span className="count">{x.shares.length}</span> : undefined} />}
              {x.can.prepare && <Row icon="flag" label="Sinalizar suspeita técnica" tone="warn" onClick={() => setTool("flag")}
                badge={openFlags.length ? <span className="count count-warn">{openFlags.length}</span> : undefined} />}
              {x.can.return && x.stage === "forwarded" || x.can.return && x.stage === "assigned"
                ? <Row icon="cancel" label="Devolver para correção" tone="warn" onClick={() => setTool("return")} /> : null}
              <Row icon="priors" label="Exames anteriores" onClick={() => setTool("priors")} />
              <Row icon="timeline" label="Linha do tempo do exame" onClick={() => setTool("timeline")} />
              {x.can.cancel && !closed && <Row icon="cancel" label="Cancelar exame" tone="danger" onClick={() => setTool("cancel")} />}
            </nav>)}
          {tool !== null && <button type="button" className="link back" onClick={() => setTool(null)}>‹ Voltar às ações</button>}
          {tool === "timeline" && <Timeline studyId={studyId} />}
          {tool === "priors" && <Priors studyId={studyId} />}
          {tool === "audio" && <AudioTool studyId={studyId} onSaved={() => run(async () => undefined, "Áudio anexado ao estudo.")} />}
          {tool === "photo" && <FileTool studyId={studyId} kind="photo" capture onSaved={() => run(async () => undefined, "Foto anexada.")} />}
          {tool === "attach" && <Attachments d={x} studyId={studyId} onSaved={() => run(async () => undefined, "Anexo incluído.", false)} />}
          {tool === "comment" && <Comments d={x} studyId={studyId} onSaved={() => run(async () => undefined, "Comentário registrado.", false)} />}
          {tool === "priority" && <PriorityTool d={x} onDo={(p, why) => x.can.priority
            ? run(() => post(`/ris/prep/${studyId}/priority`, { priority: p, reason: why || null }), "Prioridade alterada.")
            : run(() => post(`/ris/prep/${studyId}/flags`, { code: "priority_request", note: `${PRIORITY[p]}: ${why}` }), "Solicitação registrada para a coordenação.")} />}
          {tool === "checklist" && <Checklist d={x} studyId={studyId} run={run} />}
          {tool === "duplicate" && <Duplicates d={x} studyId={studyId} run={run} />}
          {tool === "doctor" && <DoctorTool d={x} studyId={studyId} run={run} />}
          {tool === "share" && <ShareTool d={x} studyId={studyId} run={run} />}
          {tool === "flag" && <FlagTool d={x} studyId={studyId} run={run} />}
          {tool === "return" && <ReasonTool label="O que precisa ser corrigido" button="Devolver ao técnico"
            onDo={(r) => run(() => post(`/ris/prep/${studyId}/return`, { reason: r }), "Estudo devolvido para correção.")} />}
          {tool === "cancel" && <ReasonTool label="Justificativa do cancelamento" button="Confirmar cancelamento" danger
            note="O estudo DICOM e todo o histórico são preservados; o exame sai das filas."
            onDo={(r) => run(() => post(`/ris/prep/${studyId}/cancel`, { reason: r }), "Exame cancelado.")} />}
        </>}
      </section>
    </div>
  );
}

type PriorItem = { study_id: string; study_date: string | null; modality: string | null; description: string | null;
  accession: string | null; same_modality: boolean; study_instance_uid: string | null; restricted?: boolean;
  report: null | { id: string; status: "draft" | "final"; finalized_at: string | null } };

/** Exames anteriores do mesmo paciente (índice local), para comparação. */
export function Priors({ studyId, compact = false }: { studyId: string; compact?: boolean }) {
  const p = useLoad(() => get<{ patient_linked: boolean; items: PriorItem[] }>(`/ris/studies/${studyId}/priors`), [studyId]);
  const items = p.data?.items ?? [];
  return (
    <section aria-label="Exames anteriores" className={compact ? "priors compact" : "priors"}>
      {compact && <h3 className="h3">Exames anteriores</h3>}
      <Notice kind="error">{p.error}</Notice>
      {p.data && !p.data.patient_linked && <p className="empty">Estudo ainda sem paciente identificado: concilie para ver os anteriores.</p>}
      {p.data?.patient_linked && items.length === 0 && <p className="empty">Nenhum exame anterior deste paciente.</p>}
      {items.length > 0 && <ul className="prior-list">{items.map((x) => (
        <li key={x.study_id} className={x.same_modality ? "same" : ""}>
          <span><strong>{x.modality ?? "—"}</strong> {x.study_date ? x.study_date.split("-").reverse().join("/") : "sem data"}
            {x.description ? ` · ${x.description}` : ""}{x.same_modality && <span className="pill">mesma modalidade</span>}</span>
          <span className="prior-acts">
            {x.restricted ? <span className="sub">unidade sem vínculo</span> : <>
              {x.study_instance_uid && <OpenImages studyUid={x.study_instance_uid} compact />}
              {x.report?.status === "final" ? <a href={`/api/v1/report/reports/${x.report.id}/pdf`} target="_blank" rel="noopener">Laudo (PDF)</a>
                : <span className="sub">{x.report ? "laudo em rascunho" : "sem laudo"}</span>}</>}
          </span>
        </li>))}</ul>}
    </section>
  );
}

type TL = { current_name: string; stages: { code: string; name: string; done: boolean }[];
  events: { stage: string; stage_name: string; at: string; by: string | null; text: string; detail: string | null }[] };

function Timeline({ studyId }: { studyId: string }) {
  const t = useLoad(() => get<TL>(`/ris/studies/${studyId}/timeline`), [studyId]);
  return (
    <section aria-label="Linha do tempo do exame">
      <Notice kind="error">{t.error}</Notice>
      {t.data && <>
        <ol className="stage-strip" aria-label="Etapas">
          {t.data.stages.map((st) => <li key={st.code} className={st.done ? "done" : ""}>{st.name}</li>)}
        </ol>
        <ol className="timeline">
          {t.data.events.map((e, i) => (
            <li key={i}><span className="tl-when">{fmtDate(e.at)}</span>
              <span className="tl-what"><strong>{e.text}</strong>{e.detail ? ` — ${e.detail}` : ""}
                <span className="sub"> {e.stage_name}{e.by ? ` · ${e.by}` : ""}</span></span></li>))}
        </ol>
      </>}
    </section>
  );
}

function AudioTool({ studyId, onSaved }: { studyId: string; onSaved: () => void }) {
  const [rec, setRec] = useState<MediaRecorder | null>(null);
  const [clip, setClip] = useState<Blob | null>(null);
  const [err, setErr] = useState("");
  const chunks = useRef<Blob[]>([]);
  const url = clip ? URL.createObjectURL(clip) : null;
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);
  async function start() {
    setErr("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const r = new MediaRecorder(stream);
      chunks.current = [];
      r.ondataavailable = (e) => chunks.current.push(e.data);
      r.onstop = () => { setClip(new Blob(chunks.current, { type: r.mimeType || "audio/webm" })); stream.getTracks().forEach((t) => t.stop()); };
      r.start(); setRec(r);
    } catch { setErr("Microfone indisponível ou não autorizado neste navegador."); }
  }
  async function send() {
    if (!clip) return;
    try { await upload(`/ris/prep/${studyId}/attachments?kind=audio&filename=observacao-tecnica`, clip); onSaved(); }
    catch (e) { setErr(errorText(e)); }
  }
  return (
    <div className="tool">
      <h3>Gravar observação em áudio</h3>
      <p className="field-hint">Fica anexada ao estudo para a equipe ouvir. Não é transcrita nem vira texto clínico automaticamente.</p>
      <Notice kind="error">{err}</Notice>
      {!rec && <button className="primary" onClick={() => void start()}>Começar a gravar</button>}
      {rec && rec.state === "recording" && <button className="primary" onClick={() => { rec.stop(); setRec(null); }}>Parar</button>}
      {url && <><audio controls src={url} /><button className="primary" onClick={() => void send()}>Anexar áudio</button></>}
    </div>
  );
}

function FileTool({ studyId, kind, capture, onSaved }: { studyId: string; kind: "photo" | "document"; capture?: boolean; onSaved: () => void }) {
  const [err, setErr] = useState("");
  async function pick(f: File | undefined) {
    if (!f) return;
    setErr("");
    try { await upload(`/ris/prep/${studyId}/attachments?kind=${kind}&filename=${encodeURIComponent(f.name)}`, f); onSaved(); }
    catch (e) { setErr(errorText(e)); }
  }
  return (
    <div className="tool">
      <h3>{kind === "photo" ? "Fotografar documento" : "Incluir arquivo"}</h3>
      <p className="field-hint">{kind === "photo" ? "No celular, abre a câmera. Pedido médico, termo ou documento autorizado (JPEG, PNG ou WEBP)."
        : "PDF, JPEG, PNG ou WEBP, até 10 MB."}</p>
      <Notice kind="error">{err}</Notice>
      <label className="filepick">
        <input type="file" aria-label={kind === "photo" ? "Foto do documento" : "Arquivo do anexo"}
          accept={kind === "photo" ? "image/*" : "application/pdf,image/jpeg,image/png,image/webp"}
          {...(capture ? { capture: "environment" } : {})} onChange={(e) => void pick(e.target.files?.[0])} />
      </label>
    </div>
  );
}

function Attachments({ d, studyId, onSaved }: { d: PrepDetail; studyId: string; onSaved: () => void }) {
  const [open, setOpen] = useState<{ id: string; url: string; type: string } | null>(null);
  useEffect(() => () => { if (open) URL.revokeObjectURL(open.url); }, [open]);
  async function view(id: string, type: string) {
    const b = await blob("GET", `/ris/prep/attachments/${id}`);
    setOpen({ id, url: URL.createObjectURL(b), type });
  }
  return (
    <div className="tool">
      <h3>Anexos</h3>
      {d.can.prepare && <FileTool studyId={studyId} kind="document" onSaved={onSaved} />}
      <ul className="history">{d.attachments.map((a) => (
        <li key={a.id}>{({ document: "Documento", photo: "Foto", audio: "Áudio" } as Record<string, string>)[a.kind]} — {a.filename}
          {" "}({Math.ceil(a.size / 1024)} KB) · {a.by}, {fmtDate(a.at)} <button className="link" onClick={() => void view(a.id, a.media_type)}>Abrir</button></li>))}
        {!d.attachments.length && <li>Nenhum anexo.</li>}
      </ul>
      {open && (open.type.startsWith("audio/") ? <audio controls src={open.url} />
        : open.type.startsWith("image/") ? <img className="att-view" src={open.url} alt="Anexo" />
          : <a className="button" href={open.url} target="_blank" rel="noopener">Abrir o PDF</a>)}
    </div>
  );
}

function Comments({ d, studyId, onSaved }: { d: PrepDetail; studyId: string; onSaved: () => void }) {
  const [text, setText] = useState("");
  const act = useAction();
  async function send(e: FormEvent) {
    e.preventDefault();
    if (await act.run(() => post(`/ris/prep/${studyId}/comments`, { text }))) { setText(""); onSaved(); }
  }
  return (
    <div className="tool">
      <h3>Comentários</h3>
      <ul className="comments">{d.comments.map((c) => (
        <li key={c.id} className={c.unread ? "unread" : ""}><strong>{c.author}</strong> <span className="sub">{c.institution} · {fmtDate(c.at)}</span>
          {c.unread && <span className="count count-new">novo</span>}<p>{c.text}</p></li>))}
        {!d.comments.length && <li>Nenhum comentário.</li>}</ul>
      {act.view}
      <form onSubmit={send} aria-label="Novo comentário">
        <textarea rows={3} maxLength={2000} required aria-label="Comentário" value={text} onChange={(e) => setText(e.target.value)} />
        <button className="primary" disabled={act.busy}>Enviar comentário</button>
      </form>
    </div>
  );
}

function PriorityTool({ d, onDo }: { d: PrepDetail; onDo: (p: string, why: string) => void }) {
  const [p, setP] = useState(d.priority);
  const [why, setWhy] = useState("");
  return (
    <form className="tool" onSubmit={(e) => { e.preventDefault(); onDo(p, why); }} aria-label="Prioridade">
      <h3>{d.can.priority ? "Alterar prioridade" : "Solicitar mudança de prioridade"}</h3>
      <div className="segmented" role="radiogroup" aria-label="Prioridade">
        {Object.entries(PRIORITY).map(([k, v]) => <label key={k} className={p === k ? "on" : ""}>
          <input type="radio" name="prio" checked={p === k} onChange={() => setP(k)} /> {v}</label>)}
      </div>
      <input aria-label="Motivo" placeholder="Motivo" maxLength={250} required={!d.can.priority} value={why} onChange={(e) => setWhy(e.target.value)} />
      <button className="primary">{d.can.priority ? "Alterar" : "Enviar solicitação"}</button>
    </form>
  );
}

type Run = (fn: () => Promise<unknown>, ok: string, close?: boolean) => Promise<boolean>;

function Checklist({ d, studyId, run }: { d: PrepDetail; studyId: string; run: Run }) {
  const locked = !["received", "preparing", "pending", "returned"].includes(d.stage);
  const ready = d.system_checks.every((c) => c.ok) && d.checklist.every((i) => !i.required || i.done);
  return (
    <div className="tool">
      <h3>Verificações do sistema</h3>
      <ul className="checks">{d.system_checks.map((c) => <li key={c.code} className={c.ok ? "ok" : "no"}>{c.ok ? "✓" : "✗"} {c.label}{c.detail ? ` (${c.detail})` : ""}</li>)}</ul>
      <h3>Checklist da instituição</h3>
      <ul className="checks">{d.checklist.map((i) => (
        <li key={i.code}><label className="check"><input type="checkbox" checked={i.done} disabled={locked}
          onChange={(e) => void run(() => post(`/ris/prep/${studyId}/check`, { code: i.code, done: e.target.checked }), "Checklist atualizado.", false)} />
          {" "}{i.label}{i.required && <span className="req"> obrigatório</span>}</label></li>))}</ul>
      {!locked && <button className="primary" disabled={!ready}
        onClick={() => void run(() => post(`/ris/prep/${studyId}/forward`), "Estudo encaminhado à fila de laudos.")}>Encaminhar para laudo</button>}
      {!ready && !locked && <p className="field-hint">Conclua as verificações e os itens obrigatórios para encaminhar.</p>}
    </div>
  );
}

function Duplicates({ d, studyId, run }: { d: PrepDetail; studyId: string; run: Run }) {
  return (
    <div className="tool">
      <h3>Duplicidade de exame</h3>
      {!d.duplicates.length ? <p>Nenhum possível duplicado encontrado.</p> : <>
        <p className="field-hint">Indício automático; a decisão é sua e fica registrada. Nada é apagado.</p>
        <ul className="history">{d.duplicates.map((x) => (
          <li key={x.study_id}>{x.modality} {x.study_date ? fmtDate(x.study_date + "T12:00:00", false) : ""} {x.accession ?? ""} — {x.reason}
            {" "}<button className="link" onClick={() => void run(() => post(`/ris/prep/${studyId}/duplicate`, { duplicate_of: x.study_id }),
              "Marcado como duplicado: este exame foi cancelado e o original preservado.")}>É duplicado deste (cancelar este)</button></li>))}</ul>
        {!d.duplicate_checked && <button onClick={() => void run(() => post(`/ris/prep/${studyId}/duplicate`, {}), "Registrado: não é duplicado.")}>Não é duplicado</button>}
      </>}
    </div>
  );
}

function DoctorTool({ d, studyId, run }: { d: PrepDetail; studyId: string; run: Run }) {
  const docs = useLoad(async () => (d.can.assign ? (await get<{ items: { id: string; name: string }[] }>("/report/assignable-physicians")).items : []), []);
  const [pid, setPid] = useState("");
  const [why, setWhy] = useState("");
  return d.can.assign ? (
    <form className="tool" aria-label="Trocar médico" onSubmit={(e) => { e.preventDefault();
      void run(() => post("/report/assignments", { study_id: studyId, physician_id: pid, priority: d.priority }), "Exame atribuído ao médico."); }}>
      <h3>Trocar médico</h3>
      <select required aria-label="Médico" value={pid} onChange={(e) => setPid(e.target.value)}>
        <option value="">Selecione…</option>{(docs.data ?? []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
      <button className="primary">Atribuir</button>
    </form>) : (
    <form className="tool" aria-label="Solicitar troca de médico" onSubmit={(e) => { e.preventDefault();
      void run(() => post(`/ris/prep/${studyId}/flags`, { code: "doctor_change", note: why }), "Solicitação enviada à coordenação."); }}>
      <h3>Solicitar troca de médico</h3>
      <p className="field-hint">A reatribuição é feita pela coordenação, conforme as regras de distribuição.</p>
      <input required maxLength={300} aria-label="Motivo da troca" placeholder="Motivo" value={why} onChange={(e) => setWhy(e.target.value)} />
      <button className="primary">Enviar solicitação</button>
    </form>);
}

function ShareTool({ d, studyId, run }: { d: PrepDetail; studyId: string; run: Run }) {
  const users = useLoad(async () => await get<{ id: string; username: string; display_name: string }[]>("/users").catch(() => []), []);
  const [f, setF] = useState({ user_id: "", hours: 24 });
  return (
    <form className="tool" aria-label="Compartilhar exame" onSubmit={(e) => { e.preventDefault();
      void run(() => post(`/ris/prep/${studyId}/shares`, { ...f, scope: "view" }), "Exame compartilhado com prazo.", false); }}>
      <h3>Compartilhar exame</h3>
      <p className="field-hint">Acesso temporário de um profissional da instituição a este exame. Liberar laudo continua exigindo vínculo com a unidade.</p>
      <select required aria-label="Profissional" value={f.user_id} onChange={(e) => setF({ ...f, user_id: e.target.value })}>
        <option value="">Selecione…</option>{(users.data ?? []).map((u) => <option key={u.id} value={u.id}>{u.display_name} ({u.username})</option>)}</select>
      <select aria-label="Prazo" value={f.hours} onChange={(e) => setF({ ...f, hours: Number(e.target.value) })}>
        {[[2, "2 horas"], [24, "1 dia"], [72, "3 dias"], [168, "7 dias"]].map(([h, l]) => <option key={h} value={h}>{l}</option>)}</select>
      <button className="primary">Compartilhar</button>
      <ul className="history">{d.shares.map((s) => <li key={s.id}>{users.data?.find((u) => u.id === s.user_id)?.display_name ?? "Profissional"} até {fmtDate(s.expires_at)}
        {" "}<button type="button" className="link" onClick={() => void run(() => del(`/ris/prep/shares/${s.id}`), "Compartilhamento revogado.", false)}>Revogar</button></li>)}</ul>
    </form>
  );
}

function FlagTool({ d, studyId, run }: { d: PrepDetail; studyId: string; run: Run }) {
  const [f, setF] = useState({ code: "missing_images", note: "" });
  return (
    <div className="tool">
      <h3>Sinalizar suspeita técnica</h3>
      <p className="field-hint">Registro da equipe: o sistema não conclui sozinho. Suspeita aberta impede o encaminhamento até ser resolvida.</p>
      <form className="filters" aria-label="Nova sinalização" onSubmit={(e) => { e.preventDefault();
        void run(() => post(`/ris/prep/${studyId}/flags`, f), "Suspeita registrada.", false); }}>
        <select aria-label="Tipo" value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })}>
          {TECH_FLAGS.map((k) => <option key={k} value={k}>{d.flag_types[k]}</option>)}</select>
        <input aria-label="Observação" placeholder="Observação" maxLength={500} value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />
        <button className="primary">Registrar</button>
      </form>
      <ul className="history">{d.flags.map((x) => <li key={x.id}>{x.label}{x.note ? ` — ${x.note}` : ""} ({x.by}, {fmtDate(x.at)})
        {x.status === "open" ? <> <button className="link" onClick={() => void run(() => post(`/ris/prep/flags/${x.id}/resolve`), "Sinalização resolvida.", false)}>Resolver</button></>
          : <span className="sub"> — resolvida por {x.resolved_by}</span>}</li>)}</ul>
    </div>
  );
}

function ReasonTool({ label, button, note, danger, onDo }: { label: string; button: string; note?: string; danger?: boolean; onDo: (r: string) => void }) {
  const [r, setR] = useState("");
  const [sure, setSure] = useState(false);
  return (
    <form className="tool" onSubmit={(e) => { e.preventDefault(); onDo(r.trim()); }} aria-label={label}>
      <h3>{label}</h3>
      {note && <p className="field-hint">{note}</p>}
      <textarea rows={3} required maxLength={300} aria-label={label} value={r} onChange={(e) => setR(e.target.value)} />
      {danger && <label className="check"><input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} /> Confirmo esta ação</label>}
      <button className={danger ? "danger" : "primary"} disabled={!r.trim() || (danger && !sure)}>{button}</button>
    </form>
  );
}
