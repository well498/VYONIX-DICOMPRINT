import { useMemo, useState } from "react";
import { ApiError, blob, get, type Me } from "../api";
import { Field, Notice, Page, useAction, useLoad } from "../ui";

type Pair = [string, number];
type Prod = {
  physician: { id: string; name: string; crm: string };
  period: { from: string; to: string };
  finalized: number; addenda: number; pending: { assigned: number; drafts: number };
  turnaround_hours: { mean: number | null; median: number | null };
  by_day: Pair[]; by_month: Pair[]; by_site: Pair[]; by_modality: Pair[];
  financial: boolean; can_see_all: boolean;
  values?: { configured: boolean; total_cents: number; by_modality: Pair[]; missing: string[] };
};
type Phys = { id: string; name: string; crm: string; active: boolean };

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const money = (c: number) => (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const hours = (h: number | null) => h === null ? "—" : h < 1 ? "menos de 1 h" : h < 48 ? `${h.toLocaleString("pt-BR")} h` : `${(h / 24).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} dias`;
const br = (s: string) => s.split("-").reverse().join("/");

function presets() {
  const t = new Date();
  const m0 = new Date(t.getFullYear(), t.getMonth(), 1);
  const p0 = new Date(t.getFullYear(), t.getMonth() - 1, 1);
  const p1 = new Date(t.getFullYear(), t.getMonth(), 0);
  return { hoje: [iso(t), iso(t)], mes: [iso(m0), iso(t)], anterior: [iso(p0), iso(p1)] } as Record<string, [string, string]>;
}

function Bars({ title, rows, label }: { title: string; rows: Pair[]; label: (k: string) => string }) {
  const max = Math.max(1, ...rows.map(([, v]) => v));
  if (!rows.length) return null;
  return (
    <section className="panel prod-block" aria-label={title}>
      <h2 className="h3">{title}</h2>
      <ul className="bars">{rows.map(([k, v]) => (
        <li key={k}><span className="bar-label">{label(k)}</span>
          <span className="bar-track"><span className="bar-fill" style={{ width: `${(v / max) * 100}%` }} /></span>
          <strong className="bar-value">{v}</strong></li>))}
      </ul>
    </section>
  );
}

export function ProductionPage({ me }: { me: Me }) {
  const canAll = me.permissions.includes("report.production.all");
  const canOwn = me.permissions.includes("report.production.own");
  const ps = useMemo(presets, []);
  const [period, setPeriod] = useState<[string, string]>(ps.mes);
  const [preset, setPreset] = useState("mes");
  const [who, setWho] = useState<string>("");
  const physicians = useLoad(() => canAll ? get<{ items: Phys[] }>("/report/production/physicians") : Promise.resolve({ items: [] }), [canAll]);
  const qs = `date_from=${period[0]}&date_to=${period[1]}${who ? `&physician_id=${who}` : ""}`;
  const data = useLoad(async () => {
    if (!who && !canOwn) return null;
    try { return await get<Prod>(`/report/production?${qs}`); }
    catch (e) { if (e instanceof ApiError && e.status === 404 && canAll) return null; throw e; }
  }, [qs]);
  const act = useAction();
  const d = data.data;

  async function exportAs(fmt: "csv" | "pdf") {
    await act.run(async () => {
      const b = await blob("GET", `/report/production?${qs}&format=${fmt}`);
      const url = URL.createObjectURL(b);
      const a = document.createElement("a");
      a.href = url; a.download = `producao-${period[0]}-a-${period[1]}.${fmt}`; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
  }

  return (
    <Page title={who ? "Produção médica" : "Minha produção"}
      intro="Laudos liberados no período, pendências e tempo de conclusão. Sem dados de pacientes."
      actions={d ? <><button onClick={() => void exportAs("csv")} disabled={act.busy}>Exportar Excel (CSV)</button>
        <button onClick={() => void exportAs("pdf")} disabled={act.busy}>Relatório PDF</button></> : undefined}>
      {act.view}
      <form className="panel filters filters-grid" aria-label="Período da produção" onSubmit={(e) => e.preventDefault()}>
        <>
          <Field label="Período">
            <select value={preset} onChange={(e) => { setPreset(e.target.value); if (ps[e.target.value]) setPeriod(ps[e.target.value]); }}>
              <option value="hoje">Hoje</option><option value="mes">Este mês</option>
              <option value="anterior">Mês anterior</option><option value="custom">Personalizado</option>
            </select></Field>
          <Field label="De"><input type="date" value={period[0]} onChange={(e) => { setPreset("custom"); setPeriod([e.target.value, period[1]]); }} /></Field>
          <Field label="Até"><input type="date" value={period[1]} onChange={(e) => { setPreset("custom"); setPeriod([period[0], e.target.value]); }} /></Field>
          {canAll && (
            <Field label="Médico">
              <select value={who} onChange={(e) => setWho(e.target.value)}>
                <option value="">{canOwn ? "Minha produção" : "Selecione o médico"}</option>
                {(physicians.data?.items ?? []).map((p) => <option key={p.id} value={p.id}>{p.name} — CRM {p.crm}</option>)}
              </select></Field>)}
        </>
      </form>
      <Notice kind="error">{data.error}</Notice>
      {!d && !data.loading && !data.error && <p className="empty">{canAll ? "Selecione um médico para ver a produção." : "Sem cadastro médico nesta instituição."}</p>}
      {d && (
        <>
          <p className="intro">{d.physician.name} — CRM {d.physician.crm} · {br(d.period.from)} a {br(d.period.to)}</p>
          <div className="card-row" role="group" aria-label="Resumo da produção">
            <div className="card"><span className="card-label">Laudos liberados</span><strong>{d.finalized}</strong></div>
            <div className="card"><span className="card-label">Adendos</span><strong>{d.addenda}</strong></div>
            <div className={`card${d.pending.assigned ? " card-warn" : ""}`}><span className="card-label">Pendentes na fila</span><strong>{d.pending.assigned}</strong></div>
            <div className="card"><span className="card-label">Rascunhos</span><strong>{d.pending.drafts}</strong></div>
            <div className="card"><span className="card-label">Tempo médio de conclusão</span><strong>{hours(d.turnaround_hours.mean)}</strong></div>
            {d.financial && d.values && <div className="card"><span className="card-label">Valor no período</span>
              <strong>{d.values.configured ? money(d.values.total_cents) : "Tabela não configurada"}</strong></div>}
          </div>
          {d.financial && d.values?.configured && d.values.missing.length > 0 &&
            <Notice kind="warn">Sem valor configurado para: {d.values.missing.join(", ")} (Configurações → produção médica).</Notice>}
          {d.finalized === 0 ? <p className="empty">Nenhum laudo liberado no período.</p> : (
            <div className="prod-grid">
              <Bars title="Por modalidade" rows={d.by_modality} label={(k) => k} />
              <Bars title="Por unidade" rows={d.by_site} label={(k) => k} />
              <Bars title="Por mês" rows={d.by_month} label={(k) => br(k)} />
              <Bars title="Por dia" rows={d.by_day} label={(k) => br(k)} />
            </div>)}
        </>
      )}
    </Page>
  );
}
