import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { homeFor, useAuth } from "../auth/AuthContext";
import { Logo } from "../components/Logo";
import { Button, ErrorBox, Field, inputCls } from "../components/ui";

function Frame({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-full items-center justify-center bg-ink-900 px-4 py-12">
      <div className="w-full max-w-sm">
        <Link to="/" className="mb-8 flex justify-center"><Logo dark /></Link>
        <div className="rounded-2xl bg-surface p-6 shadow-xl">
          <h1 className="mb-5 text-lg font-semibold">{title}</h1>
          {children}
        </div>
      </div>
    </div>
  );
}

export function Login() {
  const { user, login } = useAuth();
  const nav = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from;
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (user) return <Navigate to={from ?? homeFor(user)} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const u = await login(email, password);
      nav(from ?? homeFor(u), { replace: true });
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Frame title="Sign in">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Email"><input className={inputCls} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label="Password"><input className={inputCls} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
        {err && <ErrorBox message={err} />}
        <Button type="submit" className="w-full" busy={busy}>Sign in</Button>
      </form>
      <p className="mt-5 text-center text-sm text-muted">New organization? <Link to="/register" className="font-medium text-accent">Create one</Link></p>
      <details className="mt-4 rounded-lg bg-surface-2 p-3 text-xs text-muted">
        <summary className="cursor-pointer font-medium">Demo accounts</summary>
        <p className="mt-2">learner@, expert@ or admin@demo.skillos.dev, password <span className="font-mono">skillos-demo-2026</span></p>
      </details>
    </Frame>
  );
}

export function Register() {
  const { user, register } = useAuth();
  const nav = useNavigate();
  const [f, setF] = useState({ full_name: "", email: "", password: "", organization_name: "" });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (user) return <Navigate to={homeFor(user)} replace />;
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const u = await register(f);
      nav(homeFor(u), { replace: true });
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Frame title="Create your organization">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Organization" hint="Your institution or company. You'll be its administrator."><input className={inputCls} required minLength={2} value={f.organization_name} onChange={set("organization_name")} /></Field>
        <Field label="Your name"><input className={inputCls} required autoComplete="name" value={f.full_name} onChange={set("full_name")} /></Field>
        <Field label="Email"><input className={inputCls} type="email" required autoComplete="email" value={f.email} onChange={set("email")} /></Field>
        <Field label="Password" hint="At least 10 characters."><input className={inputCls} type="password" required minLength={10} autoComplete="new-password" value={f.password} onChange={set("password")} /></Field>
        {err && <ErrorBox message={err} />}
        <Button type="submit" className="w-full" busy={busy}>Create organization</Button>
      </form>
      <p className="mt-5 text-center text-sm text-muted">Already have an account? <Link to="/login" className="font-medium text-accent">Sign in</Link></p>
    </Frame>
  );
}
