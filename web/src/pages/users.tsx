import { useState, type FormEvent } from "react";
import { del, fmtDate, get, patch, post, put, type Me } from "../api";
import { Field, Notice, Page, useAction, useLoad } from "../ui";
import type { Site } from "../types";

type Grant = { role: string; site_id: string | null };
type User = { id: string; username: string; display_name: string; email: string | null; active: boolean;
  locked: boolean; must_change: boolean; mfa_required: boolean; mfa_enabled: boolean; last_login_at: string | null;
  roles: Grant[] };
type Role = { id: string; code: string; name: string; system: boolean; permissions: string[] };

export function UsersPage({ me }: { me: Me }) {
  const manage = me.permissions.includes("core.users.manage");
  const users = useLoad(() => get<User[]>("/users"));
  const roles = useLoad(() => get<Role[]>("/roles"));
  const sites = useLoad(() => get<Site[]>("/sites"));
  const act = useAction();
  const [creating, setCreating] = useState(false);
  const roleName = (code: string) => roles.data?.find((r) => r.code === code)?.name ?? code;
  const siteName = (id: string | null) => (id ? sites.data?.find((s) => s.id === id)?.name ?? "?" : "todas as unidades");

  return (
    <Page title="Usuários e papéis" intro="Cada papel pode valer para todas as unidades ou só para uma."
      actions={manage && <button className="primary" onClick={() => setCreating(true)}>Novo usuário</button>}>
      {act.view}
      <Notice kind="error">{users.error}</Notice>
      {manage && <ProfilesPanel onChange={() => void roles.reload()} />}
      {creating && roles.data && sites.data && (
        <NewUser roles={roles.data} sites={sites.data} onClose={() => setCreating(false)}
          onSaved={() => { setCreating(false); void users.reload(); }} />
      )}
      <div className="table-wrap">
        <table>
          <thead><tr><th>Usuário</th><th>Papéis</th><th>Situação</th><th>Último acesso</th>{manage && <th />}</tr></thead>
          <tbody>
            {users.data?.map((u) => (
              <tr key={u.id} className={u.active ? "" : "muted"}>
                <td><strong>{u.display_name}</strong><br /><span className="sub">{u.username}</span></td>
                <td>{u.roles.map((g, i) => <div key={i}>{roleName(g.role)} <span className="sub">({siteName(g.site_id)})</span></div>)}</td>
                <td>
                  {!u.active ? "Inativo" : u.locked ? "Bloqueado" : u.must_change ? "Aguardando troca de senha" : "Ativo"}
                  {u.mfa_enabled && <span className="tag">2 etapas</span>}
                </td>
                <td>{fmtDate(u.last_login_at)}</td>
                {manage && (
                  <td className="row-actions">
                    {u.locked && <button onClick={() => act.run(async () => { await post(`/users/${u.id}/unlock`); await users.reload(); }, "Usuário desbloqueado.")}>Desbloquear</button>}
                    <button onClick={() => {
                      const pw = window.prompt(`Nova senha provisória para ${u.username} (será trocada no próximo acesso):`);
                      if (pw) void act.run(() => post(`/users/${u.id}/reset-password`, { password: pw }), "Senha redefinida. As sessões abertas foram encerradas.");
                    }}>Redefinir senha</button>
                    {u.mfa_enabled && <button onClick={() => act.run(async () => { await del(`/users/${u.id}/mfa`); await users.reload(); }, "Segundo fator removido.")}>Remover 2 etapas</button>}
                    {u.id !== me.user_id && <button onClick={() => act.run(async () => { await patch(`/users/${u.id}`, { active: !u.active }); await users.reload(); }, u.active ? "Usuário desativado." : "Usuário reativado.")}>{u.active ? "Desativar" : "Reativar"}</button>}
                    {roles.data && sites.data && <RoleEditor user={u} roles={roles.data} sites={sites.data}
                      onSaved={() => users.reload()} />}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Page>
  );
}

function GrantsInput({ roles, sites, value, onChange }: { roles: Role[]; sites: Site[]; value: Grant[];
  onChange: (g: Grant[]) => void }) {
  return (
    <div className="grants">
      {value.map((g, i) => (
        <div key={i} className="grant">
          <select aria-label="Papel" value={g.role} onChange={(e) => onChange(value.map((x, j) => j === i ? { ...x, role: e.target.value } : x))}>
            {roles.map((r) => <option key={r.code} value={r.code}>{r.name}</option>)}
          </select>
          <select aria-label="Unidade" value={g.site_id ?? ""} onChange={(e) => onChange(value.map((x, j) => j === i ? { ...x, site_id: e.target.value || null } : x))}>
            <option value="">Todas as unidades</option>
            {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <button type="button" className="link" onClick={() => onChange(value.filter((_, j) => j !== i))}>Remover</button>
        </div>
      ))}
      <button type="button" onClick={() => onChange([...value, { role: roles[0]?.code ?? "", site_id: null }])}>Adicionar papel</button>
    </div>
  );
}

function NewUser({ roles, sites, onClose, onSaved }: { roles: Role[]; sites: Site[]; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ username: "", display_name: "", email: "", password: "", mfa_required: false });
  const [grants, setGrants] = useState<Grant[]>([{ role: "recepcionista", site_id: null }]);
  const [avail, setAvail] = useState<boolean | null>(null);
  const act = useAction();
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (await act.run(() => post("/users", { ...f, email: f.email || null, roles: grants }))) onSaved();
  }
  return (
    <form className="panel" onSubmit={submit} aria-label="Novo usuário">
      <h2>Novo usuário</h2>
      <div className="grid2">
        <Field label="Nome completo"><input value={f.display_name} onChange={(e) => setF({ ...f, display_name: e.target.value })} required /></Field>
        <Field label="Usuário (login)" hint={avail === false ? "Este login já está em uso na plataforma: escolha outro." : avail ? "Login disponível." : "Sem espaços; único na plataforma VYONIX"}>
          <input value={f.username} onChange={(e) => { setF({ ...f, username: e.target.value }); setAvail(null); }} required aria-invalid={avail === false}
            onBlur={() => { if (f.username.trim()) get<{ available: boolean }>(`/users/login-available?login=${encodeURIComponent(f.username.trim())}`).then((r) => setAvail(r.available)).catch(() => setAvail(null)); }} /></Field>
        <Field label="E-mail"><input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
        <Field label="Senha provisória" hint="Trocada no primeiro acesso"><input type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} required autoComplete="new-password" /></Field>
      </div>
      <label className="check"><input type="checkbox" checked={f.mfa_required} onChange={(e) => setF({ ...f, mfa_required: e.target.checked })} /> Exigir verificação em duas etapas</label>
      <h3>Papéis</h3>
      <GrantsInput roles={roles} sites={sites} value={grants} onChange={setGrants} />
      {act.view}
      <div className="form-actions"><button className="primary" disabled={act.busy}>Criar usuário</button><button type="button" onClick={onClose}>Cancelar</button></div>
    </form>
  );
}

function RoleEditor({ user, roles, sites, onSaved }: { user: User; roles: Role[]; sites: Site[]; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [grants, setGrants] = useState<Grant[]>(user.roles);
  const act = useAction();
  if (!open) return <button onClick={() => { setGrants(user.roles); setOpen(true); }}>Papéis</button>;
  return (
    <div className="popover" role="dialog" aria-label={`Papéis de ${user.username}`}>
      <GrantsInput roles={roles} sites={sites} value={grants} onChange={setGrants} />
      {act.view}
      <div className="form-actions">
        <button className="primary" onClick={async () => { if (await act.run(() => put(`/users/${user.id}/roles`, { roles: grants }))) { setOpen(false); onSaved(); } }}>Salvar papéis</button>
        <button onClick={() => setOpen(false)}>Cancelar</button>
      </div>
    </div>
  );
}

type Templates = { templates: { code: string; name: string; description: string; active: boolean }[];
  structures: { code: string; name: string; roles: string[] }[] };

/** Perfis opcionais: a instituição ativa só os que usa (modelos personalizáveis depois). */
function ProfilesPanel({ onChange }: { onChange: () => void }) {
  const [open, setOpen] = useState(false);
  const t = useLoad(async () => (open ? await get<Templates>("/role-templates") : null), [open]);
  const act = useAction();
  async function run(path: string, msg: string) {
    await act.run(async () => { await post(path); await t.reload(); onChange(); }, msg);
  }
  return (
    <section className="panel" aria-label="Perfis da instituição">
      <div className="row-actions"><h2>Perfis da instituição</h2>
        <button className="link" onClick={() => setOpen(!open)}>{open ? "Fechar" : "Modelos de perfil"}</button></div>
      {open && <>
        <p className="field-hint">Os perfis são sugestões: ative só os que a instituição usa. Um usuário pode ter várias funções; ninguém concede permissões que não possui.</p>
        {act.view}
        <div className="row-actions" role="group" aria-label="Estruturas sugeridas">
          {(t.data?.structures ?? []).map((s) => <button key={s.code} onClick={() => void run(`/role-templates/structure/${s.code}`, `Perfis sugeridos para ${s.name} ativados.`)}>
            {s.name}{s.roles.length ? "" : " (só os perfis básicos)"}</button>)}
        </div>
        <ul className="history">{(t.data?.templates ?? []).map((x) => (
          <li key={x.code}><strong>{x.name}</strong> — {x.description} {x.active ? <span className="tag">ativo</span>
            : <button className="link" onClick={() => void run(`/role-templates/${x.code}/activate`, `Perfil ${x.name} ativado.`)}>Ativar</button>}</li>))}
        </ul>
      </>}
    </section>
  );
}
