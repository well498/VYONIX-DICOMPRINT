import { useState } from "react";
import { get, post } from "../api";
import { Notice, Page, useAction, useLoad } from "../ui";

// Atributo DICOM JSON (PS3.18 F.2): {"vr": "...", "Value": [...]}
type Attr = { vr: string; Value?: unknown[] };
type DicomJson = Record<string, Attr>;

type Quality = {
  study_uid: string; receiving: boolean; reconciled: boolean; possibly_incomplete: boolean;
  issues: { code: string; message: string }[];
  series: { series_uid: string; modality: string | null; series_number: number | null; instances: number;
            missing_numbers: number[]; repeated_numbers: number[] }[];
};
type Status = { engine: { configured: boolean; reachable?: boolean; name?: string; version?: string; message?: string };
                index: { studies: number; series: number; instances: number; bytes: number }; enabled: boolean };

function val(j: DicomJson, tag: string): string {
  const v = j[tag]?.Value?.[0];
  if (v == null) return "";
  if (typeof v === "object" && v !== null && "Alphabetic" in v) return String((v as { Alphabetic: string }).Alphabetic);
  return String(v);
}
function list(j: DicomJson, tag: string): string { return (j[tag]?.Value ?? []).map(String).join(", "); }
function dicomDate(d: string): string { return d.length === 8 ? `${d.slice(6, 8)}/${d.slice(4, 6)}/${d.slice(0, 4)}` : "—"; }
function personName(pn: string): string {
  const [family, given] = pn.split("^");
  return [given, family].filter(Boolean).join(" ") || pn;
}
function toDicom(iso: string): string { return iso.replaceAll("-", ""); }
function size(bytes: number): string {
  const units: [number, string][] = [[1024 ** 3, "GB"], [1024 ** 2, "MB"], [1024, "KB"]];
  for (const [n, u] of units) if (bytes >= n) return `${(bytes / n).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} ${u}`;
  return `${bytes} bytes`;
}

const ISSUE_LABEL: Record<string, string> = {
  instance_gap: "Lacuna na numeração", instance_repeated: "Numeração repetida", receiving: "Recebendo",
  no_order: "Sem pedido", no_accession: "Sem accession",
};

export function ImagesPage({ me }: { me: { permissions: string[] } }) {
  const isAdmin = me.permissions.includes("pacs.admin");
  const [form, setForm] = useState({ name: "", pid: "", from: "", to: "", modality: "", accession: "" });
  const [query, setQuery] = useState(form);
  const [openQ, setOpenQ] = useState<Record<string, Quality | "loading" | string>>({});
  const [onlyIssues, setOnlyIssues] = useState(false);

  const studies = useLoad(async () => {
    const q = new URLSearchParams({ limit: "100" });
    if (query.name) q.set("PatientName", query.name);
    if (query.pid) q.set("PatientID", query.pid);
    if (query.accession) q.set("AccessionNumber", query.accession);
    if (query.modality) q.set("ModalitiesInStudy", query.modality.toUpperCase());
    if (query.from || query.to) q.set("StudyDate", `${toDicom(query.from)}-${toDicom(query.to)}`);
    return (await get<DicomJson[] | null>(`/pacs/dicomweb/studies?${q}`)) ?? [];
  }, [query]);
  const issues = useLoad(async () => onlyIssues
    ? (await get<{ studies: { study_uid: string; issues: string[] }[] }>("/pacs/quality")).studies : [], [onlyIssues]);
  const status = useLoad(async () => isAdmin ? await get<Status>("/pacs/status") : null, [isAdmin]);
  const sync = useAction();

  const issueMap = new Map((issues.data ?? []).map((x) => [x.study_uid, x.issues]));
  const rows = (studies.data ?? []).filter((s) => !onlyIssues || issueMap.has(val(s, "0020000D")));

  async function toggleQuality(uid: string) {
    if (openQ[uid]) { const n = { ...openQ }; delete n[uid]; setOpenQ(n); return; }
    setOpenQ({ ...openQ, [uid]: "loading" });
    try {
      const q = await get<Quality>(`/pacs/studies/${encodeURIComponent(uid)}/quality`);
      setOpenQ((o) => ({ ...o, [uid]: q }));
    } catch (e) {
      setOpenQ((o) => ({ ...o, [uid]: e instanceof Error ? e.message : "Erro ao consultar a qualidade." }));
    }
  }

  return (
    <Page title="Imagens" intro="Estudos de imagem recebidos pelo VYONIX PACS. Abrir um estudo no Viewer é registrado na auditoria. Não liberado para uso clínico."
      actions={isAdmin && status.data?.enabled ? (
        <button disabled={sync.busy} onClick={() => sync.run(async () => {
          const r = await post<{ indexed: number; duplicates: number; rejected: number }>("/pacs/sync");
          await studies.reload(); await status.reload();
          sync.setMsg({ kind: "ok", text: `Sincronização: ${r.indexed} nova(s), ${r.duplicates} já indexada(s), ${r.rejected} recusada(s).` });
        })}>Sincronizar recebimentos</button>) : undefined}>
      {sync.view}
      {isAdmin && status.data && (
        <div className="card-row" role="group" aria-label="Estado do armazenamento">
          <div className="card">
            <span className="card-label">Motor DICOM</span>
            <strong>{!status.data.engine.configured ? "Não configurado"
              : status.data.engine.reachable ? [status.data.engine.name, status.data.engine.version].filter(Boolean).join(" ")
                : "Sem resposta"}</strong>
            {status.data.engine.message && <span className="field-hint">{status.data.engine.message}</span>}
          </div>
          <div className="card"><span className="card-label">Estudos</span><strong>{status.data.index.studies}</strong></div>
          <div className="card"><span className="card-label">Imagens</span><strong>{status.data.index.instances}</strong></div>
          <div className="card"><span className="card-label">Armazenado</span><strong>{size(status.data.index.bytes)}</strong></div>
          <div className="card"><span className="card-label">Módulo</span>
            <strong>{status.data.enabled ? "Habilitado" : "Desabilitado"}</strong></div>
        </div>
      )}
      <form className="filters filters-grid" role="search" aria-label="Pesquisar estudos" onSubmit={(e) => { e.preventDefault(); setQuery(form); }}>
        <input placeholder="Nome do paciente" aria-label="Nome do paciente" value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <input placeholder="ID do paciente" aria-label="ID do paciente" value={form.pid}
          onChange={(e) => setForm({ ...form, pid: e.target.value })} />
        <input type="date" aria-label="Data inicial" title="Data inicial" value={form.from} onChange={(e) => setForm({ ...form, from: e.target.value })} />
        <input type="date" aria-label="Data final" title="Data final" value={form.to} onChange={(e) => setForm({ ...form, to: e.target.value })} />
        <input placeholder="Modalidade (ex.: CT)" aria-label="Modalidade" value={form.modality} maxLength={16}
          onChange={(e) => setForm({ ...form, modality: e.target.value })} />
        <input placeholder="Accession" aria-label="Número de acesso" value={form.accession}
          onChange={(e) => setForm({ ...form, accession: e.target.value })} />
        <button>Pesquisar</button>
        <label className="check"><input type="checkbox" checked={onlyIssues}
          onChange={(e) => setOnlyIssues(e.target.checked)} /> Só com pendência de qualidade</label>
      </form>
      <Notice kind="error">{studies.error || issues.error}</Notice>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Data</th><th>Paciente</th><th>ID</th><th>Modalidades</th><th>Descrição</th>
            <th className="num">Séries</th><th className="num">Imagens</th><th>Accession</th><th>Ações</th></tr></thead>
          <tbody>
            {rows.map((s) => {
              const uid = val(s, "0020000D");
              const q = openQ[uid];
              const flags = issueMap.get(uid);
              return [
                <tr key={uid}>
                  <td>{dicomDate(val(s, "00080020"))}</td>
                  <td>{personName(val(s, "00100010")) || "—"}</td>
                  <td className="nowrap">{val(s, "00100020")}</td>
                  <td>{list(s, "00080061") || "—"}</td>
                  <td>{val(s, "00081030") || "—"}
                    {flags && <span className="tags">{flags.map((f) => <span key={f} className="tag tag-warn">{ISSUE_LABEL[f] ?? f}</span>)}</span>}
                  </td>
                  <td className="num">{val(s, "00201206")}</td>
                  <td className="num">{val(s, "00201208")}</td>
                  <td className="nowrap">{val(s, "00080050") || "—"}</td>
                  <td className="actions"><div className="row-actions">
                    <a className="button" href={`/viewer/viewer?StudyInstanceUIDs=${encodeURIComponent(uid)}`}
                      target="_blank" rel="noopener">Abrir no Viewer</a>
                    <button className="link" aria-expanded={!!q} onClick={() => void toggleQuality(uid)}>Qualidade</button>
                  </div></td>
                </tr>,
                q ? (
                  <tr key={`${uid}-q`} className="detail-row">
                    <td colSpan={9}>
                      {q === "loading" ? "Consultando…" : typeof q === "string" ? <Notice kind="error">{q}</Notice> : (
                        <div>
                          {q.issues.length === 0 ? <Notice kind="ok">Nenhuma pendência encontrada (indícios verificados: numeração, recepção, pedido e accession).</Notice>
                            : <ul>{q.issues.map((i, k) => <li key={k}>{i.message}</li>)}</ul>}
                          <p className="field-hint">“Possivelmente incompleto” é um indício: o DICOM não informa quantas imagens o estudo deveria ter.</p>
                          <table>
                            <thead><tr><th>Série</th><th>Modalidade</th><th className="num">Imagens</th><th>Faltando</th><th>Repetidas</th></tr></thead>
                            <tbody>{q.series.map((se) => (
                              <tr key={se.series_uid}><td>{se.series_number ?? "—"}</td><td>{se.modality ?? "—"}</td>
                                <td className="num">{se.instances}</td>
                                <td>{se.missing_numbers.join(", ") || "—"}</td><td>{se.repeated_numbers.join(", ") || "—"}</td></tr>
                            ))}</tbody>
                          </table>
                        </div>
                      )}
                    </td>
                  </tr>
                ) : null,
              ];
            })}
          </tbody>
        </table>
        {!studies.loading && rows.length === 0 && <p className="empty">Nenhum estudo com esses filtros.</p>}
      </div>
    </Page>
  );
}
