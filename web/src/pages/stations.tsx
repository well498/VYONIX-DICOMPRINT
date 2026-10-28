import { useState, type FormEvent } from "react";
import { del, get, post, type Me } from "../api";
import { Field, Notice, Page, useAction, useLoad } from "../ui";

type Node = { id: string; ae_title: string; host: string | null; port: number | null; description: string | null;
  can_query: boolean; can_receive: boolean };

export function StationsPage({ me }: { me: Me }) {
  void me;
  const list = useLoad(() => get<{ nodes: Node[]; qr: { port: number | null; ae_title: string } }>("/pacs/nodes"), []);
  const [form, setForm] = useState({ ae: "", host: "", port: "", description: "", query: true, receive: false });
  const [creating, setCreating] = useState(false);
  const act = useAction();

  async function submit(e: FormEvent) {
    e.preventDefault();
    const ok = await act.run(async () => {
      await post("/pacs/nodes", { ae_title: form.ae, host: form.host || null, port: form.port ? Number(form.port) : null,
        description: form.description || null, can_query: form.query, can_receive: form.receive });
      await list.reload();
    }, "Estação cadastrada.");
    if (ok) { setCreating(false); setForm({ ae: "", host: "", port: "", description: "", query: true, receive: false }); }
  }

  const qr = list.data?.qr;
  return (
    <Page title="Estações DICOM"
      intro="Equipamentos e estações que podem consultar o PACS e a worklist (C-FIND) e receber estudos (C-MOVE). Estação não cadastrada é recusada."
      actions={!creating ? <button className="primary" onClick={() => setCreating(true)}>Cadastrar estação</button> : undefined}>
      {act.view}
      {qr && (
        <Notice kind="info">{qr.port
          ? <>Configure nos equipamentos: AE Title <strong>{qr.ae_title}</strong>, porta <strong>{qr.port}</strong>, endereço deste servidor.</>
          : "Consulta DICOM não configurada neste servidor (ative o PACS pelo VYONIX DEPLOY)."}</Notice>
      )}
      {creating && (
        <form className="panel" aria-label="Cadastrar estação" onSubmit={submit}>
          <div className="grid2">
            <Field label="AE Title" hint="Até 16 caracteres, como configurado no equipamento">
              <input required maxLength={16} value={form.ae} onChange={(e) => setForm({ ...form, ae: e.target.value.toUpperCase() })} /></Field>
            <Field label="Endereço IP" hint="Se informado, consultas de outro IP são recusadas">
              <input maxLength={64} value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} /></Field>
            <Field label="Porta" hint="Obrigatória para receber estudos (C-MOVE)">
              <input type="number" min={1} max={65535} value={form.port} onChange={(e) => setForm({ ...form, port: e.target.value })} /></Field>
            <Field label="Descrição"><input maxLength={200} value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
          </div>
          <label className="check"><input type="checkbox" checked={form.query}
            onChange={(e) => setForm({ ...form, query: e.target.checked })} /> Pode consultar (estudos e worklist)</label>
          <label className="check"><input type="checkbox" checked={form.receive}
            onChange={(e) => setForm({ ...form, receive: e.target.checked })} /> Pode receber estudos (C-MOVE)</label>
          <div className="row-actions">
            <button className="primary" disabled={act.busy}>Salvar estação</button>
            <button type="button" className="link" onClick={() => setCreating(false)}>Cancelar</button>
          </div>
        </form>
      )}
      <Notice kind="error">{list.error}</Notice>
      <div className="table-wrap">
        <table>
          <thead><tr><th>AE Title</th><th>Endereço</th><th>Porta</th><th>Descrição</th><th>Consulta</th><th>Recebe</th><th>Ações</th></tr></thead>
          <tbody>
            {(list.data?.nodes ?? []).map((n) => (
              <tr key={n.id}>
                <td className="nowrap">{n.ae_title}</td><td>{n.host ?? "qualquer"}</td><td>{n.port ?? "—"}</td>
                <td>{n.description ?? "—"}</td><td>{n.can_query ? "Sim" : "Não"}</td><td>{n.can_receive ? "Sim" : "Não"}</td>
                <td className="actions"><button className="link" disabled={act.busy} onClick={() => void act.run(async () => {
                  await del(`/pacs/nodes/${n.id}`); await list.reload();
                }, `Estação ${n.ae_title} removida.`)}>Remover</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        {!list.loading && !list.error && (list.data?.nodes ?? []).length === 0 && <p className="empty">Nenhuma estação cadastrada.</p>}
      </div>
    </Page>
  );
}
