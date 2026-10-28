import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ApiError, get, post, setCsrf, type Me } from "./api";
import { AccessGate, Login } from "./pages/access";
import { AuditPage } from "./pages/audit";
import { CommercialPage } from "./pages/commercial";
import { Dashboard } from "./pages/dashboard";
import { ImagesPage } from "./pages/images";
import { LicensePage } from "./pages/license";
import { PatientsPage } from "./pages/patients";
import { SchedulePage } from "./pages/schedule";
import { SettingsPage } from "./pages/settings";
import { SitesPage } from "./pages/sites";
import { UsersPage } from "./pages/users";

type Route = { id: string; label: string; perm?: string; view: (me: Me) => ReactNode };

const ROUTES: Route[] = [
  { id: "inicio", label: "Início", view: (me) => <Dashboard me={me} /> },
  { id: "pacientes", label: "Pacientes", perm: "clinical.patients.read", view: (me) => <PatientsPage me={me} /> },
  { id: "agenda", label: "Agenda", perm: "ris.schedule.read", view: (me) => <SchedulePage me={me} /> },
  { id: "imagens", label: "Imagens", perm: "pacs.studies.read", view: (me) => <ImagesPage me={me} /> },
  { id: "usuarios", label: "Usuários e papéis", perm: "core.users.read", view: (me) => <UsersPage me={me} /> },
  { id: "unidades", label: "Unidades", perm: "core.settings.read", view: (me) => <SitesPage me={me} /> },
  { id: "configuracoes", label: "Configurações", perm: "core.settings.read", view: (me) => <SettingsPage me={me} /> },
  { id: "licenca", label: "Licença e módulos", perm: "core.license.read", view: (me) => <LicensePage me={me} /> },
  { id: "comercial", label: "Contratar e demonstrar", perm: "core.license.read",
    view: (me) => <CommercialPage me={me} /> },
  { id: "auditoria", label: "Auditoria", perm: "core.audit.read", view: () => <AuditPage /> },
];

function currentRoute() { return location.hash.replace(/^#\/?/, "") || "inicio"; }

export function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [route, setRoute] = useState(currentRoute());

  const refresh = useCallback(async () => {
    try {
      const m = await get<Me>("/auth/me");
      setCsrf(m.csrf); setMe(m);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) { setMe(null); return; }
      setMe(null);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    const on = () => setRoute(currentRoute());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  if (me === undefined) return <div className="boot" aria-busy="true">Carregando…</div>;
  if (me === null) return <Login onDone={(m) => { setCsrf(m.csrf); setMe(m); }} />;
  if (me.stage !== "ok") return <AccessGate me={me} onDone={refresh} onLogout={() => setMe(null)} />;

  const allowed = ROUTES.filter((r) => !r.perm || me.permissions.includes(r.perm));
  const active = allowed.find((r) => r.id === route) ?? allowed[0];

  async function logout() {
    try { await post("/auth/logout"); } finally { setMe(null); location.hash = ""; }
  }

  return (
    <div className="shell">
      <nav className="rail" aria-label="Navegação principal">
        <div className="brand">
          <svg viewBox="0 0 32 32" aria-hidden="true"><path d="M8 9l8 15 8-15" /></svg>
          <span>VYONIX</span>
        </div>
        <ul>
          {allowed.map((r) => (
            <li key={r.id}>
              <a href={`#/${r.id}`} aria-current={r.id === active.id ? "page" : undefined}>{r.label}</a>
            </li>
          ))}
        </ul>
        <div className="who">
          <strong>{me.display_name}</strong>
          <span>{me.roles.map((r) => r.name).join(", ") || "Sem papel"}</span>
          <button className="link" onClick={logout}>Sair</button>
        </div>
      </nav>
      <main id="conteudo">{active.view(me)}</main>
    </div>
  );
}
