import { useState } from "react";
import { fmtDate, get, post, type Me } from "../api";
import { Notice, Page, useAction, useLoad } from "../ui";

type Study = { id: string; study_instance_uid: string; accession: string | null; modality: string | null;
  study_date: string | null; description: string | null; patient_id: string | null };
type Order = { id: string; accession: string; status: string; patient_id: string; patient_name?: string | null;
  created_at: string };
type Attr = { vr: string; Value?: unknown[] };

function pn(v: unknown): string {
  if (v && typeof v === "object" && "Alphabetic" in (v as object)) return String((v as { Alphabetic: string }).Alphabetic);
  return v == null ? "" : String(v);
}

/** Estudos recebidos sem pedido: conciliação manual pelo número de acesso, com conferência dos dados DICOM. */
export function ReconcilePage({ me }: { me: Me }) {
  const canDicom = me.permissions.includes("pacs.studies.read");
  const list = useLoad(async () => {
    const studies = await get<Study[]>("/studies?unreconciled=true");
    const dicom: Record<string, { name: string; id: string }> = {};
    if (canDicom) {
      await Promise.all(studies.map(async (st) => {
        try {
          const r = await get<Record<string, Attr>[] | null>(`/pacs/dicomweb/studies?StudyInstanceUID=${encodeURIComponent(st.study_instance_uid)}`);
          const j = r?.[0];
          if (j) dicom[st.id] = { name: pn(j["00100010"]?.Value?.[0]), id: pn(j["00100020"]?.Value?.[0]) };
        } catch { /* sem acesso ao PACS: só os dados do cadastro */ }
      }));
    }
    return { studies, dicom };
  }, []);
  const [open, setOpen] = useState<string | null>(null);
  const [acc, setAcc] = useState("");
  const [found, setFound] = useState<Order[] | null>(null);
  const act = useAction();

  async function search() {
    await act.run(async () => { setFound(await get<Order[]>(`/orders?accession=${encodeURIComponent(acc.trim())}`)); });
  }
  async function reconcile(studyId: string, orderId: string) {
    const ok = await act.run(async () => { await post(`/studies/${studyId}/reconcile`, { order_id: orderId }); await list.reload(); },
      "Estudo conciliado com o pedido.");
    if (ok) { setOpen(null); setFound(null); setAcc(""); }
  }

  return (
    <Page title="Conciliação de estudos"
      intro="Estudos recebidos sem pedido correspondente. Confira o paciente nos dados DICOM antes de conciliar: o estudo passa a pertencer ao paciente do pedido.">
      {act.view}
      <Notice kind="error">{list.error}</Notice>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Data</th><th>Modalidade</th><th>Descrição</th><th>Accession do estudo</th><th>Paciente (DICOM)</th><th>Ações</th></tr></thead>
          <tbody>
            {(list.data?.studies ?? []).map((st) => {
              const d = list.data?.dicom[st.id];
              return [
                <tr key={st.id}>
                  <td className="nowrap">{st.study_date ? fmtDate(st.study_date + "T12:00:00", false) : "—"}</td>
                  <td>{st.modality ?? "—"}</td><td>{st.description ?? "—"}</td><td className="nowrap">{st.accession ?? "—"}</td>
                  <td>{d ? `${d.name || "—"} (ID ${d.id || "—"})` : "—"}</td>
                  <td className="actions"><button onClick={() => { setOpen(open === st.id ? null : st.id); setFound(null); setAcc(st.accession ?? ""); }}>
                    Conciliar</button></td>
                </tr>,
                open === st.id ? (
                  <tr key={`${st.id}-r`} className="detail-row"><td colSpan={6}>
                    <form className="filters" aria-label="Buscar pedido" onSubmit={(e) => { e.preventDefault(); void search(); }}>
                      <input required aria-label="Número de acesso do pedido" placeholder="Número de acesso do pedido" value={acc}
                        onChange={(e) => setAcc(e.target.value)} />
                      <button>Buscar pedido</button>
                    </form>
                    {found && (found.length === 0 ? <Notice kind="warn">Nenhum pedido com esse número de acesso.</Notice> : (
                      <ul className="history">{found.map((o) => (
                        <li key={o.id}>Pedido {o.accession} — paciente <strong>{o.patient_name ?? "—"}</strong> — {o.status} — {fmtDate(o.created_at)}{" "}
                          <button className="primary" disabled={act.busy} onClick={() => void reconcile(st.id, o.id)}>Confirmar conciliação</button></li>))}
                      </ul>))}
                  </td></tr>) : null,
              ];
            })}
          </tbody>
        </table>
        {!list.loading && !list.error && (list.data?.studies ?? []).length === 0 && <p className="empty">Nenhum estudo aguardando conciliação.</p>}
      </div>
    </Page>
  );
}
