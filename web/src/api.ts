// Cliente da API do VYONIX Core. A sessão fica em cookie HttpOnly; o token anti-CSRF fica só em memória.

export type Me = {
  user_id: string; tenant_id: string; username: string; display_name: string;
  stage: "ok" | "password_change" | "mfa_enroll" | "mfa_verify";
  permissions: string[]; roles: { role: string; name: string; site_id: string | null }[]; csrf: string;
};

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: Record<string, unknown>) {
    super(message);
  }
}

let csrf = "";
export function setCsrf(token: string) { csrf = token; }

export async function api<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && csrf) headers["X-CSRF-Token"] = csrf;
  let r: Response;
  try {
    r = await fetch(`/api/v1${path}`, { method, headers, credentials: "same-origin",
      body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "network", "Sem conexão com o servidor VYONIX. Verifique a rede e tente de novo.", {});
  }
  const data = r.status === 204 ? null : await r.json().catch(() => null);
  if (!r.ok) {
    const d = (data ?? {}) as { error?: string; message?: string; details?: Record<string, unknown> };
    throw new ApiError(r.status, d.error ?? "error", d.message ?? `Erro ${r.status}.`, d.details ?? {});
  }
  return data as T;
}

export const get = <T,>(p: string) => api<T>("GET", p);
export const post = <T,>(p: string, b: unknown = {}) => api<T>("POST", p, b);
export const put = <T,>(p: string, b: unknown) => api<T>("PUT", p, b);
export const patch = <T,>(p: string, b: unknown) => api<T>("PATCH", p, b);
export const del = <T,>(p: string) => api<T>("DELETE", p);

export function fmtDate(iso: string | null | undefined, withTime = true): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return withTime ? d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })
    : d.toLocaleDateString("pt-BR");
}

export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    const errs = (e.details?.errors as { field: string; message: string }[] | undefined) ?? [];
    return errs.length ? `${e.message} ${errs.map((x) => `${x.field}: ${x.message}`).join("; ")}` : e.message;
  }
  return "Erro inesperado na interface. Recarregue a página.";
}
