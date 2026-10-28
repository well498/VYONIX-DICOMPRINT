import { useState } from "react";
import { fmtDate, get, patch, type Me } from "../api";
import { Notice, Page, useAction, useLoad } from "../ui";

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
    <Page title="Painel do técnico" intro="Exames do dia, recepção das imagens no PACS e pendências. A emissão e a liberação de laudos são exclusivas dos médicos."
      actions={<input type="date" aria-label="Dia" value={day} onChange={(e) => setDay(e.target.value)} />}>
      {act.view}
      <Notice kind="error">{p.error}</Notice>
      {d && <div className="card-row" role="group" aria-label="Resumo do dia">
        <div className="card"><span className="card-label">A realizar</span><strong>{(c.scheduled ?? 0) + (c.arrived ?? 0)}</strong></div>
        <div className="card"><span className="card-label">Em realização</span><strong>{c.in_progress ?? 0}</strong></div>
        <div className="card"><span className="card-label">Concluídos / imagens recebidas</span><strong>{(c.completed ?? 0) + (c.received ?? 0)}</strong></div>
        {d.received && <div className="card"><span className="card-label">Estudos recebidos no PACS</span><strong>{d.received.length}</strong></div>}
        <div className={`card${d.reception_failures.length ? " card-warn" : ""}`}><span className="card-label">Recusas na recepção DICOM</span><strong>{d.reception_failures.length}</strong></div>
        <div className="card"><span className="card-label">Transferências incompletas (MPPS)</span><strong>{d.incomplete_transfers}</strong></div>
      </div>}
      <h2 className="section">Exames do dia</h2>
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
