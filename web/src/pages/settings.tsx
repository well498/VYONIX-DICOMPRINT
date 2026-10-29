import { useState, type FormEvent } from "react";
import { fmtDate, get, put, type Me } from "../api";
import { Field, Notice, Page, useAction, useLoad } from "../ui";

type Prop = { type?: string; title?: string; description?: string; minimum?: number; maximum?: number;
  maxLength?: number; pattern?: string };
type Desc = { module: string; key: string; description: string; scope: string; row_version: number;
  value: Record<string, unknown>; schema: { properties: Record<string, Prop> } };
type Hist = { at: string; actor: string; reason: string | null; old: Record<string, unknown> | null;
  new: Record<string, unknown> };

const MODULE_NAME: Record<string, string> = { core: "Plataforma", clinical: "Cadastro clínico" };

export function SettingsPage({ me }: { me: Me }) {
  const manage = me.permissions.includes("core.settings.manage");
  const list = useLoad(() => get<Desc[]>("/settings"));
  return (
    <Page title="Configurações" intro="Cada alteração fica no histórico com o valor anterior, quem alterou e o motivo.">
      <Notice kind="error">{list.error}</Notice>
      {list.data && <WorkflowOverview list={list.data} />}
      {list.data?.map((d) => <SettingForm key={`${d.module}.${d.key}`} d={d} manage={manage} onSaved={list.reload} />)}
    </Page>
  );
}

function WorkflowOverview({ list }: { list: Desc[] }) {
  const v = (m: string, k: string) => list.find((d) => d.module === m && d.key === k)?.value;
  const wf = v("ris", "workflow") as { scheduling?: boolean; worklist?: boolean } | undefined;
  const prep = v("ris", "preparation") as { require_forward?: boolean } | undefined;
  const dist = v("report", "distribution") as { mode?: string } | undefined;
  const DIST: Record<string, string> = { manual: "manual (coordenação atribui)", fixed: "médico fixo", balanced: "equilibrada" };
  const stages: [string, string, "always" | "on" | "off" | "na"][] = [
    ["Cadastro do paciente", "Sempre usado", "always"],
    ["Solicitação e agendamento", wf ? (wf.scheduling ? "Ligado" : "Desligado") : "Módulo RIS não habilitado", wf ? (wf.scheduling ? "on" : "off") : "na"],
    ["Worklist (modalidades)", wf ? (wf.worklist ? "Ligada" : "Desligada") : "Módulo RIS não habilitado", wf ? (wf.worklist ? "on" : "off") : "na"],
    ["Aquisição e recepção no PACS", "Sempre usado (com o PACS habilitado)", "always"],
    ["Viewer", "Sempre disponível com o PACS", "always"],
    ["Preparação pelo técnico", prep ? (prep.require_forward ? "Obrigatória antes do laudo" : "Opcional (o médico vê o exame ao chegar)") : "Módulo RIS não habilitado", prep ? (prep.require_forward ? "on" : "off") : "na"],
    ["Distribuição aos médicos", dist ? `Modo ${DIST[dist.mode ?? "manual"] ?? dist.mode}` : "Módulo de laudos não habilitado", dist ? "on" : "na"],
    ["Laudo e liberação com senha", "Sempre usado (não é assinatura digital ICP-Brasil)", "always"],
    ["Entrega ao paciente", "Ainda não disponível (portal do paciente planejado)", "na"],
  ];
  return (
    <section className="panel" aria-label="Fluxo do exame">
      <h2 className="h3">Fluxo do exame</h2>
      <p className="intro">Etapas usadas pela instituição. Ajuste nas configurações abaixo: <em>Etapas do fluxo do exame</em>, <em>Preparação técnica dos estudos</em> e <em>Distribuição dos exames aos médicos</em>.</p>
      <ol className="flow">{stages.map(([n, t, k]) => (
        <li key={n} className={`flow-${k}`}><strong>{n}</strong><span>{t}</span></li>))}</ol>
    </section>
  );
}

function SettingForm({ d, manage, onSaved }: { d: Desc; manage: boolean; onSaved: () => void }) {
  const [v, setV] = useState<Record<string, unknown>>(d.value);
  const [reason, setReason] = useState("");
  const [hist, setHist] = useState<Hist[] | null>(null);
  const act = useAction();
  const dirty = JSON.stringify(v) !== JSON.stringify(d.value);
  async function save(e: FormEvent) {
    e.preventDefault();
    if (await act.run(() => put(`/settings/${d.module}/${d.key}`, { value: v, reason: reason || null,
      row_version: d.row_version }), "Configuração salva.")) { setReason(""); onSaved(); }
  }
  return (
    <form className="panel" onSubmit={save} aria-label={d.description}>
      <h2>{d.description} <span className="sub">{MODULE_NAME[d.module] ?? d.module}</span></h2>
      <div className="grid2">
        {Object.entries(d.schema.properties).map(([k, p]) => {
          const label = p.description ?? p.title ?? k;
          if (p.type === "boolean") {
            return <label key={k} className="check"><input type="checkbox" disabled={!manage} checked={Boolean(v[k])}
              onChange={(e) => setV({ ...v, [k]: e.target.checked })} /> {label}</label>;
          }
          return (
            <Field key={k} label={label} hint={p.minimum !== undefined ? `De ${p.minimum} a ${p.maximum}` : undefined}>
              <input disabled={!manage} type={p.type === "integer" ? "number" : "text"} min={p.minimum} max={p.maximum}
                maxLength={p.maxLength} value={String(v[k] ?? "")}
                onChange={(e) => setV({ ...v, [k]: p.type === "integer" ? Number(e.target.value) : e.target.value })} />
            </Field>
          );
        })}
      </div>
      {manage && dirty && (
        <Field label="Motivo da alteração"><input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} /></Field>
      )}
      {act.view}
      <div className="form-actions">
        {manage && <button className="primary" disabled={!dirty || act.busy}>Salvar</button>}
        <button type="button" onClick={async () => setHist(hist ? null : await get<Hist[]>(`/settings/${d.module}/${d.key}/history`))}>
          {hist ? "Ocultar histórico" : "Histórico"}</button>
      </div>
      {hist && (hist.length === 0 ? <p className="empty">Sem alterações registradas.</p> : (
        <ul className="history">{hist.map((h, i) => (
          <li key={i}>{fmtDate(h.at)} — {h.actor}{h.reason ? ` (${h.reason})` : ""}: {Object.keys(h.new)
            .filter((k) => JSON.stringify(h.old?.[k]) !== JSON.stringify(h.new[k]))
            .map((k) => `${k} ${JSON.stringify(h.old?.[k] ?? null)} → ${JSON.stringify(h.new[k])}`).join("; ")}</li>
        ))}</ul>
      ))}
    </form>
  );
}
