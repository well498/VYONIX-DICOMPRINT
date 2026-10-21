import { useState } from "react";
import { fmtDate, get } from "../api";
import { Notice, Page, useAction, useLoad } from "../ui";
import type { AuditRow } from "../types";

export function AuditPage() {
  const [action, setAction] = useState("");
  const [actor, setActor] = useState("");
  const [query, setQuery] = useState({ action: "", actor: "" });
  const rows = useLoad(() => {
    const q = new URLSearchParams({ limit: "200" });
    if (query.action) q.set("action", query.action);
    if (query.actor) q.set("actor", query.actor);
    return get<AuditRow[]>(`/audit?${q}`);
  }, [query]);
  const verify = useAction();
  const [chain, setChain] = useState<string>("");

  return (
    <Page title="Auditoria" intro="Registro encadeado de acessos e alterações. Cada registro guarda o resumo do anterior: uma alteração feita fora do VYONIX aparece na verificação."
      actions={<button disabled={verify.busy} onClick={() => verify.run(async () => {
        const r = await get<{ ok: boolean; broken: number[] }>("/audit/verify");
        setChain(r.ok ? "Cadeia íntegra: nenhum registro alterado." :
          `Cadeia rompida nos registros ${r.broken.join(", ")}. Preserve o banco e acione o suporte.`);
      })}>Verificar integridade</button>}>
      {chain && <Notice kind={chain.startsWith("Cadeia íntegra") ? "ok" : "error"}>{chain}</Notice>}
      {verify.view}
      <form className="filters" onSubmit={(e) => { e.preventDefault(); setQuery({ action, actor }); }}>
        <input placeholder="Ação (ex.: auth.*)" value={action} onChange={(e) => setAction(e.target.value)}
          aria-label="Filtrar por ação" />
        <input placeholder="Usuário" value={actor} onChange={(e) => setActor(e.target.value)}
          aria-label="Filtrar por usuário" />
        <button>Filtrar</button>
      </form>
      <Notice kind="error">{rows.error}</Notice>
      <div className="table-wrap">
        <table>
          <thead><tr><th>#</th><th>Quando</th><th>Usuário</th><th>Ação</th><th>Objeto</th><th>Detalhes</th><th>IP</th></tr></thead>
          <tbody>
            {rows.data?.map((r) => (
              <tr key={r.seq}>
                <td className="num">{r.seq}</td><td>{fmtDate(r.at)}</td><td>{r.actor}</td>
                <td><code>{r.action}</code></td>
                <td>{r.target_type ? `${r.target_type} ${r.target_id?.slice(0, 8) ?? ""}` : "—"}</td>
                <td className="details">{Object.keys(r.details).length ? JSON.stringify(r.details) : "—"}</td>
                <td>{r.ip ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.data?.length === 0 && <p className="empty">Nenhum registro com esses filtros.</p>}
      </div>
    </Page>
  );
}
