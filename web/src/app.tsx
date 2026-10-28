import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ApiError, get, post, setCsrf, type Me } from "./api";
import { AccessGate, Login } from "./pages/access";
import { AuditPage } from "./pages/audit";
import { CommercialPage } from "./pages/commercial";
import { Dashboard } from "./pages/dashboard";
import { ExamCenterPage } from "./pages/examcenter";
import { ImagesPage } from "./pages/images";
import { LicensePage } from "./pages/license";
import { PatientsPage } from "./pages/patients";
import { PlatformPage } from "./pages/platform";
import { ReconcilePage } from "./pages/reconcile";
import { ReportsPage } from "./pages/reports";
import { SchedulePage } from "./pages/schedule";
import { SettingsPage } from "./pages/settings";
import { SitesPage } from "./pages/sites";
import { TechnicianPage } from "./pages/technician";
import { StationsPage } from "./pages/stations";
import { UsersPage } from "./pages/users";

type NavState = "expanded" | "collapsed" | "hidden";
type Route = { id: string; label: string; perm?: string; operator?: boolean; view: (me: Me) => ReactNode };

const ROUTES: Route[] = [
  { id: "inicio", label: "Início", view: (me) => <Dashboard me={me} /> },
  { id: "vyonix", label: "Administração VYONIX", perm: "platform.institutions.read", operator: true,
    view: (me) => <PlatformPage me={me} /> },
  { id: "pacientes", label: "Pacientes", perm: "clinical.patients.read", view: (me) => <PatientsPage me={me} /> },
  { id: "agenda", label: "Agenda", perm: "ris.schedule.read", view: (me) => <SchedulePage me={me} /> },
  { id: "tecnico", label: "Painel do técnico", perm: "ris.exam.perform", view: (me) => <TechnicianPage me={me} /> },
  { id: "central", label: "Central de exames", perm: "ris.schedule.read", view: (me) => <ExamCenterPage me={me} /> },
  { id: "laudos", label: "Laudos", perm: "report.read", view: (me) => <ReportsPage me={me} /> },
  { id: "conciliacao", label: "Conciliação", perm: "clinical.studies.reconcile", view: (me) => <ReconcilePage me={me} /> },
  { id: "imagens", label: "Imagens", perm: "pacs.studies.read", view: (me) => <ImagesPage me={me} /> },
  { id: "estacoes", label: "Estações DICOM", perm: "pacs.admin", view: (me) => <StationsPage me={me} /> },
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
  const [navState, setNavState] = useState<NavState>(() => {
    try { const v = localStorage.getItem("vyx-nav"); return v === "collapsed" || v === "hidden" ? v : "expanded"; }
    catch { return "expanded"; }
  });
  const [drawer, setDrawer] = useState(false);
  const [flavor, setFlavor] = useState("commercial");
  useEffect(() => { get<{ flavor?: string }>("/health").then((h) => setFlavor(h.flavor ?? "commercial")).catch(() => undefined); }, []);
  const banner = flavor === "homologacao" ? <div className="homolog-banner" role="note">HOMOLOGAÇÃO INTERNA — SEM LICENÇA COMERCIAL — somente dados fictícios, não usar com pacientes</div> : null;

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
  if (me === null) return <>{banner}<Login onDone={(m) => { setCsrf(m.csrf); setMe(m); }} /></>;
  if (me.stage !== "ok") return <>{banner}<AccessGate me={me} onDone={refresh} onLogout={() => setMe(null)} /></>;

  const allowed = ROUTES.filter((r) => (!r.perm || me.permissions.includes(r.perm))
    && (!r.operator || me.organization?.kind === "operator"));
  const active = allowed.find((r) => r.id === route) ?? allowed[0];

  async function logout() {
    try { await post("/auth/logout"); } finally { setMe(null); location.hash = ""; }
  }

  const short = (label: string) => label.split(/\s+/).filter((w) => w.length > 2 || w === w.toUpperCase()).slice(0, 2)
    .map((w) => w[0]).join("").toUpperCase();
  function setNav(v: NavState) { setNavState(v); try { localStorage.setItem("vyx-nav", v); } catch { /* sem armazenamento */ } }

  return (
    <div className={`shell nav-${navState}${drawer ? " drawer-open" : ""}`}>
      <div className="topbar">
        <button type="button" className="menu-btn" aria-expanded={drawer} aria-controls="menu-principal"
          onClick={() => setDrawer(!drawer)}>{drawer ? "Fechar menu" : "Menu"}</button>
        <span className="topbar-title">{active.label}</span>
      </div>
      {navState === "hidden" && <button type="button" className="nav-show" onClick={() => setNav("expanded")}>Mostrar menu</button>}
      {drawer && <div className="drawer-backdrop" onClick={() => setDrawer(false)} />}
      <nav className="rail" id="menu-principal" aria-label="Navegação principal">
        <div className="brand">
          <svg viewBox="0 0 32 32" aria-hidden="true"><path d="M8 9l8 15 8-15" /></svg>
          <span className="brand-name">VYONIX</span>
        </div>
        <ul>
          {allowed.map((r) => (
            <li key={r.id}>
              <a href={`#/${r.id}`} aria-current={r.id === active.id ? "page" : undefined} title={r.label}
                onClick={() => setDrawer(false)}><span className="nav-abbr" aria-hidden="true">{short(r.label)}</span>
                <span className="nav-label">{r.label}</span></a>
            </li>
          ))}
        </ul>
        <div className="nav-modes" role="group" aria-label="Barra lateral">
          {navState === "expanded"
            ? <button type="button" className="link" onClick={() => setNav("collapsed")}>Recolher</button>
            : <button type="button" className="link" onClick={() => setNav("expanded")}>Expandir</button>}
          <button type="button" className="link" onClick={() => setNav("hidden")}>Ocultar</button>
        </div>
        <div className="who">
          <strong>{me.display_name}</strong>
          <span>{me.roles.map((r) => r.name).join(", ") || "Sem papel"}</span>
          <button className="link" onClick={logout}>Sair</button>
        </div>
      </nav>
      <main id="conteudo">{banner}{active.view(me)}</main>
    </div>
  );
}
