import { get, type Me } from "../api";
import { Notice, Page, useLoad } from "../ui";
import { STATE_LABEL, tone, type LicenseInfo } from "../types";

export function Dashboard({ me }: { me: Me }) {
  const canLicense = me.permissions.includes("core.license.read");
  const lic = useLoad(() => (canLicense ? get<LicenseInfo>("/license") : Promise.resolve(null)), [canLicense]);
  const first = me.display_name.split(" ")[0];
  const attention = lic.data?.modules.filter((m) => m.kind && tone(m.state) !== "ok") ?? [];
  return (
    <Page title={`Olá, ${first}`} intro="Situação desta instalação do VYONIX.">
      <Notice kind="error">{lic.error}</Notice>
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
