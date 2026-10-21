import { useState, type FormEvent } from "react";
import { get, post, type Me } from "../api";
import { Field, Notice, Page, download, useAction, useLoad } from "../ui";
import type { ModuleRow } from "../types";

const DAYS = [5, 15, 30];

export function CommercialPage({ me }: { me: Me }) {
  const manage = me.permissions.includes("core.license.manage");
  const mods = useLoad(() => get<ModuleRow[]>("/modules"));
  const [kind, setKind] = useState<"demo" | "contract">("demo");
  const [chosen, setChosen] = useState<string[]>(["core", "print"]);
  const [days, setDays] = useState<number | "custom">(15);
  const [custom, setCustom] = useState(10);
  const [contact, setContact] = useState({ name: me.display_name, email: "", phone: "", notes: "" });
  const [result, setResult] = useState<{ code: string; file: string; request_id: string } | null>(null);
  const act = useAction();

  async function submit(e: FormEvent) {
    e.preventDefault();
    const demo_days = kind === "demo" ? (days === "custom" ? custom : days) : null;
    await act.run(async () => setResult(await post("/license/request", {
      modules: chosen, demo_days, contact_name: contact.name, contact_email: contact.email,
      contact_phone: contact.phone || null, notes: contact.notes || null })));
  }

  return (
    <Page title="Contratar e demonstrar" intro="Peça uma demonstração ou a contratação de módulos. O pedido gera um código desta instalação; o fornecedor devolve a licença assinada, que você aplica em Licença e módulos.">
      {!manage && <Notice kind="info">Somente administradores podem gerar pedidos. Fale com o administrador da clínica.</Notice>}
      {manage && !result && (
        <form className="panel" onSubmit={submit} aria-label="Solicitar demonstração">
          <fieldset className="choice">
            <legend>O que você precisa</legend>
            <label className="check"><input type="radio" name="kind" checked={kind === "demo"} onChange={() => setKind("demo")} /> Solicitar demonstração</label>
            <label className="check"><input type="radio" name="kind" checked={kind === "contract"} onChange={() => setKind("contract")} /> Contratar</label>
          </fieldset>
          <fieldset className="choice">
            <legend>Módulos</legend>
            <div className="module-picks">
              {mods.data?.filter((m) => m.requires_license).map((m) => (
                <label key={m.code} className="check">
                  <input type="checkbox" checked={chosen.includes(m.code)} disabled={m.code === "core"}
                    onChange={(e) => setChosen(e.target.checked ? [...chosen, m.code] : chosen.filter((c) => c !== m.code))} />
                  {m.name}{!m.available && <span className="sub"> (em desenvolvimento)</span>}
                </label>
              ))}
            </div>
          </fieldset>
          {kind === "demo" && (
            <fieldset className="choice">
              <legend>Duração da demonstração</legend>
              {DAYS.map((d) => <label key={d} className="check"><input type="radio" name="days" checked={days === d} onChange={() => setDays(d)} /> {d} dias</label>)}
              <label className="check"><input type="radio" name="days" checked={days === "custom"} onChange={() => setDays("custom")} /> Outro prazo</label>
              {days === "custom" && <input type="number" min={1} max={90} value={custom} aria-label="Dias de demonstração" onChange={(e) => setCustom(Number(e.target.value))} />}
              <p className="sub">A contagem começa quando a licença de demonstração é aplicada neste servidor.</p>
            </fieldset>
          )}
          <div className="grid2">
            <Field label="Responsável"><input value={contact.name} onChange={(e) => setContact({ ...contact, name: e.target.value })} required minLength={2} /></Field>
            <Field label="E-mail para resposta"><input type="email" value={contact.email} onChange={(e) => setContact({ ...contact, email: e.target.value })} required /></Field>
            <Field label="Telefone"><input value={contact.phone} onChange={(e) => setContact({ ...contact, phone: e.target.value })} /></Field>
            <Field label="Observações"><input value={contact.notes} onChange={(e) => setContact({ ...contact, notes: e.target.value })} maxLength={500} /></Field>
          </div>
          {act.view}
          <button className="primary" disabled={act.busy || chosen.length === 0}>Gerar pedido</button>
        </form>
      )}
      {result && (
        <section className="panel" aria-label="Pedido gerado">
          <h2>Pedido gerado</h2>
          <p className="intro">Envie o arquivo (ou o código) ao fornecedor do VYONIX. Nenhum dado de paciente vai no pedido.</p>
          <textarea readOnly rows={5} value={result.code} aria-label="Código do pedido" />
          <div className="form-actions">
            <button className="primary" onClick={() => download(`pedido-${result.request_id}.vyreq`, result.file)}>Baixar arquivo do pedido</button>
            <button onClick={() => navigator.clipboard?.writeText(result.code)}>Copiar código</button>
            <button onClick={() => setResult(null)}>Novo pedido</button>
          </div>
        </section>
      )}
    </Page>
  );
}
