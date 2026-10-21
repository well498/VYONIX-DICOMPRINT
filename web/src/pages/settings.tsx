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
      {list.data?.map((d) => <SettingForm key={`${d.module}.${d.key}`} d={d} manage={manage} onSaved={list.reload} />)}
    </Page>
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
