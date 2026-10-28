import { useState } from "react";
import { fmtDate, get, type Me } from "../api";
import { Notice, Page, useLoad } from "../ui";

type Item = { order_id: string; accession: string | null; priority: string; patient_name: string; procedure: string | null;
  modality: string | null; requester: string | null; stage: string; flags: string[]; requested_at: string;
  scheduled_at: string | null; room: string | null; mpps_status: string | null; study_instance_uid: string | null;
  images: number | null; images_check: { expected: number; received: number } | null; received_at: string | null;
  report_id: string | null; reported_at: string | null; critical: boolean;
  minutes_to_images: number | null; minutes_to_report: number | null };
type Result = { items: Item[]; by_stage: Record<string, number>; late: number; total: number;
  median_minutes_to_images: number | null; median_minutes_to_report: number | null };

const STAGE: [string, string][] = [["requested", "Pedido"], ["scheduled", "Agendado"], ["arrived", "Chegou"],
  ["in_progress", "Em realização"], ["images", "Imagens no PACS"], ["reporting", "Laudo em redação"],
  ["reported", "Laudo liberado"], ["cancelled", "Cancelado"]];
const STAGE_NAME = Object.fromEntries(STAGE);
const FLAG: Record<string, string> = { not_scheduled: "urgente sem agendamento", late_acquisition: "aquisição atrasada",
  late_report: "laudo fora do prazo", incomplete_images: "imagens incompletas", schedule_cancelled: "agendamento cancelado" };
const PRIORITY: Record<string, string> = { routine: "rotina", urgent: "urgente", stat: "imediato" };

function iso(d: Date) { return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; }
function dur(m: number | null) {
  if (m === null) return "—";
  return m < 60 ? `${m} min` : m < 2880 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${Math.round(m / 1440)} dias`;
}

/** Central de exames: o ciclo de cada pedido, do pedido ao laudo liberado, com atrasos e tempos. */
export function ExamCenterPage({ me }: { me: Me }) {
  const today = iso(new Date());
  const [f, setF] = useState({ from: today, to: today, modality: "", stage: "", late: false });
  const [q, setQ] = useState(f);
  const res = useLoad(async () => {
    const p = new URLSearchParams({ date_from: q.from, date_to: q.to });
    if (q.modality) p.set("modality", q.modality.toUpperCase());
    if (q.stage) p.set("stage", q.stage);
    if (q.late) p.set("late_only", "true");
    return await get<Result>(`/ris/exam-center?${p}`);
  }, [q]);
  const canView = me.permissions.includes("pacs.studies.read");
  const d = res.data;
  return (
    <Page title="Central de exames" intro="Cada pedido do período, do pedido ao laudo liberado: etapa atual, atrasos e tempos de atendimento (registro operacional, não indicador clínico).">
      <form className="filters exam-filters" role="search" aria-label="Filtrar exames" onSubmit={(e) => { e.preventDefault(); setQ(f); }}>
        <input type="date" aria-label="De" value={f.from} onChange={(e) => setF({ ...f, from: e.target.value })} />
        <input type="date" aria-label="Até" value={f.to} onChange={(e) => setF({ ...f, to: e.target.value })} />
        <input placeholder="Modalidade" aria-label="Modalidade" maxLength={16} value={f.modality} onChange={(e) => setF({ ...f, modality: e.target.value })} />
        <select aria-label="Etapa" value={f.stage} onChange={(e) => setF({ ...f, stage: e.target.value })}>
          <option value="">Todas as etapas</option>{STAGE.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <label className="check"><input type="checkbox" checked={f.late} onChange={(e) => setF({ ...f, late: e.target.checked })} /> Só com atraso ou pendência</label>
        <button>Filtrar</button>
      </form>
      <Notice kind="error">{res.error}</Notice>
      {d && <div className="card-row" role="group" aria-label="Resumo do período">
        <div className="card"><span className="card-label">Pedidos</span><strong>{d.total}</strong></div>
        <div className="card"><span className="card-label">Com atraso ou pendência</span><strong>{d.late}</strong></div>
        <div className="card"><span className="card-label">Aguardando laudo</span><strong>{(d.by_stage.images ?? 0) + (d.by_stage.reporting ?? 0)}</strong></div>
        <div className="card"><span className="card-label">Laudos liberados</span><strong>{d.by_stage.reported ?? 0}</strong></div>
        <div className="card"><span className="card-label">Mediana pedido → imagens</span><strong>{dur(d.median_minutes_to_images)}</strong></div>
        <div className="card"><span className="card-label">Mediana imagens → laudo</span><strong>{dur(d.median_minutes_to_report)}</strong></div>
      </div>}
      {d && <p className="field-hint">{STAGE.map(([k, v]) => `${v}: ${d.by_stage[k] ?? 0}`).join(" · ")}</p>}
      <div className="table-wrap">
        <table>
          <thead><tr><th>Paciente</th><th>Exame</th><th>Prioridade</th><th>Etapa</th><th>Agendado</th><th>Imagens</th><th>Laudo</th><th>Tempos</th></tr></thead>
          <tbody>{(d?.items ?? []).map((x) => (
            <tr key={x.order_id}>
              <td>{x.patient_name}<br /><span className="field-hint">{x.accession ?? "—"}</span></td>
              <td>{[x.modality, x.procedure].filter(Boolean).join(" · ") || "—"}<br /><span className="field-hint">{x.requester ?? ""}</span></td>
              <td>{PRIORITY[x.priority] ?? x.priority}</td>
              <td>{STAGE_NAME[x.stage] ?? x.stage}<span className="tags">{x.flags.map((fl) => <span key={fl} className="tag tag-warn">{FLAG[fl] ?? fl}</span>)}
                {x.critical && <span className="tag tag-warn">achado crítico</span>}</span></td>
              <td className="nowrap">{x.scheduled_at ? fmtDate(x.scheduled_at) : "—"}{x.room ? <><br /><span className="field-hint">{x.room}</span></> : null}</td>
              <td>{x.images ?? "—"}{x.images_check ? <span className="field-hint"> (MPPS {x.images_check.received}/{x.images_check.expected})</span> : null}
                {canView && x.received_at && x.study_instance_uid && <><br /><a href={`/viewer/viewer?StudyInstanceUIDs=${encodeURIComponent(x.study_instance_uid)}`} target="_blank" rel="noopener">Viewer</a></>}</td>
              <td>{x.reported_at ? fmtDate(x.reported_at) : x.report_id ? "em redação" : "—"}</td>
              <td className="nowrap">até imagens: {dur(x.minutes_to_images)}<br />até laudo: {dur(x.minutes_to_report)}</td>
            </tr>))}</tbody>
        </table>
        {!res.loading && !res.error && !(d?.items.length) && <p className="empty">Nenhum exame no período com esses filtros.</p>}
      </div>
    </Page>
  );
}
