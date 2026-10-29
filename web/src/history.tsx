import { fmtDate, get } from "./api";
import { Notice, useLoad } from "./ui";
import { OpenImages } from "./viewer";

/** Histórico integrado do paciente (PACS, RIS e laudos): um item por exame, sem duplicar; exame de unidade sem
 * vínculo aparece restrito. Sem texto de laudo. */
type Item = { kind: "study" | "order" | "encounter"; date: string; modality?: string | null; study_id?: string; restricted: boolean;
  description?: string | null; accession?: string | null; study_instance_uid?: string | null; images?: { series: number } | null;
  procedure?: string | null; requester?: string | null; order_status?: string | null;
  encounter?: { number: string; status: string; arrived_at: string | null } | null;
  report?: { id: string; status: string; critical: boolean; finalized_at: string | null; versions: number } | null;
  documents?: { kind: string; modality?: string | null; description?: string | null; count?: number }[];
  schedule?: { at: string; status: string; room: string | null }[] };
type History = { items: Item[]; counts: { studies: number; orders_without_study: number; encounters_without_order: number };
  can_view_images: boolean; can_read_reports: boolean };

const REPORT: Record<string, string> = { draft: "laudo em rascunho", review: "laudo em revisão", final: "laudo liberado" };
const ORDER: Record<string, string> = { requested: "solicitado", scheduled: "agendado", arrived: "paciente chegou",
  in_progress: "em realização", completed: "concluído", cancelled: "cancelado" };

export function PatientHistory({ patientId }: { patientId: string }) {
  const h = useLoad(() => get<History>(`/ris/patients/${patientId}/history`), [patientId]);
  if (h.error) return <Notice kind="error">{h.error}</Notice>;
  if (!h.data) return <p className="field-hint">Carregando histórico…</p>;
  const d = h.data;
  return (
    <section className="panel" aria-label="Histórico do paciente">
      <h3>Histórico do paciente</h3>
      <p className="field-hint">{d.counts.studies} exame(s) com imagens/estudo · {d.counts.orders_without_study} pedido(s) sem estudo ·
        {" "}{d.counts.encounters_without_order} atendimento(s) sem pedido. Mais recentes primeiro.</p>
      {d.items.length === 0 && <p className="empty">Nada registrado para este paciente.</p>}
      <ol className="patient-history">{d.items.map((x, i) => (
        <li key={i} className={`ph-${x.kind}`}>
          <span className="ph-date">{fmtDate(x.date + "T12:00:00", false)}</span>
          {x.kind === "study" && (x.restricted
            ? <span>{x.modality ?? "Exame"} — <em>restrito</em> (unidade sem vínculo com você)</span>
            : <span>
                <strong>{x.modality ?? "—"}</strong> {x.description ?? x.procedure ?? ""}{x.accession ? ` · acesso ${x.accession}` : ""}
                {x.requester ? ` · solicitante ${x.requester}` : ""}
                {x.encounter ? ` · atendimento ${x.encounter.number}` : ""}
                {x.images ? ` · ${x.images.series} série(s) no PACS` : " · sem imagens no PACS"}
                {x.report && <> · {REPORT[x.report.status] ?? x.report.status}{x.report.critical && <span className="tag tag-warn">Achado crítico</span>}
                  {x.report.status === "final" && d.can_read_reports && <> <a href={`/api/v1/report/reports/${x.report.id}/pdf`}>PDF</a></>}</>}
                {x.documents && x.documents.length > 0 && <> · documentos: {x.documents.map((doc) => doc.kind === "attachment"
                  ? `${doc.count} anexo(s) da preparação` : `${doc.modality}${doc.description ? ` (${doc.description})` : ""}`).join(", ")}</>}
                {x.study_instance_uid && d.can_view_images && <> <OpenImages studyUid={x.study_instance_uid} compact /></>}
              </span>)}
          {x.kind === "order" && <span>Pedido {x.accession ?? ""} — {x.description ?? "procedimento não informado"} · {ORDER[x.order_status ?? ""] ?? x.order_status}
            {x.schedule && x.schedule.length > 0 && ` · agendado ${fmtDate(x.schedule[0].at)}`}{x.requester ? ` · solicitante ${x.requester}` : ""}</span>}
          {x.kind === "encounter" && <span>Atendimento {x.encounter?.number} ({x.encounter?.status === "open" ? "aberto" : x.encounter?.status}) sem pedido de exame</span>}
        </li>))}
      </ol>
    </section>
  );
}
