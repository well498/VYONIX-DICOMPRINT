import { useState } from "react";
import { fmtDate, get, patch, type Me } from "../api";
import { Notice, Page, useAction, useLoad } from "../ui";
import { PRIORITY, PrepSheet } from "./prep";

type PrepItem = { study_id: string; patient_name: string | null; accession: string | null; modality: string | null;
  description: string | null; received_at: string; station: string | null; images: number; incomplete: boolean;
  stage: string; priority: string; flags: string[]; attachments: number; unread_comments: number;
  physician: string | null; due_at: string | null; site_id: string | null };
type PrepQueue = { items: PrepItem[]; totals: Record<string, number>; stages: Record<string, string> };

const CARDS: [string, string][] = [["", "Recebidos"], ["awaiting", "Aguardando preparação"], ["incomplete", "Incompletos"],
  ["pending", "Com pendência"], ["urgent", "Urgentes"], ["forwarded", "Prontos para laudo"], ["assigned", "Encaminhados ao médico"],
  ["returned", "Devolvidos para correção"]];

/** Fila de preparação: tudo que chegou ao PACS, com etapa, pendências e acesso rápido às ações. */
export function PrepQueuePanel() {
  const [f, setF] = useState({ stage: "", date_from: "", date_to: "", modality: "", station: "", site_id: "", priority: "", patient: "", accession: "" });
  const [q, setQ] = useState(f);
  const [open, setOpen] = useState<string | null>(null);
  const [more, setMore] = useState(false);
  const sites = useLoad(async () => await get<{ id: string; name: string }[]>("/sites").catch(() => []), []);
  const list = useLoad(async () => {
    const p = new URLSearchParams(Object.entries(q).filter(([, v]) => v) as [string, string][]);
    return await get<PrepQueue>(`/ris/prep?${p}`);
  }, [q]);
  const d = list.data;
  const total = d ? Object.entries(d.totals).filter(([k]) => k in d.stages).reduce((a, [, v]) => a + v, 0) : 0;
  const pick = (stage: string) => { const n = { ...f, stage }; setF(n); setQ(n); };
  return (
    <section aria-label="Fila de preparação">
      <div className="card-row stage-cards" role="group" aria-label="Situação dos estudos">
        {CARDS.map(([k, label]) => (
          <button key={k || "all"} type="button" className={`card card-btn${q.stage === k ? " on" : ""}${["incomplete", "pending", "urgent", "returned"].includes(k) && d?.totals[k] ? " card-warn" : ""}`}
            aria-pressed={q.stage === k} onClick={() => pick(k)}>
            <span className="card-label">{label}</span><strong>{k ? d?.totals[k] ?? 0 : total}</strong></button>))}
      </div>
      <form className="filters exam-filters" role="search" aria-label="Filtrar estudos" onSubmit={(e) => { e.preventDefault(); setQ(f); }}>
        <input placeholder="Paciente" aria-label="Paciente" value={f.patient} onChange={(e) => setF({ ...f, patient: e.target.value })} />
        <input placeholder="Accession" aria-label="Accession" value={f.accession} onChange={(e) => setF({ ...f, accession: e.target.value })} />
        <input placeholder="Modalidade" aria-label="Modalidade" maxLength={16} value={f.modality} onChange={(e) => setF({ ...f, modality: e.target.value })} />
        <button type="button" className="link" onClick={() => setMore(!more)}>{more ? "Menos filtros" : "Mais filtros"}</button>
        {more && <>
          <input type="date" aria-label="Recebido de" value={f.date_from} onChange={(e) => setF({ ...f, date_from: e.target.value })} />
          <input type="date" aria-label="Recebido até" value={f.date_to} onChange={(e) => setF({ ...f, date_to: e.target.value })} />
          <input placeholder="Equipamento" aria-label="Equipamento" value={f.station} onChange={(e) => setF({ ...f, station: e.target.value })} />
          <select aria-label="Unidade" value={f.site_id} onChange={(e) => setF({ ...f, site_id: e.target.value })}>
            <option value="">Todas as unidades</option>{(sites.data ?? []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
          <select aria-label="Prioridade" value={f.priority} onChange={(e) => setF({ ...f, priority: e.target.value })}>
            <option value="">Todas as prioridades</option>{Object.entries(PRIORITY).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        </>}
        <button>Filtrar</button>
      </form>
      <Notice kind="error">{list.error}</Notice>
      <ul className="study-list" aria-label="Estudos">
        {(d?.items ?? []).map((x) => (
          <li key={x.study_id}>
            <button type="button" className="study" onClick={() => setOpen(x.study_id)} aria-label={`Preparar ${x.patient_name ?? "estudo"}`}>
              <span className="study-main"><strong>{x.patient_name ?? "Paciente não identificado"}</strong>
                <span className="sub">{[x.modality, x.description].filter(Boolean).join(" · ")} · {x.images} imagem(ns){x.station ? ` · ${x.station}` : ""}</span>
                <span className="sub">Recebido {fmtDate(x.received_at)}{x.accession ? ` · ${x.accession}` : ""}{x.physician ? ` · ${x.physician}` : ""}</span></span>
              <span className="study-tags">
                {x.priority !== "routine" && <span className={`pill pill-${x.priority}`}>{PRIORITY[x.priority]}</span>}
                <span className={`pill stage-${x.stage}`}>{d?.stages[x.stage]}</span>
                {x.incomplete && <span className="pill pill-warn">incompleto</span>}
                {x.flags.length > 0 && <span className="pill pill-warn">{x.flags.length} pendência(s)</span>}
                {x.unread_comments > 0 && <span className="count count-new">{x.unread_comments} comentário(s) novo(s)</span>}
              </span>
            </button>
          </li>))}
        {d && !d.items.length && <li className="empty">Nenhum estudo com esses filtros.</li>}
      </ul>
      {open && <PrepSheet studyId={open} onClose={() => setOpen(null)} onChanged={() => void list.reload()} />}
    </section>
  );
}

type Exam = { schedule_id: string; status: string; patient_name: string; patient_id: string; modality: string;
  station_aet: string | null; room: string | null; description: string | null; scheduled_at: string; accession: string;
  mpps_status: string | null; images: { expected: number; received: number } | null; study_instance_uid: string };
type Panel = { day: string; exams: Exam[]; exam_counts: Record<string, number>; incomplete_transfers: number;
  reception_failures: { at: string; reason: string | null; via: string | null; source: string }[];
  received?: { study_uid: string; patient_name: string; accession: string | null; description: string | null; instances: number; received_at: string }[];
  quality_issues?: { study_uid: string; accession: string | null; possibly_incomplete: boolean; reconciled: boolean; issues: string[] }[] };

const STATUS: Record<string, string> = { scheduled: "Agendado", arrived: "Paciente chegou", in_progress: "Em realização",
  received: "Imagens recebidas", completed: "Concluído", cancelled: "Cancelado" };
const ISSUE: Record<string, string> = { no_order: "sem pedido conciliado", instance_gap: "lacuna na numeração",
  instance_repeated: "numeração repetida", receiving: "recepção em andamento", no_accession: "sem número de acesso" };

function iso(d: Date) { return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; }
function pn(n: string) { const [f, g] = (n || "").split("^"); return g ? `${g} ${f}`.trim() : f || "—"; }
function hour(s: string) { return new Date(s).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }); }

/** Painel do Técnico em Radiologia: exames do dia, recepção DICOM e pendências. Não emite nem libera laudos. */
export function TechnicianPage({ me }: { me: Me }) {
  const [day, setDay] = useState(iso(new Date()));
  const p = useLoad(async () => await get<Panel>(`/ris/technician-panel?day=${day}`), [day]);
  const act = useAction();
  const canPerform = me.permissions.includes("ris.exam.perform") || me.permissions.includes("ris.schedule.manage");
  const canView = me.permissions.includes("pacs.studies.read");
  async function move(e: Exam, status: string, label: string) {
    await act.run(async () => { await patch(`/ris/schedules/${e.schedule_id}/status`, { status }); await p.reload(); },
      `${e.patient_name}: ${label}.`);
  }
  const d = p.data;
  const c = d?.exam_counts ?? {};
  return (
    <Page title="Painel do técnico" intro="Receba, confira, prepare e encaminhe os estudos para laudo. A emissão e a liberação de laudos são exclusivas dos médicos."
      actions={<input type="date" aria-label="Dia" value={day} onChange={(e) => setDay(e.target.value)} />}>
      {act.view}
      {me.permissions.includes("ris.exam.prepare") && <PrepQueuePanel />}
      <h2 className="section">Agenda do dia</h2>
      <Notice kind="error">{p.error}</Notice>
      {d && <div className="card-row" role="group" aria-label="Resumo do dia">
        <div className="card"><span className="card-label">A realizar</span><strong>{(c.scheduled ?? 0) + (c.arrived ?? 0)}</strong></div>
        <div className="card"><span className="card-label">Em realização</span><strong>{c.in_progress ?? 0}</strong></div>
        <div className="card"><span className="card-label">Concluídos / imagens recebidas</span><strong>{(c.completed ?? 0) + (c.received ?? 0)}</strong></div>
        {d.received && <div className="card"><span className="card-label">Estudos recebidos no PACS</span><strong>{d.received.length}</strong></div>}
        <div className={`card${d.reception_failures.length ? " card-warn" : ""}`}><span className="card-label">Recusas na recepção DICOM</span><strong>{d.reception_failures.length}</strong></div>
        <div className="card"><span className="card-label">Transferências incompletas (MPPS)</span><strong>{d.incomplete_transfers}</strong></div>
      </div>}
      <h3>Exames agendados</h3>
      <div className="table-wrap"><table>
        <thead><tr><th>Hora</th><th>Paciente</th><th>Exame</th><th>Sala / estação</th><th>Situação</th>{canPerform && <th>Ações</th>}</tr></thead>
        <tbody>{(d?.exams ?? []).map((e) => (
          <tr key={e.schedule_id}>
            <td className="nowrap">{hour(e.scheduled_at)}</td>
            <td>{e.patient_name}<br /><span className="field-hint">{e.patient_id} · {e.accession}</span></td>
            <td>{e.modality} {e.description ?? ""}</td>
            <td>{[e.room, e.station_aet].filter(Boolean).join(" · ") || "—"}</td>
            <td>{STATUS[e.status] ?? e.status}{e.mpps_status && <span className="tag" title="Informado pela modalidade (MPPS)">modalidade: {e.mpps_status.toLowerCase()}</span>}
              {e.images && <span className={`tag${e.images.received < e.images.expected ? " tag-warn" : ""}`}>imagens {e.images.received}/{e.images.expected}</span>}
              {canView && ["received", "completed"].includes(e.status) && <> <a href={`/viewer/viewer?StudyInstanceUIDs=${encodeURIComponent(e.study_instance_uid)}`} target="_blank" rel="noopener">Viewer</a></>}</td>
            {canPerform && <td className="actions"><div className="row-actions">
              {e.status === "scheduled" && <button onClick={() => void move(e, "arrived", "chegada registrada")}>Chegou</button>}
              {["scheduled", "arrived"].includes(e.status) && <button onClick={() => void move(e, "in_progress", "exame iniciado")}>Iniciar</button>}
              {["in_progress", "received"].includes(e.status) && <button onClick={() => void move(e, "completed", "exame concluído")}>Concluir</button>}
            </div></td>}
          </tr>))}</tbody>
      </table>{d && !d.exams.length && <p className="empty">Nenhum exame agendado para o dia.</p>}</div>
      {d?.received && <>
        <h2 className="section">Recebidos pelo PACS</h2>
        <ul className="history">{d.received.map((r) => <li key={r.study_uid}>{fmtDate(r.received_at)} — {pn(r.patient_name)} — {r.description ?? "estudo"} {r.accession ?? ""} — {r.instances} imagem(ns)</li>)}
          {!d.received.length && <li>Nenhum estudo recebido no dia.</li>}</ul>
      </>}
      <h2 className="section">Recusas na recepção DICOM</h2>
      <ul className="history">{(d?.reception_failures ?? []).map((f, i) => <li key={i}>{fmtDate(f.at)} — {f.reason ?? "motivo não informado"} ({f.via ?? "—"}, {f.source})</li>)}
        {d && !d.reception_failures.length && <li>Nenhuma recusa no dia.</li>}</ul>
      {d?.quality_issues && d.quality_issues.length > 0 && <>
        <h2 className="section">Pendências de qualidade e conciliação</h2>
        <ul className="history">{d.quality_issues.map((q) => <li key={q.study_uid}>{q.accession ?? q.study_uid.slice(-12)} — {q.issues.map((i) => ISSUE[i] ?? i).join(", ")}</li>)}</ul>
      </>}
    </Page>
  );
}
