export type ModuleStatus = {
  module: string; label: string; licensed: boolean; kind: string | null; state: string; message: string;
  ends_at: string | null; limits: Record<string, number>;
};
export type LicenseInfo = {
  installation_id: string; hardware_id: string; mode: string;
  license: null | {
    license_id: string; type: string; type_label: string; edition: string; customer: string; issued_at: string;
    expires_at: string | null; schema: number; validation: string; connectivity: string; connectivity_label: string;
    last_online_ok: string | null;
  };
  modules: ModuleStatus[];
  documents: { kind: string; license_id: string; seq: number; status: string; applied_by: string; applied_at: string }[];
};
export type ModuleRow = {
  code: string; name: string; description: string; version: string; depends: string[]; available: boolean;
  always_enabled: boolean; requires_license: boolean; status: string; licensed: boolean; license_message: string;
};
export type Site = { id: string; name: string; cnes: string | null; timezone: string; active: boolean };
export type AuditRow = { seq: number; at: string; actor: string; action: string; target_type: string | null;
  target_id: string | null; details: Record<string, unknown>; ip: string | null };

export const STATE_LABEL: Record<string, string> = {
  unlicensed: "Sem licença", active: "Ativa", due_soon: "Próxima do vencimento", overdue: "Em atraso",
  suspension_scheduled: "Suspensão programada", suspended: "Suspensa", expired: "Expirada", reactivated: "Reativada",
  demo: "Demonstração", demo_expired: "Demonstração encerrada", blocked: "Bloqueada",
  auth_expired: "Validação online pendente",
};
export const KIND_LABEL: Record<string, string> = { subscription: "Assinatura", permanent: "Permanente",
  demo: "Demonstração" };

export function tone(state: string): "ok" | "warn" | "bad" | "off" {
  if (["active", "reactivated", "demo"].includes(state)) return "ok";
  if (["due_soon", "overdue", "suspension_scheduled"].includes(state)) return "warn";
  if (state === "unlicensed") return "off";
  return "bad";
}
