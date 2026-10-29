import { useEffect, useRef, useState, type KeyboardEvent } from "react";

/**
 * Texto rico do laudo: o mesmo subconjunto seguro do servidor (vyonix/report/richtext.py).
 * Permitido: parágrafos, quebras, títulos (h3/h4), negrito, itálico, sublinhado, listas e tabelas simples.
 * Todo o resto é descartado (texto mantido), e o servidor sanitiza de novo ao gravar.
 */
const BLOCK = new Set(["p", "h3", "h4", "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td"]);
const INLINE = new Set(["strong", "em", "u", "br"]);
const ALIAS: Record<string, string> = { b: "strong", i: "em", h1: "h3", h2: "h3", h5: "h4", h6: "h4", div: "p",
  section: "p", article: "p", blockquote: "p", caption: "p", tfoot: "tbody" };
const DROP = new Set(["script", "style", "iframe", "object", "embed", "noscript", "template", "svg", "math", "head",
  "title", "textarea", "select", "button", "form", "img", "video", "audio", "link", "meta"]);

function esc(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function walk(n: Node, out: string[]): void {
  n.childNodes.forEach((c) => {
    if (c.nodeType === Node.TEXT_NODE) { out.push(esc(c.textContent ?? "")); return; }
    if (c.nodeType !== Node.ELEMENT_NODE) return;
    const el = c as Element;
    const raw = el.tagName.toLowerCase();
    if (DROP.has(raw)) return;
    // Word/Google Docs colam negrito/itálico como estilo: preserva o que dá para preservar com segurança
    const st = (el as HTMLElement).style;
    let tag = ALIAS[raw] ?? raw;
    if (tag === "span" && st) {
      const inner: string[] = [];
      walk(el, inner);
      let h = inner.join("");
      if (st.textDecoration.includes("underline")) h = `<u>${h}</u>`;
      if (st.fontStyle === "italic") h = `<em>${h}</em>`;
      if (st.fontWeight === "bold" || Number(st.fontWeight) >= 600) h = `<strong>${h}</strong>`;
      out.push(h);
      return;
    }
    if (tag === "br") { out.push("<br>"); return; }
    if (!BLOCK.has(tag) && !INLINE.has(tag)) { walk(el, out); return; }
    let attrs = "";
    if (tag === "td" || tag === "th") {
      for (const a of ["colspan", "rowspan"]) {
        const v = el.getAttribute(a);
        if (v && /^\d+$/.test(v) && Number(v) > 1 && Number(v) <= 10) attrs += ` ${a}="${Number(v)}"`;
      }
    }
    out.push(`<${tag}${attrs}>`);
    walk(el, out);
    out.push(`</${tag}>`);
  });
}

export function sanitizeHtml(html: string): string {
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");
  const out: string[] = [];
  walk(doc.body, out);
  return out.join("").trim();
}

/** Texto simples (laudos/modelos antigos) → HTML equivalente. */
export function textToHtml(text: string): string {
  return (text ?? "").trim().split(/\n{2,}/).filter((p) => p.trim())
    .map((p) => `<p>${esc(p).replace(/\n/g, "<br>")}</p>`).join("");
}

export function asHtml(body: string, format: string | undefined): string {
  return format === "html" ? body : textToHtml(body);
}

/** Exibição somente leitura (versões liberadas, histórico, frases). */
export function RichView({ html, format, label }: { html: string; format?: string; label?: string }) {
  if (format !== "html") return <pre className="report-text" aria-label={label}>{html}</pre>;
  return <div className="rich-view" aria-label={label} dangerouslySetInnerHTML={{ __html: sanitizeHtml(html) }} />;
}

export type Phrase = { id: string; title: string; shortcut: string | null; body: string; personal: boolean;
  favorite?: boolean; category?: string | null; variables?: string[] };

type Props = { label: string; value: string; onChange: (html: string) => void; readOnly?: boolean; rows?: number;
  phrases?: Phrase[]; hint?: string; fields?: Record<string, string | null> };

const FIELD = /\{\{\s*([a-z_.]+)\s*\}\}/g;
const VAR = /\[\[([^\[\]<>]{1,40})\]\]/g;

/** Preenche os campos do exame ({{...}}) e os editáveis ([[...]]) com valores escapados. */
export function fillPhrase(body: string, fields: Record<string, string | null> | undefined, values: Record<string, string>): string {
  let h = body.replace(FIELD, (m, k: string) => (fields && k in fields ? esc(fields[k] || "[não informado]") : m));
  h = h.replace(VAR, (m, k: string) => (values[k.trim()] ? esc(values[k.trim()]) : m));
  return h;
}

/**
 * Editor com barra de formatação. Colar do Word mantém negrito, itálico, sublinhado, listas e tabelas e descarta o
 * resto. Frases rápidas: escolher na lista ou digitar o atalho (ex.: /normal) seguido de espaço.
 */
export function RichEditor({ label, value, onChange, readOnly, rows = 8, phrases, hint, fields }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const last = useRef<string>("");
  const saved = useRef<Range | null>(null);
  const [pick, setPick] = useState("");
  const [pending, setPending] = useState<{ phrase: Phrase; values: Record<string, string> } | null>(null);

  useEffect(() => {                                  // valor vindo de fora (abrir laudo, trocar modelo)
    if (ref.current && value !== last.current) {
      ref.current.innerHTML = sanitizeHtml(value);
      last.current = value;
    }
  }, [value]);

  function emit() {
    if (!ref.current) return;
    const h = sanitizeHtml(ref.current.innerHTML);
    last.current = h;
    onChange(h);
  }
  function cmd(name: string, arg?: string) {
    if (readOnly) return;
    ref.current?.focus();
    document.execCommand(name, false, arg);
    emit();
  }
  function applyPhrase(p: Phrase) {
    const vars = p.variables ?? [];
    if (vars.length === 0) { insertHtml(fillPhrase(p.body, fields, {})); return; }
    const sel = window.getSelection();                // guarda o cursor enquanto o médico preenche os campos
    saved.current = sel && sel.rangeCount && ref.current?.contains(sel.anchorNode) ? sel.getRangeAt(0).cloneRange() : null;
    setPending({ phrase: p, values: Object.fromEntries(vars.map((v) => [v, ""])) });
  }
  function confirmPending() {
    if (!pending) return;
    const h = fillPhrase(pending.phrase.body, fields, pending.values);
    setPending(null);
    if (saved.current && ref.current) {
      ref.current.focus();
      const sel = window.getSelection();
      sel?.removeAllRanges(); sel?.addRange(saved.current);
    }
    insertHtml(h);
  }
  function insertHtml(h: string) {
    if (readOnly || !ref.current) return;
    ref.current.focus();
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount || !ref.current.contains(sel.anchorNode)) {   // sem cursor no editor: no fim
      const r = document.createRange();
      r.selectNodeContents(ref.current);
      r.collapse(false);
      sel?.removeAllRanges(); sel?.addRange(r);
    }
    document.execCommand("insertHTML", false, sanitizeHtml(h));
    emit();
  }
  function table() {
    insertHtml("<table><tbody><tr><th>&nbsp;</th><th>&nbsp;</th></tr><tr><td>&nbsp;</td><td>&nbsp;</td></tr></tbody></table><p><br></p>");
  }
  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if ((e.ctrlKey || e.metaKey) && ["b", "i", "u"].includes(e.key.toLowerCase())) {
      e.preventDefault();
      cmd({ b: "bold", i: "italic", u: "underline" }[e.key.toLowerCase()]!);
      return;
    }
    if (e.key !== " " || !phrases?.length) return;
    const sel = window.getSelection();
    const node = sel?.anchorNode;
    if (!sel || !node || node.nodeType !== Node.TEXT_NODE) return;
    const before = (node.textContent ?? "").slice(0, sel.anchorOffset);
    const m = /(\/[a-z0-9._-]{1,29})$/.exec(before);
    const ph = m && phrases.find((p) => p.shortcut === m[1]);
    if (!ph || !m) return;
    e.preventDefault();
    const r = document.createRange();
    r.setStart(node, sel.anchorOffset - m[1].length);
    r.setEnd(node, sel.anchorOffset);
    sel.removeAllRanges(); sel.addRange(r);
    document.execCommand("delete");
    applyPhrase(ph);
  }

  return (
    <div className="field rich">
      <span className="field-label" id={`${label}-lbl`}>{label}</span>
      {!readOnly && (
        <div className="rich-toolbar" role="toolbar" aria-label={`Formatação: ${label}`}>
          <button type="button" title="Negrito (Ctrl+B)" aria-label="Negrito" onMouseDown={(e) => e.preventDefault()} onClick={() => cmd("bold")}><strong>N</strong></button>
          <button type="button" title="Itálico (Ctrl+I)" aria-label="Itálico" onMouseDown={(e) => e.preventDefault()} onClick={() => cmd("italic")}><em>I</em></button>
          <button type="button" title="Sublinhado (Ctrl+U)" aria-label="Sublinhado" onMouseDown={(e) => e.preventDefault()} onClick={() => cmd("underline")}><u>S</u></button>
          <button type="button" title="Título" aria-label="Título" onMouseDown={(e) => e.preventDefault()} onClick={() => cmd("formatBlock", "h3")}>T</button>
          <button type="button" title="Parágrafo" aria-label="Parágrafo" onMouseDown={(e) => e.preventDefault()} onClick={() => cmd("formatBlock", "p")}>¶</button>
          <button type="button" title="Lista com marcadores" aria-label="Lista com marcadores" onMouseDown={(e) => e.preventDefault()} onClick={() => cmd("insertUnorderedList")}>•</button>
          <button type="button" title="Lista numerada" aria-label="Lista numerada" onMouseDown={(e) => e.preventDefault()} onClick={() => cmd("insertOrderedList")}>1.</button>
          <button type="button" title="Inserir tabela 2×2" aria-label="Inserir tabela" onMouseDown={(e) => e.preventDefault()} onClick={table}>▦</button>
          <button type="button" title="Limpar formatação" aria-label="Limpar formatação" onMouseDown={(e) => e.preventDefault()} onClick={() => cmd("removeFormat")}>⌫</button>
          {phrases && phrases.length > 0 && (
            <select aria-label="Inserir frase rápida" value={pick} onChange={(e) => {
              const p = phrases.find((x) => x.id === e.target.value);
              if (p) applyPhrase(p);
              setPick("");
            }}>
              <option value="">Inserir frase…</option>
              {phrases.map((p) => <option key={p.id} value={p.id}>{p.favorite ? "★ " : ""}{p.category ? `${p.category} › ` : ""}{p.title}{p.shortcut ? ` (${p.shortcut})` : ""}{p.personal ? " · minha" : ""}</option>)}
            </select>)}
        </div>)}
      {pending && (
        <div className="panel-inset" role="group" aria-label="Campos da frase">
          <strong>{pending.phrase.title}</strong>: preencha os campos (vazios ficam marcados para completar depois).
          <div className="filters">
            {Object.keys(pending.values).map((k, i) => (
              <input key={k} aria-label={k} placeholder={k} maxLength={200} autoFocus={i === 0} value={pending.values[k]}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); confirmPending(); } }}
                onChange={(e) => setPending({ ...pending, values: { ...pending.values, [k]: e.target.value } })} />))}
            <button type="button" className="primary" onClick={confirmPending}>Inserir frase</button>
            <button type="button" className="link" onClick={() => setPending(null)}>Cancelar</button>
          </div>
        </div>)}
      <div ref={ref} className="rich-area" role="textbox" aria-multiline="true" aria-label={label}
        aria-readonly={readOnly ? "true" : undefined} contentEditable={!readOnly} suppressContentEditableWarning
        style={{ minHeight: `${rows * 1.5}rem` }} spellCheck lang="pt-BR"
        onInput={emit} onBlur={emit} onKeyDown={onKeyDown}
        onPaste={(e) => {
          if (readOnly) return;
          e.preventDefault();
          const h = e.clipboardData.getData("text/html");
          insertHtml(h ? sanitizeHtml(h) : textToHtml(e.clipboardData.getData("text/plain")));
        }}
        onDrop={(e) => e.preventDefault()} />
      {hint && <span className="field-hint">{hint}</span>}
    </div>
  );
}
