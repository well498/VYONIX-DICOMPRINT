import { useState, type FormEvent } from "react";
import { fmtDate, get, post, type Me } from "../api";
import { Field, Notice, Page, useAction, useLoad } from "../ui";

type Patient = { id: string; name: string; birth_date: string | null; sex: string | null; active: boolean;
  merged_into_id: string | null; row_version: number; identifiers: { issuer: string; value: string }[];
  merges?: { id: string; source_id: string; target_id: string; reason: string; merged_by: string; at: string;
    reverted_at: string | null }[] };
type Order = { id: string; accession: string; status: string; priority: string; created_at: string };
type Study = { id: string; study_instance_uid: string; accession: string | null; modality: string | null;
  study_date: string | null; order_id: string | null };

const ORDER_STATUS: Record<string, string> = { requested: "Solicitado", scheduled: "Agendado", arrived: "Paciente chegou",
  in_progress: "Em realização", completed: "Concluído", cancelled: "Cancelado" };

export function PatientsPage({ me }: { me: Me }) {
  const can = (p: string) => me.permissions.includes(p);
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const list = useLoad(() => get<Patient[]>(`/patients?${new URLSearchParams(query ? { q: query } : {})}`), [query]);
  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  return (
    <Page title="Pacientes" intro="Cadastro único de pacientes da instituição."
      actions={can("clinical.patients.write") && <button className="primary" onClick={() => setCreating(true)}>Novo paciente</button>}>
      <form className="filters" role="search" onSubmit={(e) => { e.preventDefault(); setQuery(q.trim()); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Nome do paciente" aria-label="Buscar paciente" />
        <button>Buscar</button>
      </form>
      {creating && <NewPatient onClose={() => setCreating(false)} onSaved={(id) => { setCreating(false); setSelected(id); void list.reload(); }} />}
      <Notice kind="error">{list.error}</Notice>
      <div className="split">
        <ul className="patient-list" aria-label="Resultado da busca">
          {list.data?.map((p) => (
            <li key={p.id}>
              <button className={selected === p.id ? "selected" : ""} onClick={() => setSelected(p.id)}>
                <strong>{p.name}</strong>
                <span className="sub">{p.birth_date ? fmtDate(p.birth_date + "T12:00:00", false) : "Nascimento não informado"}
                  {p.identifiers[0] ? ` — ${p.identifiers[0].issuer} ${p.identifiers[0].value}` : ""}</span>
              </button>
            </li>
          ))}
          {list.data?.length === 0 && <li className="empty">Nenhum paciente encontrado. Confira a grafia ou cadastre um novo.</li>}
        </ul>
        {selected && <PatientDetail key={selected} id={selected} me={me} onChanged={() => list.reload()} />}
      </div>
    </Page>
  );
}

function NewPatient({ onClose, onSaved }: { onClose: () => void; onSaved: (id: string) => void }) {
  const [f, setF] = useState({ name: "", birth_date: "", sex: "", issuer: "PRONTUARIO", value: "" });
  const act = useAction();
  async function submit(e: FormEvent) {
    e.preventDefault();
    await act.run(async () => {
      const p = await post<Patient>("/patients", { name: f.name, birth_date: f.birth_date || null, sex: f.sex || null,
        identifiers: f.value ? [{ issuer: f.issuer, value: f.value }] : [] });
      onSaved(p.id);
    });
  }
  return (
    <form className="panel" onSubmit={submit} aria-label="Novo paciente">
      <h2>Novo paciente</h2>
      <div className="grid2">
        <Field label="Nome completo"><input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required minLength={2} /></Field>
        <Field label="Data de nascimento"><input type="date" value={f.birth_date} onChange={(e) => setF({ ...f, birth_date: e.target.value })} /></Field>
        <Field label="Sexo"><select value={f.sex} onChange={(e) => setF({ ...f, sex: e.target.value })}>
          <option value="">Não informado</option><option value="F">Feminino</option><option value="M">Masculino</option><option value="O">Outro</option></select></Field>
        <Field label="Identificador" hint="Ex.: PRONTUARIO, CPF, CNS">
          <div className="pair"><input aria-label="Emissor" value={f.issuer} onChange={(e) => setF({ ...f, issuer: e.target.value })} />
            <input aria-label="Número" value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })} /></div>
        </Field>
      </div>
      {act.view}
      <div className="form-actions"><button className="primary" disabled={act.busy}>Cadastrar paciente</button><button type="button" onClick={onClose}>Cancelar</button></div>
    </form>
  );
}

function PatientDetail({ id, me, onChanged }: { id: string; me: Me; onChanged: () => void }) {
  const can = (p: string) => me.permissions.includes(p);
  const p = useLoad(() => get<Patient>(`/patients/${id}`), [id]);
  const orders = useLoad(() => (can("clinical.orders.read") ? get<Order[]>(`/orders?patient_id=${id}`) : Promise.resolve([])), [id]);
  const studies = useLoad(() => (can("clinical.studies.read") ? get<Study[]>(`/studies?patient_id=${id}`) : Promise.resolve([])), [id]);
  const reports = useLoad(async () => (can("report.read")
    ? (await get<{ items: { study_id: string; report_id: string | null; report_status: string }[] }>(`/report/worklist?patient_id=${id}`)).items
    : []), [id]);
  const reportOf = new Map((reports.data ?? []).map((r) => [r.study_id, r]));
  const act = useAction();
  const [mergeTarget, setMergeTarget] = useState("");
  const [reason, setReason] = useState("");
  if (!p.data) return <div className="detail"><Notice kind="error">{p.error}</Notice></div>;
  const x = p.data;
  return (
    <article className="detail" aria-label={`Paciente ${x.name}`}>
      <h2>{x.name}</h2>
      {x.merged_into_id && <Notice kind="warn">Cadastro mesclado em outro paciente. Use o cadastro de destino.</Notice>}
      <dl className="facts">
        <div><dt>Nascimento</dt><dd>{x.birth_date ? fmtDate(x.birth_date + "T12:00:00", false) : "—"}</dd></div>
        <div><dt>Sexo</dt><dd>{{ F: "Feminino", M: "Masculino", O: "Outro" }[x.sex ?? ""] ?? "—"}</dd></div>
        {x.identifiers.map((i) => <div key={i.issuer + i.value}><dt>{i.issuer}</dt><dd>{i.value}</dd></div>)}
      </dl>
      {act.view}
      {can("clinical.orders.write") && !x.merged_into_id && (
        <button onClick={() => act.run(async () => { await post("/orders", { patient_id: x.id }); await orders.reload(); }, "Pedido criado.")}>Novo pedido</button>
      )}
      {can("clinical.orders.read") && (
        <>
          <h3>Pedidos</h3>
          {orders.data?.length ? <ul className="history">{orders.data.map((o) => <li key={o.id}>{o.accession} — {ORDER_STATUS[o.status] ?? o.status} — {fmtDate(o.created_at)}</li>)}</ul>
            : <p className="empty">Nenhum pedido.</p>}
        </>
      )}
      {can("clinical.studies.read") && (
        <>
          <h3>Estudos</h3>
          {studies.data?.length ? <ul className="history">{studies.data.map((s) => <li key={s.id}>{s.modality ?? "—"} {s.study_date ? fmtDate(s.study_date + "T12:00:00", false) : ""} — acesso {s.accession ?? "—"} {s.order_id ? "(conciliado)" : "(sem pedido)"}
                {reportOf.get(s.id)?.report_status === "final" && <> — laudo liberado <a href={`/api/v1/report/reports/${reportOf.get(s.id)!.report_id}/pdf`}>PDF do laudo</a></>}
                {reportOf.get(s.id)?.report_status === "draft" && " — laudo em rascunho"}</li>)}</ul>
            : <p className="empty">Nenhum estudo recebido.</p>}
        </>
      )}
      {can("clinical.patients.merge") && (
        <section className="panel" aria-label="Mesclar cadastro">
          <h3>Mesclar cadastro duplicado</h3>
          {!x.merged_into_id && <>
            <p className="sub">Os identificadores, pedidos e estudos deste cadastro passam para o cadastro de destino. A mescla pode ser desfeita.</p>
            <Field label="ID do cadastro de destino"><input value={mergeTarget} onChange={(e) => setMergeTarget(e.target.value)} /></Field>
            <Field label="Motivo"><input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
            <button disabled={!mergeTarget || reason.length < 3} onClick={() => act.run(async () => {
              await post("/patients/merge", { source_id: x.id, target_id: mergeTarget.trim(), reason });
              await p.reload(); onChanged();
            }, "Cadastros mesclados.")}>Mesclar neste destino</button>
          </>}
          {x.merges?.filter((m) => !m.reverted_at).map((m) => (
            <p key={m.id}>Mescla de {fmtDate(m.at)} por {m.merged_by} ({m.reason}){" "}
              <button onClick={() => {
                const why = window.prompt("Motivo para desfazer a mescla:");
                if (why) void act.run(async () => { await post(`/merges/${m.id}/undo`, { reason: why }); await p.reload(); onChanged(); }, "Mescla desfeita.");
              }}>Desfazer mescla</button></p>
          ))}
        </section>
      )}
      <p className="sub">ID do cadastro: <code>{x.id}</code></p>
    </article>
  );
}
