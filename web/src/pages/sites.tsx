import { useState, type FormEvent } from "react";
import { get, patch, post, type Me } from "../api";
import { Field, Notice, Page, useAction, useLoad } from "../ui";
import type { Site } from "../types";

export function SitesPage({ me }: { me: Me }) {
  const manage = me.permissions.includes("core.sites.manage");
  const sites = useLoad(() => get<Site[]>("/sites"));
  const act = useAction();
  const [name, setName] = useState(""); const [cnes, setCnes] = useState("");
  async function add(e: FormEvent) {
    e.preventDefault();
    if (await act.run(() => post("/sites", { name, cnes: cnes || null }), "Unidade cadastrada.")) {
      setName(""); setCnes(""); void sites.reload();
    }
  }
  return (
    <Page title="Unidades" intro="Locais de atendimento da instituição. A licença define quantas unidades ativas são permitidas.">
      <Notice kind="error">{sites.error}</Notice>
      {act.view}
      <div className="table-wrap">
        <table>
          <thead><tr><th>Unidade</th><th>CNES</th><th>Fuso horário</th><th>Situação</th>{manage && <th />}</tr></thead>
          <tbody>
            {sites.data?.map((s) => (
              <tr key={s.id} className={s.active ? "" : "muted"}>
                <td>{s.name}</td><td>{s.cnes ?? "—"}</td><td>{s.timezone}</td><td>{s.active ? "Ativa" : "Inativa"}</td>
                {manage && <td className="row-actions"><button onClick={() => act.run(async () => {
                  await patch(`/sites/${s.id}`, { name: s.name, active: !s.active }); await sites.reload();
                })}>{s.active ? "Desativar" : "Reativar"}</button></td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {manage && (
        <form className="panel inline" onSubmit={add} aria-label="Nova unidade">
          <Field label="Nome da unidade"><input value={name} onChange={(e) => setName(e.target.value)} required /></Field>
          <Field label="CNES" hint="7 dígitos, opcional"><input value={cnes} onChange={(e) => setCnes(e.target.value)} inputMode="numeric" pattern="[0-9]{7}" /></Field>
          <button className="primary" disabled={act.busy}>Cadastrar unidade</button>
        </form>
      )}
    </Page>
  );
}
