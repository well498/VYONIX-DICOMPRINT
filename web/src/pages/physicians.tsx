import { useEffect, useMemo, useState, type FormEvent } from "react";
import { blob, del, errorText, fmtDate, get, post, put, upload, type Me } from "../api";
import { Field, Notice, useAction, useLoad } from "../ui";

type Link = { id: string; site_id: string | null; valid_from: string; valid_to: string | null };
type Physician = { id: string; user_id: string; full_name: string; crm: string; crm_uf: string; rqe: string | null;
  specialties: string[]; identification: string; active: boolean; links: Link[]; requires_review?: boolean;
  footer?: string | null };
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
  const [sigFor, setSigFor] = useState<string | null>(null);
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
  async function toggleReview(p: Physician) {
    await act.run(async () => {
      await put(`/report/physicians/${p.id}`, { user_id: p.user_id, full_name: p.full_name, crm: p.crm, crm_uf: p.crm_uf,
        rqe: p.rqe, specialties: p.specialties, footer: p.footer ?? null, active: p.active, requires_review: !p.requires_review });
      await list.reload();
    }, p.requires_review ? "Os laudos deste médico voltam a ser liberados por ele." : "Os laudos deste médico passam por revisão antes da liberação.");
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
            {p.requires_review && <span className="tag">laudos com revisão obrigatória</span>}
            {" "}<label className="check"><input type="checkbox" checked={Boolean(p.requires_review)} disabled={act.busy}
              onChange={() => void toggleReview(p)} /> Exige revisão (segunda leitura)</label>
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
            {" "}<button className="link" onClick={() => setSigFor(sigFor === p.id ? null : p.id)}>Enviar assinatura (administrador designado)</button>
            {sigFor === p.id && <div className="panel-inset">
              <p className="field-hint">Só funciona se {p.full_name} designou você no próprio cadastro. A imagem fica pendente até o médico confirmar com a senha dele; você não pode usá-la.</p>
              <SignatureEditor base={`/report/physicians/${p.id}/signature`} label={`Assinatura de ${p.full_name}`} onSent={() => setSigFor(null)} />
            </div>}
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

type SigStatus = {
  has_image: boolean; use_signature_image: boolean; uploaded_at: string | null;
  pending: { uploaded_by: string; uploaded_at: string } | null; delegate_user_id: string | null;
  history: { status: string; uploaded_by: string; uploaded_at: string; confirmed_at: string | null; ended_at: string | null; sha256: string }[];
};

const STATUS: Record<string, string> = { active: "ativa", pending: "aguardando sua confirmação", replaced: "substituída",
  deleted: "excluída", rejected: "descartada (nova imagem enviada antes da confirmação)" };

function useObjectUrl() {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);
  return [url, (b: Blob | null) => setUrl(b ? URL.createObjectURL(b) : null)] as const;
}

/** Carregar, tratar (recorte, brilho, contraste, fundo branco) e pré-visualizar antes de enviar. */
export function SignatureEditor({ base, onSent, label }: { base: string; onSent: () => Promise<void> | void; label: string }) {
  const [file, setFile] = useState<File | undefined>();
  const [p, setP] = useState({ l: 0, t: 0, r: 100, b: 100, bright: 100, contrast: 100, bg: true });
  const [url, setUrl] = useObjectUrl();
  const [err, setErr] = useState("");
  const act = useAction();
  const query = useMemo(() => {
    const q = new URLSearchParams({ brightness: String(p.bright / 100), contrast: String(p.contrast / 100),
      remove_background: String(p.bg) });
    if (p.l > 0 || p.t > 0 || p.r < 100 || p.b < 100) q.set("crop", [p.l, p.t, p.r, p.b].map((x) => x / 100).join(","));
    return q.toString();
  }, [p]);
  useEffect(() => {
    if (!file) { setUrl(null); return; }
    const h = setTimeout(() => {
      blob("POST", `${base}/preview?${query}`, file).then((b) => { setUrl(b); setErr(""); })
        .catch((e) => { setUrl(null); setErr(errorText(e)); });
    }, 300);
    return () => clearTimeout(h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file, query, base]);
  const slider = (k: keyof typeof p, name: string, min: number, max: number) => (
    <label className="field slider"><span className="field-label">{name}: {String(p[k])}%</span>
      <input type="range" min={min} max={max} value={Number(p[k])} aria-label={name}
        onChange={(e) => setP({ ...p, [k]: Number(e.target.value) })} /></label>);
  async function send(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    const ok = await act.run(async () => { await upload(`${base}?${query}`, file); }, "Imagem enviada: aguarda a confirmação do médico com a senha.");
    if (ok) { setFile(undefined); await onSent(); }
  }
  return (
    <form className="sig-editor" aria-label={label} onSubmit={send}>
      {act.view}
      <Field label="Carregar imagem da assinatura" hint="Foto ou digitalização em JPG, JPEG, PNG ou WEBP, até 5 MB. Use papel branco e boa luz.">
        <input type="file" accept="image/png,image/jpeg,image/webp,.jpg,.jpeg,.png,.webp" aria-label="Arquivo da assinatura"
          onChange={(e) => setFile(e.target.files?.[0])} /></Field>
      {file && <>
        <div className="sig-preview" aria-live="polite">
          {url ? <img src={url} alt="Pré-visualização da assinatura tratada" /> : <span>{err || "Gerando a pré-visualização…"}</span>}
        </div>
        <div className="grid2">
          {slider("l", "Recorte à esquerda", 0, 45)}{slider("r", "Recorte à direita", 55, 100)}
          {slider("t", "Recorte no topo", 0, 45)}{slider("b", "Recorte na base", 55, 100)}
          {slider("bright", "Brilho", 30, 300)}{slider("contrast", "Contraste", 30, 300)}
        </div>
        <label className="check"><input type="checkbox" checked={p.bg} onChange={(e) => setP({ ...p, bg: e.target.checked })} /> Remover o fundo branco</label>
        <button className="primary" disabled={!url || act.busy}>Enviar para confirmação</button>
      </>}
    </form>
  );
}

/** Assinatura manuscrita do próprio médico: só visual; ativa após a confirmação dele e aplicada só com autorização. */
export function MySignaturePanel() {
  const base = "/report/physicians/me/signature";
  const st = useLoad(async () => await get<SigStatus>(base).catch(() => null), []);
  const delegates = useLoad(async () => (await get<{ items: User[] }>(`${base}/delegates`).catch(() => ({ items: [] as User[] }))).items, []);
  const [active, setActive] = useObjectUrl();
  const [pending, setPending] = useObjectUrl();
  const [pw, setPw] = useState("");
  const act = useAction();
  const s = st.data;
  useEffect(() => {
    if (s?.has_image) blob("GET", `${base}/image`).then(setActive).catch(() => setActive(null)); else setActive(null);
    if (s?.pending) blob("GET", `${base}/image?which=pending`).then(setPending).catch(() => setPending(null)); else setPending(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s?.uploaded_at, s?.pending?.uploaded_at, s?.has_image]);
  if (!s) return null;
  async function confirm(e: FormEvent) {
    e.preventDefault();
    const ok = await act.run(async () => { await post(`${base}/confirm`, { password: pw }); await st.reload(); },
      "Imagem confirmada e ativa. Ela só entra nos laudos se o uso estiver autorizado.");
    if (ok) setPw("");
  }
  async function consent(allow: boolean) {
    await act.run(async () => { await post(`${base}/consent`, { allow }); await st.reload(); },
      allow ? "Uso autorizado nos próximos laudos que você liberar." : "Uso revogado para os próximos laudos.");
  }
  async function remove() {
    await act.run(async () => { await del(base); await st.reload(); }, "Imagem excluída e uso revogado. Laudos já liberados não mudam.");
  }
  async function delegate(id: string) {
    await act.run(async () => { await put(`${base}/delegate`, { user_id: id || null }); await st.reload(); },
      id ? "Administrador designado: ele pode enviar uma imagem, que só vale após a sua confirmação." : "Designação removida.");
  }
  return (
    <section className="panel" aria-label="Minha assinatura">
      <h2>Assinatura manuscrita</h2>
      <ul className="sig-modes">
        <li><strong>Confirmação por senha</strong> — é o que libera o laudo no VYONIX.</li>
        <li><strong>Imagem da assinatura manuscrita</strong> — apenas visual no PDF, inserida só nos laudos que você liberar e com o uso autorizado.</li>
        <li><strong>Assinatura digital ICP-Brasil (PAdES)</strong> — ainda não disponível. A imagem não é assinatura digital.</li>
      </ul>
      {act.view}
      <div className="grid2">
        <div>
          <h3>Imagem ativa</h3>
          {s.has_image && active ? <div className="sig-preview"><img src={active} alt="Sua assinatura ativa" /></div>
            : <p>Nenhuma imagem ativa.</p>}
          {s.has_image && <p className="field-hint">Ativa desde {fmtDate(s.uploaded_at)}.</p>}
          {s.has_image && <label className="check"><input type="checkbox" checked={s.use_signature_image}
            onChange={(e) => void consent(e.target.checked)} /> Autorizo aplicar a imagem nos laudos que eu liberar</label>}
          {(s.has_image || s.pending) && <button className="link danger" onClick={() => void remove()}>Excluir imagem</button>}
        </div>
        <div>
          {s.pending ? <>
            <h3>Aguardando sua confirmação</h3>
            {pending && <div className="sig-preview"><img src={pending} alt="Assinatura pendente de confirmação" /></div>}
            <p className="field-hint">Enviada por {s.pending.uploaded_by} em {fmtDate(s.pending.uploaded_at)}. Confira antes de confirmar: ela substituirá a ativa.</p>
            <form className="filters" aria-label="Confirmar assinatura" onSubmit={confirm}>
              <input type="password" required autoComplete="current-password" aria-label="Sua senha" placeholder="Sua senha" value={pw} onChange={(e) => setPw(e.target.value)} />
              <button className="primary" disabled={act.busy || !pw}>Confirmar que é a minha assinatura</button>
            </form>
          </> : <h3>{s.has_image ? "Substituir imagem" : "Cadastrar imagem"}</h3>}
          <SignatureEditor base={base} label="Enviar imagem da assinatura" onSent={st.reload} />
        </div>
      </div>
      <Field label="Administrador autorizado a enviar por mim" hint="Opcional. O envio dele fica pendente até você confirmar; ele não usa a sua assinatura.">
        <select value={s.delegate_user_id ?? ""} onChange={(e) => void delegate(e.target.value)}>
          <option value="">Ninguém (só eu)</option>
          {(delegates.data ?? []).map((u) => <option key={u.id} value={u.id}>{u.display_name} ({u.username})</option>)}
        </select></Field>
      {s.history.length > 0 && <details><summary>Histórico ({s.history.length})</summary>
        <ul className="history">{s.history.map((h, i) => (
          <li key={i}>{fmtDate(h.uploaded_at)} — enviada por {h.uploaded_by} — {STATUS[h.status] ?? h.status}
            {h.confirmed_at ? `, confirmada em ${fmtDate(h.confirmed_at)}` : ""}{h.ended_at ? `, encerrada em ${fmtDate(h.ended_at)}` : ""} · {h.sha256}</li>))}
        </ul></details>}
    </section>
  );
}
