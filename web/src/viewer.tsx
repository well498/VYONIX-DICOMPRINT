import { useEffect, useRef, useState, type FormEvent } from "react";
import { del, errorText, fmtDate, get, post } from "./api";
import { Field, Notice, useAction, useLoad } from "./ui";

/** Lançador do VYONIX Viewer: o servidor escolhe o protocolo (explícito → pessoal → instituição → padrão) e só
 * oferece anteriores do mesmo paciente que o usuário pode ver. */
type Prior = { study_id: string; study_instance_uid: string; study_date: string | null; modality: string | null;
  description: string | null; accession: string | null; same_modality: boolean };
type Launch = { url: string; layout: string; layout_name: string; source: string; prior: Prior | null; priors: Prior[];
  note: string | null };

const SOURCE: Record<string, string> = { explicit: "escolhido agora", personal: "seu protocolo", institution: "protocolo da instituição",
  default: "padrão" };

function day(d: string | null) { return d ? fmtDate(d + "T12:00:00", false) : "sem data"; }

async function openVyonix(studyUid: string, params: Record<string, string> = {}): Promise<Launch> {
  const w = window.open("about:blank", "_blank");     // abre já (bloqueadores de pop-up) e navega depois
  try {
    const r = await get<Launch>(`/pacs/viewer/launch?${new URLSearchParams({ study_uid: studyUid, ...params })}`);
    if (w) { w.opener = null; w.location.href = r.url; } else window.location.href = r.url;
    return r;
  } catch (e) {
    w?.close();
    throw e;
  }
}

/** Botão "Abrir no Viewer" + "Comparar…" (lista de anteriores autorizados). */
export function ViewerButtons({ studyUid, label = "Abrir no Viewer", compact = false }: { studyUid: string; label?: string; compact?: boolean }) {
  const [pick, setPick] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const info = useLoad(async () => (pick ? await get<Launch>(`/pacs/viewer/launch?${new URLSearchParams({ study_uid: studyUid, preview: "true", layout: "compare" })}`) : null), [pick, studyUid]);
  async function go(params: Record<string, string> = {}) {
    setMsg(null);
    try {
      const r = await openVyonix(studyUid, params);
      setMsg(r.note ?? (r.prior ? `Comparando com ${r.prior.modality ?? ""} de ${day(r.prior.study_date)} (${SOURCE[r.source] ?? r.source}).`
        : `Aberto: ${r.layout_name} (${SOURCE[r.source] ?? r.source}).`));
    } catch (e) { setMsg(errorText(e)); }
  }
  return (
    <span className="viewer-buttons" role="group" aria-label="Viewer">
      <button type="button" className={compact ? "link" : undefined} onClick={() => void go()}>{label}</button>
      {" "}<button type="button" className="link" aria-expanded={pick} onClick={() => setPick(!pick)}>Comparar…</button>
      {pick && (
        <span className="viewer-pick">
          {info.loading && <span className="field-hint">Buscando exames anteriores…</span>}
          {info.error && <span className="field-hint">{info.error}</span>}
          {info.data && (info.data.priors.length === 0
            ? <span className="field-hint">Nenhum exame anterior com imagens disponível para você.</span>
            : <select aria-label="Exame anterior para comparar" defaultValue="" onChange={(e) => {
                if (e.target.value) { void go({ prior: e.target.value }); setPick(false); }
              }}>
                <option value="">Comparar com…</option>
                {info.data.priors.map((p) => <option key={p.study_instance_uid} value={p.study_instance_uid}>
                  {day(p.study_date)} · {p.modality ?? "—"} · {p.description ?? p.accession ?? "exame"}{p.same_modality ? " ★" : ""}</option>)}
              </select>)}
        </span>)}
      {msg && <span className="field-hint" role="status"> {msg}</span>}
    </span>
  );
}

type Protocol = { id: string; personal: boolean; modality: string | null; procedure_id: string | null; layout: string;
  layout_name: string; compare_prior: boolean; prior_same_modality: boolean };

/** Protocolos de exibição: os da instituição (com permissão) e os pessoais (se a instituição permitir). */
export function ViewerProtocolsPanel() {
  const list = useLoad(() => get<{ items: Protocol[]; layouts: Record<string, string>; allow_personal: boolean; access: string;
    can_manage: boolean }>("/pacs/viewer/protocols"), []);
  const procs = useLoad(async () => await get<{ id: string; name: string }[]>("/procedures").catch(() => []), []);
  const [form, setForm] = useState({ modality: "", procedure_id: "", layout: "compare", prior_same_modality: true, personal: true });
  const act = useAction();
  const d = list.data;
  async function save(e: FormEvent) {
    e.preventDefault();
    await act.run(async () => {
      await post("/pacs/viewer/protocols", { modality: form.modality || null, procedure_id: form.procedure_id || null,
        layout: form.layout, compare_prior: form.layout === "compare", prior_same_modality: form.prior_same_modality,
        personal: form.personal });
      await list.reload();
    }, "Protocolo salvo.");
  }
  const procName = (id: string | null) => (id ? procs.data?.find((p) => p.id === id)?.name ?? "procedimento" : null);
  const canPersonal = Boolean(d?.allow_personal);
  return (
    <section className="panel" aria-label="Protocolos do Viewer">
      <h2>Protocolos de exibição do Viewer</h2>
      <p className="field-hint">Definem como o Viewer abre cada exame: 1 quadro, grade de séries ou comparação lado a lado com o exame
        anterior do mesmo paciente. Vale o mais específico (procedimento &gt; modalidade &gt; geral); o seu protocolo pessoal vem antes
        do da instituição. A comparação nunca alinha anatomia automaticamente.</p>
      {d && <p className="field-hint">Acesso às imagens: {d.access === "linked" ? "médicos veem só estudos das unidades com vínculo" : "toda a organização"}.
        {!d.allow_personal && " Protocolos pessoais desativados pela instituição."}</p>}
      {act.view}
      <Notice kind="error">{list.error}</Notice>
      <ul className="history">{(d?.items ?? []).map((p) => (
        <li key={p.id}><strong>{p.layout_name}</strong> — {procName(p.procedure_id) ?? (p.modality ?? "todas as modalidades")}
          {p.layout === "compare" && (p.prior_same_modality ? " (anterior da mesma modalidade)" : " (anterior mais recente)")}
          <span className="tag">{p.personal ? "meu" : "instituição"}</span>
          {(p.personal || d?.can_manage) && <> <button type="button" className="link" onClick={() => void act.run(async () => {
            await del(`/pacs/viewer/protocols/${p.id}`); await list.reload(); }, "Protocolo removido.")}>Remover</button></>}</li>))}
      </ul>
      {(canPersonal || d?.can_manage) && (
        <form className="grid2" aria-label="Novo protocolo do Viewer" onSubmit={save}>
          {canPersonal && d?.can_manage && (
            <label className="check"><input type="checkbox" checked={!form.personal} onChange={(e) => setForm({ ...form, personal: !e.target.checked })} />
              {" "}Protocolo da instituição</label>)}
          <Field label="Modalidade do protocolo" hint="Vazio = todas"><input maxLength={16} value={form.modality}
            onChange={(e) => setForm({ ...form, modality: e.target.value.toUpperCase() })} /></Field>
          <Field label="Procedimento do protocolo" hint="Opcional; mais específico que a modalidade">
            <select value={form.procedure_id} onChange={(e) => setForm({ ...form, procedure_id: e.target.value })}>
              <option value="">Qualquer</option>{(procs.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
          <Field label="Layout ao abrir"><select value={form.layout} onChange={(e) => setForm({ ...form, layout: e.target.value })}>
            {Object.entries(d?.layouts ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
          {form.layout === "compare" && <label className="check"><input type="checkbox" checked={form.prior_same_modality}
            onChange={(e) => setForm({ ...form, prior_same_modality: e.target.checked })} /> Comparar com anterior da mesma modalidade</label>}
          <div className="form-actions"><button className="primary" disabled={act.busy}>Salvar protocolo</button></div>
        </form>)}
    </section>
  );
}

type Avail = Record<"vyonix" | "weasis" | "oviyam", { available: boolean; label: string; reason: string | null }>;
let availCache: Promise<Avail> | null = null;
function availability(): Promise<Avail> {
  if (!availCache) {
    availCache = get<Avail>("/pacs/external/viewers").catch((e) => { availCache = null; throw e; });
    setTimeout(() => { availCache = null; }, 60000);      // configuração alterada pelo administrador vale em 1 min
  }
  return availCache;
}

/** Menu único "Abrir imagens" (mesma experiência em toda a plataforma): VYONIX Viewer no navegador, comparação
 * com anterior, Weasis (aplicativo local) e Oviyam (serviço web). O servidor confere permissão, organização e
 * vínculo em cada abertura; aqui só se mostra o que está disponível e por quê. */
export function OpenImages({ studyUid, compact = false }: { studyUid: string; compact?: boolean }) {
  const [open, setOpenState] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const btn = useRef<HTMLButtonElement>(null);
  function setOpen(v: boolean) {                         // menu fixo na tela: não é cortado por tabelas com rolagem
    if (v && btn.current) {
      const r = btn.current.getBoundingClientRect();
      const width = Math.min(416, window.innerWidth - 16);
      setPos({ top: r.bottom + 4, left: Math.max(8, Math.min(r.left, window.innerWidth - width - 8)) });
    }
    setOpenState(v);
  }
  useEffect(() => {
    if (!open) return undefined;
    const follow = () => setOpen(true);                  // acompanha o botão ao rolar ou redimensionar
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpenState(false); };
    window.addEventListener("resize", follow);
    window.addEventListener("scroll", follow, true);
    window.addEventListener("keydown", esc);
    return () => { window.removeEventListener("resize", follow); window.removeEventListener("scroll", follow, true);
      window.removeEventListener("keydown", esc); };
  }, [open]);
  const [msg, setMsg] = useState<{ text: string; weasis?: string; help?: string[] } | null>(null);
  const av = useLoad(async () => (open ? await availability() : null), [open]);
  async function vyonix(params: Record<string, string> = {}) {
    setMsg(null);
    try {
      const r = await openVyonix(studyUid, params);
      setMsg({ text: r.note ?? (r.prior ? `VYONIX Viewer: comparando com ${r.prior.modality ?? ""} de ${day(r.prior.study_date)}.`
        : `VYONIX Viewer: ${r.layout_name} (${SOURCE[r.source] ?? r.source}).`) });
    } catch (e) { setMsg({ text: errorText(e) }); }
    setOpen(false);
  }
  async function external(viewer: "weasis" | "oviyam") {
    setMsg(null);
    const w = viewer === "oviyam" ? window.open("about:blank", "_blank") : null;
    try {
      const r = await post<{ uri?: string; url?: string; help: string[] }>(`/pacs/external/${viewer}/launch?${new URLSearchParams({ study_uid: studyUid })}`, {});
      if (viewer === "weasis" && r.uri) {
        window.location.href = r.uri;                       // o sistema entrega o link weasis:// ao aplicativo
        setMsg({ text: "Abrindo no Weasis…", weasis: r.uri, help: r.help });
      } else if (r.url) {
        if (w) { w.opener = null; w.location.href = r.url; } else window.open(r.url, "_blank", "noopener");
        setMsg({ text: "Oviyam aberto em nova aba.", help: r.help });
      }
    } catch (e) { w?.close(); setMsg({ text: errorText(e) }); }
    setOpen(false);
  }
  const item = (key: "weasis" | "oviyam", title: string, sub: string) => {
    const a = av.data?.[key];
    return (
      <li key={key}><button type="button" role="menuitem" disabled={!a?.available} onClick={() => void external(key)}>
        <strong>{title}</strong> <span className="sub">— {sub}</span>
        {a && !a.available && <span className="field-hint"> Indisponível: {a.reason}</span>}</button></li>);
  };
  return (
    <span className="open-images">
      <button ref={btn} type="button" className={compact ? "link" : undefined} aria-haspopup="menu" aria-expanded={open}
        onClick={() => setOpen(!open)}>Abrir imagens ▾</button>
      {open && (
        <ul className="open-images-menu" role="menu" aria-label="Abrir imagens" style={pos ?? undefined}>
          <li><button type="button" role="menuitem" onClick={() => void vyonix()}>
            <strong>VYONIX Viewer</strong> <span className="sub">— no navegador</span></button></li>
          <li><ComparePick studyUid={studyUid} onPick={(uid) => void vyonix({ prior: uid })} /></li>
          {av.loading && <li className="field-hint">Verificando visualizadores…</li>}
          {av.error && <li className="field-hint">{av.error}</li>}
          {av.data && item("weasis", "Abrir com Weasis", "visualização avançada (aplicativo instalado)")}
          {av.data && item("oviyam", "Abrir com Oviyam", "visualização pelo navegador")}
        </ul>)}
      {msg && <span className="field-hint" role="status"> {msg.text}
        {msg.weasis && <> <a href={msg.weasis}>Se o Weasis não abrir, clique aqui</a>.</>}
        {msg.help && <span className="open-images-help">{msg.help.join(" ")}</span>}</span>}
    </span>
  );
}

function ComparePick({ studyUid, onPick }: { studyUid: string; onPick: (uid: string) => void }) {
  const info = useLoad(async () => await get<Launch>(`/pacs/viewer/launch?${new URLSearchParams({ study_uid: studyUid, preview: "true", layout: "compare" })}`)
    .catch(() => null), [studyUid]);
  const priors = info.data?.priors ?? [];
  if (info.loading) return <span className="field-hint">Buscando exames anteriores…</span>;
  if (priors.length === 0) return <span className="field-hint">Comparar: nenhum exame anterior com imagens disponível para você.</span>;
  return (
    <select aria-label="Comparar com exame anterior" defaultValue="" onChange={(e) => { if (e.target.value) onPick(e.target.value); }}>
      <option value="">VYONIX Viewer — comparar com anterior…</option>
      {priors.map((p) => <option key={p.study_instance_uid} value={p.study_instance_uid}>
        {day(p.study_date)} · {p.modality ?? "—"} · {p.description ?? p.accession ?? "exame"}{p.same_modality ? " ★" : ""}</option>)}
    </select>);
}
