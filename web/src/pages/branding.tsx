import { useEffect, useState, type FormEvent } from "react";
import { fmtDate, get, post, upload } from "../api";
import { Field, Notice, useAction, useLoad } from "../ui";

type Settings = { margin_top_mm: number; margin_bottom_mm: number; margin_left_mm: number; margin_right_mm: number;
  font: "Sans" | "Serif"; font_size: number; accent_color: string; header_text: string; footer_text: string;
  page_numbers: boolean; logo_height_mm: number };
type Scope = { site_id: string | null; name: string; versions: number;
  current: null | { version: number; settings: Partial<Settings>; logo: boolean; letterhead: boolean; created_by: string; created_at: string } };

/** Identidade visual dos laudos por organização e por unidade (TELELAUDO T2). Cada gravação cria uma versão. */
export function BrandingPanel() {
  const data = useLoad(async () => await get<{ scopes: Scope[]; defaults: Settings }>("/report/branding"), []);
  const [scope, setScope] = useState<string>("");
  const [cfg, setCfg] = useState<Partial<Settings>>({});
  const [files, setFiles] = useState<{ logo?: File; letterhead?: File }>({});
  const act = useAction();
  const current = data.data?.scopes.find((x) => (x.site_id ?? "") === scope);
  // recarrega o formulário só ao trocar de escopo ou quando a versão do escopo muda (não apaga o que está sendo digitado)
  useEffect(() => { setCfg(current?.current?.settings ?? {}); setFiles({}); }, [scope, current?.current?.version]);  // eslint-disable-line
  const defaults = data.data?.defaults;
  const val = <K extends keyof Settings>(k: K): Settings[K] | "" => (cfg[k] ?? "") as Settings[K] | "";
  const set = (k: keyof Settings, v: unknown) => setCfg({ ...cfg, [k]: v === "" ? undefined : v });

  async function submit(e: FormEvent) {
    e.preventDefault();
    await act.run(async () => {
      const ids: { logo_asset_id?: string; letterhead_asset_id?: string } = {};
      if (files.logo) ids.logo_asset_id = (await upload<{ id: string }>("/report/branding/assets?kind=logo", files.logo)).id;
      if (files.letterhead) ids.letterhead_asset_id = (await upload<{ id: string }>("/report/branding/assets?kind=letterhead", files.letterhead)).id;
      await post("/report/branding", { site_id: scope || null, settings: cfg, ...ids, keep_images: true });
      await data.reload();
    }, "Identidade salva como nova versão. Laudos já liberados continuam com a versão da liberação.");
  }

  const num = (k: keyof Settings, label: string, min: number, max: number, step = 1) => (
    <Field label={label} hint={defaults ? `Vazio = herdado (${defaults[k]})` : undefined}>
      <input type="number" min={min} max={max} step={step} value={val(k) as number | ""}
        onChange={(e) => set(k, e.target.value === "" ? "" : Number(e.target.value))} /></Field>);

  return (
    <section className="panel" aria-label="Identidade visual dos laudos">
      <h2>Identidade visual dos laudos</h2>
      <p className="field-hint">A unidade herda da organização tudo o que não definir. Imagens: PNG ou JPEG até 2 MB (papel timbrado em proporção A4).</p>
      {act.view}
      <Notice kind="error">{data.error}</Notice>
      <form onSubmit={submit} aria-label="Editar identidade visual">
        <div className="grid2">
          <Field label="Aplicar a">
            <select value={scope} onChange={(e) => setScope(e.target.value)}>
              {(data.data?.scopes ?? []).map((x) => <option key={x.site_id ?? "org"} value={x.site_id ?? ""}>{x.name}</option>)}
            </select></Field>
          <div className="field-hint">{current?.current
            ? `Versão ${current.current.version} por ${current.current.created_by} em ${fmtDate(current.current.created_at)}${current.current.logo ? " · com logomarca" : ""}${current.current.letterhead ? " · com papel timbrado" : ""}`
            : "Sem identidade própria (usa a da organização ou a neutra do sistema)."}</div>
          <Field label="Logomarca"><input type="file" accept="image/png,image/jpeg"
            onChange={(e) => setFiles({ ...files, logo: e.target.files?.[0] })} /></Field>
          <Field label="Papel timbrado (fundo da página)"><input type="file" accept="image/png,image/jpeg"
            onChange={(e) => setFiles({ ...files, letterhead: e.target.files?.[0] })} /></Field>
          <Field label="Cor de destaque"><input type="color" value={(val("accent_color") as string) || defaults?.accent_color || "#12313F"}
            onChange={(e) => set("accent_color", e.target.value)} /></Field>
          <Field label="Fonte"><select value={val("font") as string} onChange={(e) => set("font", e.target.value)}>
            <option value="">Herdada</option><option value="Sans">Sem serifa</option><option value="Serif">Com serifa</option></select></Field>
          {num("font_size", "Tamanho da fonte (pt)", 8, 14, 0.5)}
          {num("logo_height_mm", "Altura da logomarca (mm)", 6, 40)}
          {num("margin_top_mm", "Margem superior (mm)", 5, 60)}
          {num("margin_bottom_mm", "Margem inferior (mm)", 5, 60)}
          {num("margin_left_mm", "Margem esquerda (mm)", 5, 40)}
          {num("margin_right_mm", "Margem direita (mm)", 5, 40)}
          <Field label="Texto do cabeçalho"><input maxLength={300} value={val("header_text") as string} onChange={(e) => set("header_text", e.target.value)} /></Field>
          <Field label="Texto do rodapé"><input maxLength={300} value={val("footer_text") as string} onChange={(e) => set("footer_text", e.target.value)} /></Field>
        </div>
        <label className="check"><input type="checkbox" checked={cfg.page_numbers ?? defaults?.page_numbers ?? true}
          onChange={(e) => set("page_numbers", e.target.checked)} /> Numerar páginas (“Página X de Y”)</label>
        <div className="row-actions">
          <button className="primary" disabled={act.busy}>Salvar nova versão</button>
          <a className="button" href={`/api/v1/report/branding/preview${scope ? `?site_id=${scope}` : ""}`} target="_blank" rel="noopener">Pré-visualizar A4</a>
        </div>
      </form>
    </section>
  );
}
