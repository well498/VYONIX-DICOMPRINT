import { get, type Me } from "../api";
import { Notice, Page, useLoad } from "../ui";
import { STATE_LABEL, tone, type LicenseInfo } from "../types";

type Health = { status: "ok" | "atenção" | "falha"; problems: string[] };

function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Pendências do dia conforme o papel: saúde do sistema, exames de hoje, laudos e achados críticos. */
function Pending({ me }: { me: Me }) {
  const can = (p: string) => me.permissions.includes(p);
  const data = useLoad(async () => {
    const out: { health?: Health; today?: number; toReport?: number; critical?: number } = {};
    const jobs: Promise<void>[] = [];
    if (can("core.settings.read")) jobs.push(get<Health>("/health/detail").then((h) => { out.health = h; }).catch(() => {}));
    if (can("ris.schedule.read")) jobs.push(get<{ items: unknown[] }>(`/ris/worklist?date_from=${todayIso()}&date_to=${todayIso()}`)
      .then((r) => { out.today = r.items.length; }).catch(() => {}));
    if (can("report.read")) {
      jobs.push(get<{ items: unknown[] }>("/report/worklist?status=pending").then((r) => { out.toReport = r.items.length; }).catch(() => {}));
      jobs.push(get<{ items: unknown[] }>("/report/critical").then((r) => { out.critical = r.items.length; }).catch(() => {}));
    }
    await Promise.all(jobs);
    return out;
  }, []);
  const d = data.data;
  if (!d || (d.health === undefined && d.today === undefined && d.toReport === undefined)) return null;
  return (
    <>
      <h2 className="section">Pendências</h2>
      <div className="card-row" role="group" aria-label="Pendências">
        {d.health && <a className="card" href="#/inicio" title={d.health.problems.join("\n")}>
          <span className="card-label">Sistema</span><strong>{d.health.status === "ok" ? "OK" : d.health.status === "falha" ? "Falha" : "Atenção"}</strong>
          {d.health.problems.length > 0 && <span className="field-hint">{d.health.problems[0]}</span>}</a>}
        {d.today !== undefined && <a className="card" href="#/agenda"><span className="card-label">Exames hoje (a realizar)</span><strong>{d.today}</strong></a>}
        {d.toReport !== undefined && <a className="card" href="#/laudos"><span className="card-label">Estudos sem laudo</span><strong>{d.toReport}</strong></a>}
        {d.critical !== undefined && <a className="card" href="#/laudos"><span className="card-label">Achados críticos a comunicar</span>
          <strong>{d.critical}</strong></a>}
      </div>
    </>
  );
}

export function Dashboard({ me }: { me: Me }) {
  const canLicense = me.permissions.includes("core.license.read");
  const lic = useLoad(() => (canLicense ? get<LicenseInfo>("/license") : Promise.resolve(null)), [canLicense]);
  const first = me.display_name.split(" ")[0];
  const attention = lic.data?.modules.filter((m) => m.kind && tone(m.state) !== "ok") ?? [];
  return (
    <Page title={`Olá, ${first}`} intro="Situação desta instalação do VYONIX.">
      <Notice kind="error">{lic.error}</Notice>
      <Pending me={me} />
      {canLicense && lic.data && (
        <>
          {!lic.data.license && (
            <Notice kind="warn">Nenhuma licença instalada. O sistema funciona com até 3 usuários e 1 unidade até a
              licença ser aplicada. <a href="#/comercial">Solicitar licença ou demonstração</a>.</Notice>
          )}
          {attention.map((m) => (
            <Notice key={m.module} kind={tone(m.state) === "warn" ? "warn" : "error"}>
              <strong>{m.label}: {STATE_LABEL[m.state] ?? m.state}.</strong> {m.message}</Notice>
          ))}
          <h2 className="section">Módulos licenciados</h2>
          <ul className="lightbox">
            {lic.data.modules.filter((m) => m.kind).map((m) => (
              <li key={m.module} className={`film film-${tone(m.state)}`}>
                <span className="film-name">{m.label}</span>
                <span className="film-state">{STATE_LABEL[m.state] ?? m.state}</span>
              </li>
            ))}
            {lic.data.modules.every((m) => !m.kind) && <li className="film film-off">
              <span className="film-name">Nenhum módulo licenciado</span></li>}
          </ul>
        </>
      )}
      {!canLicense && <p className="intro">Use o menu para acessar as funções liberadas para o seu papel.</p>}
    </Page>
  );
}
