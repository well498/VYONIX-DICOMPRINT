import { useState, type FormEvent } from "react";
import { patch, post, get, type Me } from "../api";
import { Field, Notice, Page, useAction, useLoad } from "../ui";
import { OpenImages } from "../viewer";

type Item = {
  schedule_id: string; sps_id: string; status: string; accession: string; priority: string; modality: string;
  station_aet: string | null; room: string | null; description: string | null; scheduled_at: string; duration_min: number;
  study_instance_uid: string; mpps_status: string | null;
  images: { expected: number; received: number } | null;
  mpps_summary?: { series?: { series_uid: string; description: string | null; protocol: string | null; images: number }[];
    dose?: Record<string, unknown> & { exposure_items?: Record<string, unknown>[] } } | null;
  patient_id: string; patient_name: string;
};
type Room = { id: string; name: string; modality: string | null; station_aet: string | null; default_duration_min: number;
  active: boolean };
type Pending = { order_id: string; accession: string; priority: string; patient_name: string;
  procedure: string | null; modality: string | null; created_at: string };

const STATUS: Record<string, string> = { scheduled: "Agendado", arrived: "Paciente chegou", in_progress: "Em realização", received: "Imagens recebidas",
  completed: "Concluído", cancelled: "Cancelado" };

const DOSE: Record<string, string> = { fluoro_time_s: "Tempo de fluoroscopia (s)", exposures: "Exposições",
  entrance_dose_mgy: "Dose de entrada (mGy)", entrance_dose_dgy: "Dose de entrada (dGy)", dap_dgy_cm2: "Produto dose × área (dGy·cm²)",
  exposed_area_cm2: "Área exposta (cm²)", source_entrance_mm: "Fonte–entrada (mm)", comments: "Comentários" };

function MppsSummary({ s }: { s: NonNullable<Item["mpps_summary"]> }) {
  return (
    <details className="mpps-summary"><summary>Informado pela modalidade</summary>
      {s.series?.length ? <ul>{s.series.map((x) => <li key={x.series_uid}>{x.description || x.protocol || "Série"}{x.protocol && x.description ? ` (${x.protocol})` : ""}: {x.images} imagem(ns)</li>)}</ul> : null}
      {s.dose && <ul>{Object.entries(s.dose).filter(([k]) => k !== "exposure_items").map(([k, v]) => <li key={k}>{DOSE[k] ?? k}: {String(v)}</li>)}
        {s.dose.exposure_items?.length ? <li>{s.dose.exposure_items.length} registro(s) de exposição</li> : null}</ul>}
      <span className="field-hint">Valores como enviados pelo equipamento (MPPS), sem conferência nem validação dosimétrica.</span>
    </details>);
}

const MPPS: Record<string, string> = { "IN PROGRESS": "modalidade: iniciado", COMPLETED: "modalidade: concluído",
  DISCONTINUED: "modalidade: interrompido" };

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function hour(iso: string): string {
  return new Date(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}
/** "2026-11-03T09:00" (horário local do navegador) → ISO com o fuso, como a API exige. */
function withOffset(local: string): string {
  const d = new Date(local);
  const off = -d.getTimezoneOffset();
  const sign = off >= 0 ? "+" : "-";
  const hh = String(Math.floor(Math.abs(off) / 60)).padStart(2, "0");
  const mm = String(Math.abs(off) % 60).padStart(2, "0");
  return `${local.length === 16 ? local + ":00" : local}${sign}${hh}:${mm}`;
}

export function SchedulePage({ me }: { me: Me }) {
  const canManage = me.permissions.includes("ris.schedule.manage");
  const canView = me.permissions.includes("pacs.studies.read");
  const [filters, setFilters] = useState({ from: today(), to: today(), modality: "", done: false });
  const [query, setQuery] = useState(filters);
  const [form, setForm] = useState({ order: "", when: `${today()}T08:00`, modality: "", aet: "", room: "", description: "", duration: "15" });
  const [creating, setCreating] = useState(false);
  const [cancel, setCancel] = useState<{ id: string; reason: string } | null>(null);
  const act = useAction();

  const list = useLoad(async () => {
    const q = new URLSearchParams({ date_from: query.from, date_to: query.to });
    if (query.modality) q.set("modality", query.modality.toUpperCase());
    if (query.done) q.set("include_done", "true");
    return (await get<{ items: Item[] }>(`/ris/worklist?${q}`)).items;
  }, [query]);
  const stations = useLoad(async () => (canManage && creating
    ? (await get<{ items: { ae_title: string; description: string | null }[] }>("/ris/stations")).items : []), [canManage, creating]);
  const unknownAet = !!form.aet && !!stations.data && !stations.data.some((x) => x.ae_title === form.aet);
  const rooms = useLoad(async () => (await get<{ items: Room[] }>("/ris/rooms")).items, [creating]);
  const [showRooms, setShowRooms] = useState(false);
  const pending = useLoad(async () => (canManage && creating ? (await get<{ items: Pending[] }>("/ris/orders")).items : []),
    [canManage, creating]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const ok = await act.run(async () => {
      await post("/ris/schedules", { order_id: form.order, scheduled_at: withOffset(form.when),
        modality: form.modality || null, station_aet: form.aet || null, room: form.room || null,
        description: form.description || null, duration_min: Number(form.duration) || 15 });
    }, "Exame agendado. Ele já aparece na worklist da modalidade.");
    if (ok) { setCreating(false); setForm({ ...form, order: "" }); await list.reload(); }
  }

  async function setStatus(it: Item, status: string, reason: string | null = null) {
    const ok = await act.run(async () => {
      await patch(`/ris/schedules/${it.schedule_id}/status`, { status, reason }); await list.reload();
    }, `Situação alterada para “${STATUS[status]}”.`);
    if (ok) setCancel(null);
  }

  return (
    <Page title="Agenda" intro="Exames agendados e a worklist enviada às modalidades (Modality Worklist). O estudo que chega ao PACS com o UID agendado marca o exame como recebido."
      actions={<>
        {me.permissions.includes("ris.rooms.manage") && <button onClick={() => setShowRooms(!showRooms)}>{showRooms ? "Fechar salas" : "Salas"}</button>}
        {canManage && !creating && <button className="primary" onClick={() => setCreating(true)}>Agendar exame</button>}</>}>
      {act.view}
      {showRooms && <Rooms onChange={() => void rooms.reload()} />}
      {creating && (
        <form className="panel" aria-label="Agendar exame" onSubmit={submit}>
          <Field label="Pedido" hint="Pedidos ainda não agendados, mais antigos primeiro.">
            <select required value={form.order} onChange={(e) => {
              const p = pending.data?.find((x) => x.order_id === e.target.value);
              setForm({ ...form, order: e.target.value, modality: p?.modality ?? form.modality,
                        description: p?.procedure ?? form.description });
            }}>
              <option value="">Selecione…</option>
              {(pending.data ?? []).map((p) => (
                <option key={p.order_id} value={p.order_id}>
                  {p.patient_name} — {p.accession}{p.procedure ? ` — ${p.procedure}` : ""}{p.priority !== "routine" ? ` (${p.priority})` : ""}
                </option>))}
            </select>
          </Field>
          {pending.data && pending.data.length === 0 && <Notice kind="info">Nenhum pedido aguardando agendamento. Crie o pedido na ficha do paciente.</Notice>}
          <Notice kind="error">{pending.error}</Notice>
          <div className="grid2">
            <Field label="Data e hora"><input type="datetime-local" required value={form.when}
              onChange={(e) => setForm({ ...form, when: e.target.value })} /></Field>
            <Field label="Duração (min)" hint="Impede outro exame no mesmo horário na mesma estação ou sala">
              <input type="number" min={1} max={480} required value={form.duration}
                onChange={(e) => setForm({ ...form, duration: e.target.value })} /></Field>
            <Field label="Modalidade" hint="Ex.: CT, MR, CR, US"><input value={form.modality} maxLength={16}
              onChange={(e) => setForm({ ...form, modality: e.target.value.toUpperCase() })} /></Field>
            <Field label="AE Title da estação" hint="Opcional: restringe a worklist a esse equipamento">
              <input value={form.aet} maxLength={16} list="estacoes-dicom"
                onChange={(e) => setForm({ ...form, aet: e.target.value.toUpperCase() })} />
              <datalist id="estacoes-dicom">{(stations.data ?? []).map((x) =>
                <option key={x.ae_title} value={x.ae_title}>{x.description ?? ""}</option>)}</datalist></Field>
            <Field label="Sala" hint="Sala cadastrada preenche os demais campos">
              <input value={form.room} maxLength={64} list="salas-ris" onChange={(e) => {
                const room = (rooms.data ?? []).find((x) => x.name.toLowerCase() === e.target.value.trim().toLowerCase());
                setForm({ ...form, room: e.target.value, ...(room ? { modality: room.modality ?? form.modality,
                  aet: room.station_aet ?? form.aet, duration: String(room.default_duration_min) } : {}) });
              }} />
              <datalist id="salas-ris">{(rooms.data ?? []).map((x) => <option key={x.id} value={x.name} />)}</datalist></Field>
            <Field label="Descrição"><input value={form.description} maxLength={64}
              onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
          </div>
          {unknownAet && <Notice kind="warn">A estação {form.aet} não está cadastrada no PACS: ela não conseguirá consultar a worklist até ser cadastrada em “Nós DICOM”.</Notice>}
          <div className="row-actions">
            <button className="primary" disabled={act.busy}>Confirmar agendamento</button>
            <button type="button" className="link" onClick={() => setCreating(false)}>Cancelar</button>
          </div>
        </form>
      )}
      <form className="filters filters-grid" role="search" aria-label="Filtrar agenda" onSubmit={(e) => { e.preventDefault(); setQuery(filters); }}>
        <input type="date" aria-label="De" title="De" value={filters.from} onChange={(e) => setFilters({ ...filters, from: e.target.value })} />
        <input type="date" aria-label="Até" title="Até" value={filters.to} onChange={(e) => setFilters({ ...filters, to: e.target.value })} />
        <input placeholder="Modalidade" aria-label="Modalidade" maxLength={16} value={filters.modality}
          onChange={(e) => setFilters({ ...filters, modality: e.target.value })} />
        <label className="check"><input type="checkbox" checked={filters.done}
          onChange={(e) => setFilters({ ...filters, done: e.target.checked })} /> Incluir recebidos, concluídos e cancelados</label>
        <button>Filtrar</button>
      </form>
      <Notice kind="error">{list.error}</Notice>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Data</th><th>Hora</th><th>Paciente</th><th>ID</th><th>Modalidade</th><th>Estação / sala</th>
            <th>Descrição</th><th>Accession</th><th>Situação</th>{canManage && <th>Ações</th>}</tr></thead>
          <tbody>
            {(list.data ?? []).map((it) => [
              <tr key={it.schedule_id}>
                <td className="nowrap">{new Date(it.scheduled_at).toLocaleDateString("pt-BR")}</td>
                <td className="nowrap">{hour(it.scheduled_at)} <span className="field-hint">{it.duration_min} min</span></td>
                <td>{it.patient_name}</td>
                <td className="nowrap">{it.patient_id}</td>
                <td>{it.modality}</td>
                <td>{[it.station_aet, it.room].filter(Boolean).join(" · ") || "—"}</td>
                <td>{it.description || "—"}</td>
                <td className="nowrap">{it.accession}</td>
                <td>{STATUS[it.status] ?? it.status}
                  {it.mpps_status && <span className="tag" title="Informado pela modalidade (MPPS)">{MPPS[it.mpps_status] ?? it.mpps_status}</span>}
                  {it.images && <span className={`tag${it.images.received < it.images.expected ? " tag-warn" : ""}`}
                    title="Imagens informadas pela modalidade (MPPS) × recebidas pelo PACS">imagens {it.images.received}/{it.images.expected}</span>}
                  {it.mpps_summary && <MppsSummary s={it.mpps_summary} />}
                  {canView && ["received", "completed"].includes(it.status) && (
                    <> <OpenImages studyUid={it.study_instance_uid} compact /></>)}</td>
                {canManage && (
                  <td className="actions"><div className="row-actions">
                    {it.status === "scheduled" && <button onClick={() => void setStatus(it, "arrived")}>Check-in</button>}
                    {["scheduled", "arrived"].includes(it.status) && <button onClick={() => void setStatus(it, "in_progress")}>Iniciar</button>}
                    {["scheduled", "in_progress", "received"].includes(it.status) &&
                      <button onClick={() => void setStatus(it, "completed")}>Concluir</button>}
                    {!["completed", "cancelled"].includes(it.status) &&
                      <button className="link" onClick={() => setCancel({ id: it.schedule_id, reason: "" })}>Cancelar</button>}
                  </div></td>
                )}
              </tr>,
              cancel?.id === it.schedule_id ? (
                <tr key={`${it.schedule_id}-c`} className="detail-row"><td colSpan={10}>
                  <form className="filters" aria-label={`Cancelar exame de ${it.patient_name}`}
                    onSubmit={(e) => { e.preventDefault(); void setStatus(it, "cancelled", cancel.reason.trim()); }}>
                    <input required autoFocus aria-label="Motivo do cancelamento" placeholder="Motivo do cancelamento"
                      maxLength={300} value={cancel.reason} onChange={(e) => setCancel({ ...cancel, reason: e.target.value })} />
                    <button disabled={act.busy}>Confirmar cancelamento</button>
                    <button type="button" className="link" onClick={() => setCancel(null)}>Voltar</button>
                  </form>
                </td></tr>
              ) : null,
            ])}
          </tbody>
        </table>
        {!list.loading && !list.error && (list.data ?? []).length === 0 && <p className="empty">Nenhum exame agendado nesse período.</p>}
      </div>
    </Page>
  );
}

function Rooms({ onChange }: { onChange: () => void }) {
  const list = useLoad(async () => (await get<{ items: Room[] }>("/ris/rooms?include_inactive=true")).items, []);
  const [form, setForm] = useState({ name: "", modality: "", station_aet: "", default_duration_min: "15" });
  const act = useAction();
  async function submit(e: FormEvent) {
    e.preventDefault();
    const ok = await act.run(async () => {
      await post("/ris/rooms", { name: form.name, modality: form.modality || null, station_aet: form.station_aet || null,
        default_duration_min: Number(form.default_duration_min) || 15 });
      await list.reload(); onChange();
    }, "Sala cadastrada.");
    if (ok) setForm({ name: "", modality: "", station_aet: "", default_duration_min: "15" });
  }
  return (
    <section className="panel" aria-label="Salas de exame">
      <h2>Salas de exame</h2>
      {act.view}
      <ul className="history">{(list.data ?? []).map((x) => (
        <li key={x.id}>{x.name} — {x.modality ?? "qualquer modalidade"}{x.station_aet ? ` · ${x.station_aet}` : ""} · {x.default_duration_min} min{x.active ? "" : " (inativa)"}</li>))}</ul>
      <form className="grid2" aria-label="Nova sala" onSubmit={submit}>
        <Field label="Nome da sala"><input required maxLength={64} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label="Modalidade da sala"><input maxLength={16} value={form.modality} onChange={(e) => setForm({ ...form, modality: e.target.value.toUpperCase() })} /></Field>
        <Field label="Estação (AE Title)"><input maxLength={16} value={form.station_aet} onChange={(e) => setForm({ ...form, station_aet: e.target.value.toUpperCase() })} /></Field>
        <Field label="Duração padrão (min)"><input type="number" min={1} max={480} value={form.default_duration_min}
          onChange={(e) => setForm({ ...form, default_duration_min: e.target.value })} /></Field>
        <div><button className="primary" disabled={act.busy}>Salvar sala</button></div>
      </form>
    </section>
  );
}
