import { useState } from "react";
import { fmtDate, get, post, type Me } from "../api";
import { Notice, Page, readFile, useAction, useLoad } from "../ui";
import { KIND_LABEL, STATE_LABEL, tone, type LicenseInfo, type ModuleRow } from "../types";

export function LicensePage({ me }: { me: Me }) {
  const manage = me.permissions.includes("core.license.manage");
  const modManage = me.permissions.includes("core.modules.manage");
  const lic = useLoad(() => get<LicenseInfo>("/license?refresh=true"));
  const mods = useLoad(() => get<ModuleRow[]>("/modules"));
  const act = useAction();
  const [doc, setDoc] = useState("");
  const reload = () => { void lic.reload(); void mods.reload(); };
  const l = lic.data?.license;

  async function apply(kind: "install" | "authorization") {
    if (await act.run(() => post(`/license/${kind}`, { document: doc }),
      kind === "install" ? "Licença aplicada." : "Autorização de uso aplicada.")) { setDoc(""); reload(); }
  }

  return (
    <Page title="Licença e módulos" intro="A licença é conferida neste servidor: assinatura do fornecedor, instalação, hardware e horário confiável.">
      <Notice kind="error">{lic.error || mods.error}</Notice>
      {act.view}
      {lic.data && (
        <dl className="facts">
          <div><dt>Licença</dt><dd>{l ? `${l.license_id} — ${l.type_label}` : "Nenhuma instalada"}</dd></div>
          {l && <div><dt>Cliente</dt><dd>{l.customer}</dd></div>}
          {l && <div><dt>Contrato até</dt><dd>{l.expires_at ? fmtDate(l.expires_at, false) : "Sem vencimento"}</dd></div>}
          {l && <div><dt>Validação</dt><dd>{l.validation === "online" ? `Online — ${l.connectivity_label || "aguardando contato"}` : "Offline (arquivo de renovação)"}</dd></div>}
          <div><dt>Installation ID</dt><dd><code>{lic.data.installation_id}</code></dd></div>
          <div><dt>Hardware ID</dt><dd><code>{lic.data.hardware_id}</code></dd></div>
        </dl>
      )}
      <h2 className="section">Módulos</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Módulo</th><th>Licença</th><th>Situação no sistema</th>{modManage && <th />}</tr></thead>
          <tbody>
            {mods.data?.map((m) => {
              const st = lic.data?.modules.find((x) => x.module === m.code);
              return (
                <tr key={m.code} className={m.available ? "" : "muted"}>
                  <td><strong>{m.name}</strong><br /><span className="sub">{m.description}</span></td>
                  <td>
                    {!m.requires_license ? "Incluído" : st && st.kind ? (
                      <><span className={`dot dot-${tone(st.state)}`} aria-hidden="true" />
                        {st.kind === "demo" ? STATE_LABEL[st.state] ?? st.state
                          : `${KIND_LABEL[st.kind] ?? st.kind}: ${STATE_LABEL[st.state] ?? st.state}`}
                        <br /><span className="sub">{st.message}</span></>
                    ) : "Sem licença"}
                  </td>
                  <td>{!m.available ? "Em desenvolvimento" : m.status === "enabled" ? "Habilitado" : "Desabilitado"}</td>
                  {modManage && (
                    <td className="row-actions">
                      {m.available && !m.always_enabled && (m.status === "enabled"
                        ? <button onClick={() => act.run(async () => { await post(`/modules/${m.code}/disable`, {}); reload(); }, `${m.name} desabilitado. Os dados foram preservados.`)}>Desabilitar</button>
                        : <button onClick={() => act.run(async () => { await post(`/modules/${m.code}/enable`); reload(); }, `${m.name} habilitado.`)}>Habilitar</button>)}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {manage && (
        <section className="panel" aria-label="Aplicar documento de licença">
          <h2>Aplicar licença ou renovação</h2>
          <p className="intro">Abra o arquivo enviado pelo fornecedor (.vylic para licença, .vyauth para renovação) ou cole o conteúdo.</p>
          <input type="file" accept=".vylic,.vyauth,.json,.txt" aria-label="Arquivo de licença"
            onChange={async (e) => { const f = e.target.files?.[0]; if (f) setDoc(await readFile(f)); }} />
          <textarea rows={6} value={doc} onChange={(e) => setDoc(e.target.value)} aria-label="Conteúdo do documento"
            placeholder='{"format": "vyonix-license", …}' />
          <div className="form-actions">
            <button className="primary" disabled={!doc || act.busy} onClick={() => apply("install")}>Aplicar licença</button>
            <button disabled={!doc || act.busy} onClick={() => apply("authorization")}>Aplicar renovação</button>
            {l?.validation === "online" && <button disabled={act.busy} onClick={() => act.run(async () => {
              const r = await post<{ label: string; message: string }>("/license/check-online"); reload();
              act.setMsg({ kind: "ok", text: `${r.label}. ${r.message}` });
            })}>Consultar servidor agora</button>}
          </div>
        </section>
      )}
      {lic.data && lic.data.documents.length > 0 && (
        <>
          <h2 className="section">Documentos aplicados</h2>
          <ul className="history">{lic.data.documents.map((d, i) => (
            <li key={i}>{fmtDate(d.applied_at)} — {d.kind === "license" ? "Licença" : `Autorização nº ${d.seq}`} {d.license_id} ({d.status === "active" ? "vigente" : "substituída"}) por {d.applied_by}</li>
          ))}</ul>
        </>
      )}
    </Page>
  );
}
