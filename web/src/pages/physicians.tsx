import { useState, type FormEvent } from "react";
import { fmtDate, get, post, upload, type Me } from "../api";
import { Field, Notice, useAction, useLoad } from "../ui";

type Link = { id: string; site_id: string | null; valid_from: string; valid_to: string | null };
type Physician = { id: string; user_id: string; full_name: string; crm: string; crm_uf: string; rqe: string | null;
  specialties: string[]; identification: string; active: boolean; links: Link[] };
type User = { id: string; username: string; display_name: string };
type Site = { id: string; name: string };

const UFS = "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split(" ");

function today() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; }

/** Cadastro de médicos (CRM/UF, RQE, especialidades) e vínculos com a organização ou unidades (TELELAUDO T1). */
export function PhysiciansPanel({ me }: { me: Me }) {
  void me;
  const list = useLoad(async () => (await get<{ items: Physician[] }>("/report/physicians")).items, []);
  const users = useLoad(async () => await get<User[]>("/users"), []);
  const sites = useLoad(async () => await get<Site[]>("/sites").catch(() => [] as Site[]), []);
  const [form, setForm] = useState({ user_id: "", full_name: "", crm: "", crm_uf: "CE", rqe: "", specialties: "" });
  const [link, setLink] = useState<{ pid: string; site: string; from: string } | null>(null);
  const act = useAction();
  const siteName = (id: string | null) => (id ? sites.data?.find((x) => x.id === id)?.name ?? "unidade" : "toda a organização");

  async function submit(e: FormEvent) {
    e.preventDefault();
    const ok = await act.run(async () => {
      await post("/report/physicians", { ...form, rqe: form.rqe || null,
        specialties: form.specialties.split(",").map((x) => x.trim()).filter(Boolean) });
      await list.reload();
    }, "Médico cadastrado. Inclua o vínculo com a organização ou as unidades.");
    if (ok) setForm({ user_id: "", full_name: "", crm: "", crm_uf: form.crm_uf, rqe: "", specialties: "" });
  }
  async function addLink(e: FormEvent) {
    e.preventDefault();
    if (!link) return;
    const ok = await act.run(async () => {
      await post(`/report/physicians/${link.pid}/links`, { site_id: link.site || null, valid_from: link.from });
      await list.reload();
    }, "Vínculo incluído.");
    if (ok) setLink(null);
  }
  async function endLink(id: string) {
    await act.run(async () => { await post(`/report/physician-links/${id}/end`, { valid_to: today() }); await list.reload(); },
      "Vínculo encerrado hoje.");
  }

  return (
    <section className="panel" aria-label="Médicos">
      <h2>Médicos</h2>
      <p className="field-hint">Só médico cadastrado, ativo e com vínculo vigente com a unidade do exame libera laudos. A liberação é sempre do próprio médico, com a senha dele.</p>
      {act.view}
      <Notice kind="error">{list.error}</Notice>
      <ul className="history">
        {(list.data ?? []).map((p) => (
          <li key={p.id}><strong>{p.identification}</strong>{p.specialties.length ? ` — ${p.specialties.join(", ")}` : ""}{p.active ? "" : " (inativo)"}
            <ul>{p.links.map((l) => (
              <li key={l.id}>{siteName(l.site_id)}: desde {fmtDate(l.valid_from + "T12:00:00", false)}
                {l.valid_to ? ` até ${fmtDate(l.valid_to + "T12:00:00", false)}` : <> (vigente) <button className="link" onClick={() => void endLink(l.id)}>Encerrar</button></>}</li>))}
              {!p.links.length && <li>Sem vínculo: não pode liberar laudos.</li>}
            </ul>
            {link?.pid === p.id ? (
              <form className="filters" aria-label={`Vínculo de ${p.full_name}`} onSubmit={addLink}>
                <select aria-label="Unidade do vínculo" value={link.site} onChange={(e) => setLink({ ...link, site: e.target.value })}>
                  <option value="">Toda a organização</option>
                  {(sites.data ?? []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
                </select>
                <input type="date" required aria-label="Início da vigência" value={link.from} onChange={(e) => setLink({ ...link, from: e.target.value })} />
                <button className="primary" disabled={act.busy}>Incluir vínculo</button>
              </form>) : <button className="link" onClick={() => setLink({ pid: p.id, site: "", from: today() })}>Incluir vínculo</button>}
          </li>))}
      </ul>
      <form aria-label="Cadastrar médico" onSubmit={submit}>
        <div className="grid2">
          <Field label="Usuário do médico" hint="O médico entra no VYONIX com o próprio usuário">
            <select required value={form.user_id} onChange={(e) => {
              const u = users.data?.find((x) => x.id === e.target.value);
              setForm({ ...form, user_id: e.target.value, full_name: form.full_name || (u?.display_name ?? "") });
            }}>
              <option value="">Selecione…</option>
              {(users.data ?? []).map((u) => <option key={u.id} value={u.id}>{u.display_name} ({u.username})</option>)}
            </select></Field>
          <Field label="Nome completo"><input required minLength={5} maxLength={160} value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></Field>
          <Field label="CRM"><input required maxLength={20} inputMode="numeric" value={form.crm} onChange={(e) => setForm({ ...form, crm: e.target.value })} /></Field>
          <Field label="UF do CRM"><select value={form.crm_uf} onChange={(e) => setForm({ ...form, crm_uf: e.target.value })}>
            {UFS.map((u) => <option key={u}>{u}</option>)}</select></Field>
          <Field label="RQE" hint="Opcional; vários separados por vírgula"><input maxLength={60} value={form.rqe} onChange={(e) => setForm({ ...form, rqe: e.target.value })} /></Field>
          <Field label="Especialidades" hint="Separadas por vírgula"><input maxLength={400} value={form.specialties} onChange={(e) => setForm({ ...form, specialties: e.target.value })} /></Field>
        </div>
        <button className="primary" disabled={act.busy}>Cadastrar médico</button>
      </form>
    </section>
  );
}

/** Imagem da assinatura manuscrita do próprio médico (TELELAUDO T5): só visual, aplicada apenas com autorização. */
export function MySignaturePanel() {
  const st = useLoad(async () => await get<{ has_image: boolean; use_signature_image: boolean; uploaded_at: string | null }>(
    "/report/physicians/me/signature").catch(() => null), []);
  const [file, setFile] = useState<File | undefined>();
  const act = useAction();
  if (!st.data) return null;
  async function send(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    await act.run(async () => { await upload("/report/physicians/me/signature", file); await st.reload(); },
      "Imagem enviada. Ela só aparece nos laudos se você autorizar.");
  }
  async function consent(allow: boolean) {
    await act.run(async () => { await post("/report/physicians/me/signature/consent", { allow }); await st.reload(); },
      allow ? "Uso autorizado nos próximos laudos que você liberar." : "Uso revogado para os próximos laudos.");
  }
  return (
    <section className="panel" aria-label="Minha assinatura">
      <h2>Minha assinatura (imagem)</h2>
      <p className="field-hint">Elemento apenas visual no PDF. Não substitui a liberação com a sua senha nem a assinatura digital. Só você envia, troca, autoriza ou revoga; ninguém baixa a imagem.</p>
      {act.view}
      <form className="filters" aria-label="Enviar imagem da assinatura" onSubmit={send}>
        <input type="file" accept="image/png,image/jpeg" aria-label="Imagem da assinatura" onChange={(e) => setFile(e.target.files?.[0])} />
        <button disabled={!file || act.busy}>Enviar imagem</button>
      </form>
      <p>{st.data.has_image ? `Imagem cadastrada em ${fmtDate(st.data.uploaded_at)}.` : "Nenhuma imagem cadastrada."}</p>
      {st.data.has_image && <label className="check"><input type="checkbox" checked={st.data.use_signature_image}
        onChange={(e) => void consent(e.target.checked)} /> Autorizo aplicar a imagem nos laudos que eu liberar</label>}
    </section>
  );
}
