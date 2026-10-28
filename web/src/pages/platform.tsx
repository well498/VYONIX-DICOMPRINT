import { useState, type FormEvent } from "react";
import { fmtDate, get, patch, post, type Me } from "../api";
import { Field, Notice, Page, useAction, useLoad } from "../ui";

type Inst = { id: string; code: string; name: string; legal_name: string | null; document: string | null;
  institution_type: string | null; active: boolean; status_reason: string | null; contact_name: string | null;
  contact_email: string | null; contracted_modules: string[]; enabled_modules: string[]; users: number; sites: number;
  created_at: string };

const MODULES: [string, string][] = [["pacs", "PACS e Viewer"], ["report", "Telelaudos"], ["ris", "RIS / Agenda"], ["print", "DICOM Print"]];
const STRUCTURES: [string, string][] = [["clinica_pequena", "Clínica pequena"], ["cdi", "Centro de diagnóstico (CDI)"],
  ["hospital", "Hospital"], ["personalizado", "Personalizado (sem perfis extras)"]];
const EMPTY = { name: "", legal_name: "", document: "", institution_type: "clinica", code: "", sites: "", contact_name: "",
  contact_email: "", contact_phone: "", modules: [] as string[], structure: "clinica_pequena", admin_login: "",
  admin_name: "", admin_password: "" };

function slug(s: string) {
  return s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40);
}

/** Administração VYONIX: instituições (dados administrativos), assistente de cadastro e ativação. Sem dados clínicos. */
export function PlatformPage({ me }: { me: Me }) {
  const list = useLoad(async () => await get<{ items: Inst[]; types: Record<string, string> }>("/platform/institutions"), []);
  const canManage = me.permissions.includes("platform.institutions.manage");
  const [creating, setCreating] = useState(false);
  const [f, setF] = useState(EMPTY);
  const [off, setOff] = useState<{ id: string; reason: string } | null>(null);
  const act = useAction();
  const types = list.data?.types ?? {};
  async function submit(e: FormEvent) {
    e.preventDefault();
    const ok = await act.run(async () => {
      await post("/platform/institutions", { ...f, code: f.code || slug(f.name), document: f.document || null,
        legal_name: f.legal_name || null, sites: f.sites.split("\n").map((x) => x.trim()).filter(Boolean) });
      await list.reload();
    }, "Instituição cadastrada. Envie ao gestor o login e a senha provisória (troca obrigatória no primeiro acesso).");
    if (ok) { setF(EMPTY); setCreating(false); }
  }
  async function setActive(i: Inst, active: boolean, reason: string | null) {
    const ok = await act.run(async () => { await patch(`/platform/institutions/${i.id}`, { active, reason }); await list.reload(); },
      active ? `${i.name} reativada.` : `${i.name} desativada: acessos bloqueados e sessões encerradas. Nada foi apagado.`);
    if (ok) setOff(null);
  }
  return (
    <Page title="Administração VYONIX" intro="Instituições atendidas pela plataforma: cadastro, módulos contratados e situação. Esta área não dá acesso a dados clínicos."
      actions={canManage && !creating ? <button className="primary" onClick={() => setCreating(true)}>Nova instituição</button> : undefined}>
      {act.view}
      <Notice kind="error">{list.error}</Notice>
      {creating && (
        <form className="panel" aria-label="Nova instituição" onSubmit={submit}>
          <h2>1. Dados institucionais</h2>
          <div className="grid2">
            <Field label="Nome"><input required maxLength={200} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
            <Field label="Razão social"><input maxLength={200} value={f.legal_name} onChange={(e) => setF({ ...f, legal_name: e.target.value })} /></Field>
            <Field label="CNPJ" hint="Conferido pelos dígitos verificadores"><input maxLength={20} value={f.document} onChange={(e) => setF({ ...f, document: e.target.value })} /></Field>
            <Field label="Tipo de instituição"><select value={f.institution_type} onChange={(e) => setF({ ...f, institution_type: e.target.value })}>
              {Object.entries(types).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
            <Field label="Código interno" hint={`Sem acentos; padrão: ${slug(f.name) || "—"}`}><input maxLength={40} value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} /></Field>
            <Field label="Unidades" hint="Uma por linha (a primeira é a principal)"><textarea rows={3} value={f.sites} onChange={(e) => setF({ ...f, sites: e.target.value })} /></Field>
            <Field label="Responsável"><input maxLength={120} value={f.contact_name} onChange={(e) => setF({ ...f, contact_name: e.target.value })} /></Field>
            <Field label="E-mail de contato"><input type="email" maxLength={200} value={f.contact_email} onChange={(e) => setF({ ...f, contact_email: e.target.value })} /></Field>
          </div>
          <h2>2. Módulos contratados</h2>
          <div className="filters">{MODULES.map(([k, v]) => <label key={k} className="check"><input type="checkbox" checked={f.modules.includes(k)}
            onChange={(e) => setF({ ...f, modules: e.target.checked ? [...f.modules, k] : f.modules.filter((x) => x !== k) })} /> {v}</label>)}</div>
          <p className="field-hint">Registro do contrato. O uso de cada módulo continua dependendo da licença assinada.</p>
          <h2>3. Estrutura organizacional</h2>
          <Field label="Modelo"><select value={f.structure} onChange={(e) => setF({ ...f, structure: e.target.value })}>
            {STRUCTURES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
          <h2>4. Administração inicial</h2>
          <div className="grid2">
            <Field label="Nome do gestor"><input required maxLength={120} value={f.admin_name} onChange={(e) => setF({ ...f, admin_name: e.target.value })} /></Field>
            <Field label="Login do gestor" hint="Único na plataforma"><input required maxLength={60} value={f.admin_login} onChange={(e) => setF({ ...f, admin_login: e.target.value })} /></Field>
            <Field label="Senha provisória" hint="Trocada no primeiro acesso"><input type="password" required autoComplete="new-password" value={f.admin_password} onChange={(e) => setF({ ...f, admin_password: e.target.value })} /></Field>
          </div>
          <p className="field-hint">5. Os demais profissionais são cadastrados depois pelo gestor da instituição.</p>
          <div className="form-actions"><button className="primary" disabled={act.busy}>Cadastrar instituição</button>
            <button type="button" onClick={() => setCreating(false)}>Cancelar</button></div>
        </form>)}
      <div className="table-wrap"><table>
        <thead><tr><th>Instituição</th><th>Tipo</th><th>Módulos</th><th>Usuários / unidades</th><th>Situação</th>{canManage && <th>Ações</th>}</tr></thead>
        <tbody>{(list.data?.items ?? []).map((i) => (
          <tr key={i.id} className={i.active ? "" : "muted"}>
            <td><strong>{i.name}</strong><br /><span className="sub">{i.code}{i.document ? ` · CNPJ ${i.document.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, "$1.$2.$3/$4-$5")}` : ""}</span></td>
            <td>{types[i.institution_type ?? ""] ?? "—"}</td>
            <td>contratados: {i.contracted_modules.join(", ") || "—"}<br /><span className="sub">habilitados: {i.enabled_modules.join(", ") || "—"}</span></td>
            <td>{i.users} / {i.sites}</td>
            <td>{i.active ? "Ativa" : `Desativada${i.status_reason ? ` — ${i.status_reason}` : ""}`}<br /><span className="sub">desde {fmtDate(i.created_at, false)}</span></td>
            {canManage && <td className="actions">{i.active ? (off?.id === i.id ? (
              <form className="filters" aria-label={`Desativar ${i.name}`} onSubmit={(e) => { e.preventDefault(); void setActive(i, false, off.reason); }}>
                <input required maxLength={300} aria-label="Motivo" placeholder="Motivo" value={off.reason} onChange={(e) => setOff({ ...off, reason: e.target.value })} />
                <button className="primary" disabled={act.busy}>Confirmar</button></form>)
              : <button onClick={() => setOff({ id: i.id, reason: "" })}>Desativar</button>)
              : <button onClick={() => void setActive(i, true, null)}>Reativar</button>}</td>}
          </tr>))}</tbody>
      </table>{list.data && !list.data.items.length && <p className="empty">Nenhuma instituição cadastrada.</p>}</div>
    </Page>
  );
}
