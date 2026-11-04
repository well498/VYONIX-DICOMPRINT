import { fmtDate, get, post, type Me } from "../api";
import { Notice, Page, useAction, useLoad } from "../ui";
import type { ModuleRow } from "../types";

type Comp = { problems?: string[]; [k: string]: unknown };
type SystemInfo = {
  version: string; flavor: string; mode: string;
  licensing: { required: boolean; message: string };
  health: { status: string; checked_at?: string; problems: string[]; components: Record<string, Comp> };
  database: { ok: boolean; server_version?: string; size_bytes?: number; problem?: string };
  backups: { available: boolean; count: number; items: { name: string; created_at?: string; reason?: string }[]; message?: string };
  updates: { available: boolean; items: { id: string; kind: string; status: string; created_at: string; version: string | null; message: string | null }[]; message?: string };
  modules: ModuleRow[];
  separate_products: { name: string; note: string }[];
};

const COMP: Record<string, string> = { database: "Banco de dados", events: "Eventos internos", pacs: "PACS (recepção de imagens)",
  dicom_qr: "Consulta DICOM e worklist", pacs_backup: "Backup do PACS", pacs_integrity: "Integridade do PACS",
  modules: "Módulos", disk: "Espaço em disco" };
const STATUS: Record<string, string> = { ok: "Funcionando", "atenção": "Funcionando com avisos", falha: "Com falha" };
const RUN: Record<string, string> = { succeeded: "concluída", failed: "com erro", rolled_back: "desfeita", running: "em andamento" };

function mb(n?: number) { return n === undefined ? "—" : `${(n / 1024 / 1024).toFixed(1)} MB`; }

/** Sistema e atualizações — substitui "Licença e módulos". A plataforma não usa licença nem ativação. */
export function SystemPage({ me }: { me: Me }) {
  const modManage = me.permissions.includes("core.modules.manage");
  const d = useLoad(() => get<SystemInfo>("/system"));
  const act = useAction();
  const x = d.data;
  return (
    <Page title="Sistema e atualizações" intro="Versão instalada, serviços, banco de dados, cópias de segurança, atualizações e módulos.">
      <Notice kind="error">{d.error}</Notice>
      {act.view}
      {x && <>
        <dl className="facts">
          <div><dt>Versão</dt><dd>{x.version}{x.flavor === "homologacao" ? " (homologação interna)" : ""}</dd></div>
          <div><dt>Situação</dt><dd>{STATUS[x.health.status] ?? x.health.status}{x.health.checked_at ? ` · verificado ${fmtDate(x.health.checked_at)}` : ""}</dd></div>
          <div><dt>Banco de dados</dt><dd>{x.database.ok ? `PostgreSQL ${x.database.server_version} · ${mb(x.database.size_bytes)}` : `sem resposta (${x.database.problem})`}</dd></div>
          <div><dt>Licença</dt><dd>{x.licensing.message}</dd></div>
        </dl>
        {x.health.problems.length > 0 && <Notice kind="warn">{x.health.problems.join(" ")}</Notice>}

        <h2 className="section">Serviços e diagnóstico</h2>
        <ul className="checks">{Object.entries(x.health.components).map(([k, c]) => (
          <li key={k} className={(c.problems ?? []).length ? "no" : "ok"}>{(c.problems ?? []).length ? "⚠" : "✓"} {COMP[k] ?? k}
            {(c.problems ?? []).length ? ` — ${(c.problems ?? []).join(" ")}` : " — sem problemas"}</li>))}</ul>

        <h2 className="section">Cópias de segurança</h2>
        {x.backups.available ? <ul className="history">{x.backups.items.length ? x.backups.items.map((b) => (
          <li key={b.name}>{b.name}{b.created_at ? ` · ${fmtDate(b.created_at)}` : ""}{b.reason ? ` · ${b.reason}` : ""}</li>))
          : <li>Nenhuma cópia encontrada.</li>}</ul> : <p className="sub">{x.backups.message}</p>}

        <h2 className="section">Histórico de atualizações</h2>
        {x.updates.available ? <ul className="history">{x.updates.items.length ? x.updates.items.map((u) => (
          <li key={u.id}>{fmtDate(u.created_at)} · {u.kind === "update" ? "atualização" : u.kind} {u.version ?? ""} · {RUN[u.status] ?? u.status}{u.message ? ` — ${u.message}` : ""}</li>))
          : <li>Nenhuma execução registrada.</li>}</ul> : <p className="sub">{x.updates.message}</p>}

        <h2 className="section">Módulos</h2>
        <p className="field-hint">Habilitados por configuração administrativa. Desabilitar não apaga dados.</p>
        <div className="table-wrap"><table>
          <thead><tr><th>Módulo</th><th>Situação</th>{modManage && <th />}</tr></thead>
          <tbody>{x.modules.map((m) => (
            <tr key={m.code} className={m.available ? "" : "muted"}>
              <td><strong>{m.name}</strong><br /><span className="sub">{m.description}</span></td>
              <td>{!m.available ? "Em desenvolvimento" : m.always_enabled || m.status === "enabled" ? "Habilitado" : "Desabilitado"}</td>
              {modManage && <td className="row-actions">{m.available && !m.always_enabled && (m.status === "enabled"
                ? <button onClick={() => act.run(async () => { await post(`/modules/${m.code}/disable`, {}); await d.reload(); }, `${m.name} desabilitado. Os dados foram preservados.`)}>Desabilitar</button>
                : <button onClick={() => act.run(async () => { await post(`/modules/${m.code}/enable`); await d.reload(); }, `${m.name} habilitado.`)}>Habilitar</button>)}</td>}
            </tr>))}</tbody>
        </table></div>

        <h2 className="section">Produtos separados</h2>
        <ul className="history">{x.separate_products.map((p) => <li key={p.name}><strong>{p.name}</strong> — {p.note}</li>)}</ul>
      </>}
    </Page>
  );
}
