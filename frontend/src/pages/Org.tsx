import { useState } from "react";
import { api } from "../api/client";
import type { Page, User } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Badge, Button, Card, Empty, ErrorBox, Field, inputCls, LEVEL_TONE, Loading, PageHeader, Stat } from "../components/ui";
import { useApi } from "../hooks/useApi";

interface Overview {
  learners: number; skills: number; published_skills: number; reports: number; safety_violations: number;
  sessions_by_state: Record<string, number>; competency_levels: Record<string, number>; top_mistakes: [string, number][];
}

const LEVELS = ["NOVICE", "DEVELOPING", "COMPETENT", "PROFICIENT", "EXPERT"];

export function OrgDashboard() {
  const { data: o, error, loading, reload } = useApi<Overview>("/analytics/overview");
  if (loading) return <Loading />;
  if (error || !o) return <ErrorBox message={error ?? "Unavailable"} onRetry={reload} />;
  const totalLevels = Object.values(o.competency_levels).reduce((a, b) => a + b, 0);
  const maxMistake = Math.max(1, ...o.top_mistakes.map(([, n]) => n));

  return (
    <>
      <PageHeader title="Organization" subtitle="Training activity and verified competency across your learners." />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Learners" value={o.learners} />
        <Stat label="Published skills" value={`${o.published_skills} / ${o.skills}`} />
        <Stat label="Assessed sessions" value={o.reports} />
        <Stat label="Safety violations" value={o.safety_violations} sub="caught and blocked by the engine" />
      </div>
      <div className="mt-6 grid gap-5 lg:grid-cols-2">
        <Card className="p-5">
          <h2 className="text-sm font-semibold">Competency levels</h2>
          {totalLevels === 0 ? <p className="mt-3 text-sm text-muted">No assessed learners yet.</p> : (
            <>
              <div className="mt-4 flex h-3 overflow-hidden rounded-full bg-surface-2" role="img" aria-label="Distribution of competency levels">
                {LEVELS.map((l, i) => o.competency_levels[l] ? (
                  <div key={l} title={`${l}: ${o.competency_levels[l]}`} style={{ width: `${(o.competency_levels[l] / totalLevels) * 100}%`, opacity: 0.35 + i * 0.16 }} className="h-full border-r-2 border-surface bg-accent last:border-r-0" />
                ) : null)}
              </div>
              <ul className="mt-4 space-y-1.5 text-sm">
                {LEVELS.map((l) => <li key={l} className="flex justify-between"><Badge tone={LEVEL_TONE[l]}>{l}</Badge><span className="tabular-nums">{o.competency_levels[l] ?? 0}</span></li>)}
              </ul>
            </>
          )}
        </Card>
        <Card className="p-5">
          <h2 className="text-sm font-semibold">Most frequent mistakes</h2>
          {o.top_mistakes.length === 0 ? <p className="mt-3 text-sm text-muted">No identified mistakes recorded yet.</p> : (
            <ul className="mt-4 space-y-3">
              {o.top_mistakes.map(([id, n]) => (
                <li key={id}>
                  <div className="flex justify-between text-sm"><span>{id.replace(/_/g, " ")}</span><span className="tabular-nums text-muted">{n}</span></div>
                  <div className="mt-1 h-1.5 rounded-full bg-surface-2"><div className="h-full rounded-full bg-failed" style={{ width: `${(n / maxMistake) * 100}%` }} /></div>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card className="p-5 lg:col-span-2">
          <h2 className="text-sm font-semibold">Sessions by state</h2>
          <div className="mt-3 flex flex-wrap gap-2">
            {Object.entries(o.sessions_by_state).length === 0 ? <p className="text-sm text-muted">No sessions yet.</p> :
              Object.entries(o.sessions_by_state).map(([s, n]) => <span key={s} className="rounded-lg bg-surface-2 px-3 py-1.5 text-sm">{s.replace(/_/g, " ").toLowerCase()} <span className="font-semibold tabular-nums">{n}</span></span>)}
          </div>
        </Card>
      </div>
    </>
  );
}

export function AdminPage() {
  const { user } = useAuth();
  const { data, error, loading, reload } = useApi<Page<User>>("/users?limit=200");
  const [f, setF] = useState({ full_name: "", email: "", password: "", role: "learner" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api("/users", { method: "POST", json: f });
      setF({ full_name: "", email: "", password: "", role: "learner" });
      reload();
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const deactivate = async (u: User) => {
    if (!window.confirm(`Deactivate ${u.full_name}? They will no longer be able to sign in.`)) return;
    try {
      await api(`/users/${u.id}`, { method: "DELETE" });
      reload();
    } catch (x) {
      setErr((x as Error).message);
    }
  };

  return (
    <>
      <PageHeader title="Administration" subtitle="Manage the people in your organization." />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <section>
          {loading ? <Loading /> : error ? <ErrorBox message={error} onRetry={reload} /> : data!.items.length === 0 ? <Empty title="No users" /> : (
            <Card className="divide-y divide-line">
              {data!.items.map((u) => (
                <div key={u.id} className="flex items-center justify-between gap-3 p-4">
                  <div className="min-w-0"><p className="truncate text-sm font-medium">{u.full_name}</p><p className="truncate text-xs text-muted">{u.email}</p></div>
                  <div className="flex items-center gap-2"><Badge tone={u.role === "admin" ? "accent" : "neutral"}>{u.role}</Badge>
                    {u.id !== user?.id && <Button variant="ghost" onClick={() => deactivate(u)}>Deactivate</Button>}</div>
                </div>
              ))}
            </Card>
          )}
        </section>
        <Card className="h-fit p-5">
          <h2 className="mb-4 text-sm font-semibold">Add a person</h2>
          <form onSubmit={create} className="space-y-3">
            <Field label="Name"><input className={inputCls} required value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
            <Field label="Email"><input className={inputCls} type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
            <Field label="Temporary password" hint="At least 10 characters. Share it securely."><input className={inputCls} type="password" required minLength={10} value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
            <Field label="Role">
              <select className={inputCls} value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
                <option value="learner">Learner</option><option value="expert">Expert / instructor</option><option value="admin">Admin</option>
              </select>
            </Field>
            {err && <ErrorBox message={err} />}
            <Button type="submit" className="w-full" busy={busy}>Add person</Button>
          </form>
        </Card>
      </div>
    </>
  );
}
