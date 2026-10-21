import { useEffect, useState, type FormEvent } from "react";
import { errorText, get, post, type Me } from "../api";
import { Field, Notice } from "../ui";

export function Login({ onDone }: { onDone: (m: Me) => void }) {
  const [mode, setMode] = useState<"edge" | "cloud">("edge");
  const [org, setOrg] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    get<{ mode: "edge" | "cloud" }>("/health").then((h) => setMode(h.mode)).catch(() => undefined);
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      onDone(await post<Me>("/auth/login", { username, password, organization: org || null }));
    } catch (x) { setErr(errorText(x)); setPassword(""); } finally { setBusy(false); }
  }

  return (
    <div className="door">
      <form className="door-card" onSubmit={submit} aria-labelledby="login-title">
        <div className="brand brand-lg">
          <svg viewBox="0 0 32 32" aria-hidden="true"><path d="M8 9l8 15 8-15" /></svg>
          <span>VYONIX</span>
        </div>
        <h1 id="login-title">Entrar</h1>
        {mode === "cloud" && (
          <Field label="Organização"><input value={org} onChange={(e) => setOrg(e.target.value)} required
            autoComplete="organization" /></Field>
        )}
        <Field label="Usuário"><input name="username" value={username} onChange={(e) => setUsername(e.target.value)}
          required autoFocus autoComplete="username" /></Field>
        <Field label="Senha"><input name="password" type="password" value={password}
          onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" /></Field>
        <Notice kind="error">{err}</Notice>
        <button className="primary" disabled={busy}>{busy ? "Entrando…" : "Entrar"}</button>
      </form>
    </div>
  );
}

/** Etapas obrigatórias antes do uso: troca de senha, cadastro ou confirmação do segundo fator. */
export function AccessGate({ me, onDone, onLogout }: { me: Me; onDone: () => void; onLogout: () => void }) {
  async function logout() { try { await post("/auth/logout"); } finally { onLogout(); } }
  return (
    <div className="door">
      <div className="door-card">
        {me.stage === "password_change" && <PasswordChange onDone={onDone} />}
        {me.stage === "mfa_enroll" && <MfaEnroll onDone={onDone} />}
        {me.stage === "mfa_verify" && <MfaVerify onDone={onDone} />}
        <button className="link" onClick={logout}>Sair</button>
      </div>
    </div>
  );
}

function PasswordChange({ onDone }: { onDone: () => void }) {
  const [cur, setCur] = useState(""); const [n1, setN1] = useState(""); const [n2, setN2] = useState("");
  const [err, setErr] = useState("");
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (n1 !== n2) { setErr("A confirmação não é igual à nova senha."); return; }
    try { await post("/auth/password", { current: cur, new: n1 }); onDone(); } catch (x) { setErr(errorText(x)); }
  }
  return (
    <form onSubmit={submit}>
      <h1>Defina sua senha</h1>
      <p className="intro">A senha inicial precisa ser trocada. Use ao menos 10 caracteres, com letras maiúsculas,
        minúsculas e números.</p>
      <Field label="Senha atual"><input type="password" value={cur} onChange={(e) => setCur(e.target.value)}
        required autoComplete="current-password" /></Field>
      <Field label="Nova senha"><input type="password" value={n1} onChange={(e) => setN1(e.target.value)}
        required autoComplete="new-password" /></Field>
      <Field label="Repita a nova senha"><input type="password" value={n2} onChange={(e) => setN2(e.target.value)}
        required autoComplete="new-password" /></Field>
      <Notice kind="error">{err}</Notice>
      <button className="primary">Salvar senha</button>
    </form>
  );
}

function MfaEnroll({ onDone }: { onDone: () => void }) {
  const [info, setInfo] = useState<{ secret: string; uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { post<{ secret: string; uri: string }>("/auth/mfa/enroll").then(setInfo)
    .catch((x) => setErr(errorText(x))); }, []);
  async function confirm(e: FormEvent) {
    e.preventDefault();
    try { setCodes((await post<{ recovery_codes: string[] }>("/auth/mfa/confirm", { code })).recovery_codes); }
    catch (x) { setErr(errorText(x)); }
  }
  if (codes) {
    return (
      <div>
        <h1>Guarde os códigos de recuperação</h1>
        <p className="intro">Cada código funciona uma vez, se você perder o celular. Eles não serão mostrados de novo.</p>
        <ul className="codes">{codes.map((c) => <li key={c}><code>{c}</code></li>)}</ul>
        <button className="primary" onClick={onDone}>Já guardei, continuar</button>
      </div>
    );
  }
  return (
    <form onSubmit={confirm}>
      <h1>Ative a verificação em duas etapas</h1>
      <p className="intro">No aplicativo autenticador do celular, adicione uma conta com a chave abaixo e digite o
        código de 6 dígitos que ele mostrar.</p>
      {info && <p className="secret"><code>{info.secret.replace(/(.{4})/g, "$1 ").trim()}</code></p>}
      <Field label="Código do aplicativo"><input inputMode="numeric" pattern="[0-9]{6}" maxLength={6} value={code}
        onChange={(e) => setCode(e.target.value)} required autoComplete="one-time-code" /></Field>
      <Notice kind="error">{err}</Notice>
      <button className="primary">Confirmar</button>
    </form>
  );
}

function MfaVerify({ onDone }: { onDone: () => void }) {
  const [code, setCode] = useState(""); const [err, setErr] = useState("");
  async function submit(e: FormEvent) {
    e.preventDefault();
    try { await post("/auth/mfa/verify", { code }); onDone(); } catch (x) { setErr(errorText(x)); setCode(""); }
  }
  return (
    <form onSubmit={submit}>
      <h1>Verificação em duas etapas</h1>
      <p className="intro">Digite o código do aplicativo autenticador ou um código de recuperação.</p>
      <Field label="Código"><input value={code} onChange={(e) => setCode(e.target.value)} required autoFocus
        autoComplete="one-time-code" maxLength={20} /></Field>
      <Notice kind="error">{err}</Notice>
      <button className="primary">Verificar</button>
    </form>
  );
}
