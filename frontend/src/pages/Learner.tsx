import { useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Competency, LearningSession, Page, Report, Skill, SkillDetail } from "../api/types";
import { homeFor, useAuth } from "../auth/AuthContext";
import { Badge, Button, Card, Empty, ErrorBox, fmtDate, inputCls, LEVEL_TONE, Loading, PageHeader, Stat } from "../components/ui";
import { useApi } from "../hooks/useApi";

const DONE = new Set(["COMPLETED", "ABANDONED"]);

export function LearnerDashboard() {
  const { user } = useAuth();
  const sessions = useApi<Page<LearningSession>>(user?.role === "learner" ? "/sessions?limit=50" : null);
  const comps = useApi<Competency[]>(user?.role === "learner" ? `/users/${user.id}/competencies` : null);
  const skills = useApi<Page<Skill>>(user?.role === "learner" ? "/skills" : null);
  if (user && user.role !== "learner") return <Navigate to={homeFor(user)} replace />;
  if (sessions.loading || comps.loading || skills.loading) return <Loading />;
  const err = sessions.error ?? comps.error ?? skills.error;
  if (err) return <ErrorBox message={err} onRetry={() => { sessions.reload(); comps.reload(); skills.reload(); }} />;

  const all = sessions.data!.items;
  const active = all.filter((s) => !DONE.has(s.state));
  const title = (id: string) => skills.data!.items.find((k) => k.id === id)?.title ?? "Skill";
  const proficient = comps.data!.filter((c) => ["PROFICIENT", "EXPERT"].includes(c.level)).length;

  return (
    <>
      <PageHeader title={`Welcome back, ${user!.full_name.split(" ")[0]}`} subtitle="Your practical training at a glance." />
      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Sessions" value={all.length} sub={`${active.length} in progress`} />
        <Stat label="Completed" value={all.filter((s) => s.state === "COMPLETED").length} />
        <Stat label="Proficient skills" value={`${proficient} / ${skills.data!.total}`} sub="Proficient needs an independent assessment" />
      </div>

      <h2 className="mb-3 mt-8 font-semibold">Continue</h2>
      {active.length === 0 ? (
        <Empty title="No sessions in progress" hint="Pick a skill from the library to start practising." action={<Link to="/app/skills"><Button>Browse skills</Button></Link>} />
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {active.map((s) => (
            <Link key={s.id} to={`/app/sessions/${s.id}`}>
              <Card className="p-4 transition hover:border-accent">
                <div className="flex items-center justify-between gap-2"><p className="font-medium">{title(s.skill_id)}</p>
                  <Badge tone={s.state === "BLOCKED_BY_SAFETY" ? "failed" : s.state === "AWAITING_EVIDENCE" || s.state === "NEEDS_HUMAN_REVIEW" ? "uncertain" : "accent"}>{s.state.replace(/_/g, " ").toLowerCase()}</Badge></div>
                <p className="mt-1 text-sm text-muted">{s.mode} · {s.verified_steps.length} steps verified · started {fmtDate(s.started_at ?? s.created_at)}</p>
              </Card>
            </Link>
          ))}
        </div>
      )}

      <h2 className="mb-3 mt-8 font-semibold">Competency</h2>
      {comps.data!.length === 0 ? <Empty title="No assessed skills yet" hint="Complete a session to build your competency profile." /> : (
        <div className="grid gap-3 md:grid-cols-3">
          {comps.data!.map((c) => (
            <Card key={c.skill_id} className="p-4"><p className="text-sm font-medium">{title(c.skill_id)}</p>
              <div className="mt-2"><Badge tone={LEVEL_TONE[c.level]}>{c.level}</Badge></div>
              <p className="mt-2 text-xs text-muted">{c.completions} of {c.attempts} attempts completed</p></Card>
          ))}
        </div>
      )}
    </>
  );
}

export function SkillLibrary() {
  const { user } = useAuth();
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const { data, error, loading, reload } = useApi<Page<Skill>>(`/skills?limit=100${query ? `&q=${encodeURIComponent(query)}` : ""}`);
  return (
    <>
      <PageHeader title="Skill library" subtitle="Approved procedures you can practise and be assessed on."
        actions={user?.role !== "learner" && <Link to="/app/capture"><Button>Capture new skill</Button></Link>} />
      <form className="mb-5 flex max-w-md gap-2" onSubmit={(e) => { e.preventDefault(); setQuery(q.trim()); }}>
        <input className={inputCls} placeholder="Search skills" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search skills" />
        <Button variant="secondary" type="submit">Search</Button>
      </form>
      {loading ? <Loading /> : error ? <ErrorBox message={error} onRetry={reload} /> : data!.items.length === 0 ? (
        <Empty title={query ? "No skills match your search" : "No skills yet"} hint={user?.role === "learner" ? "Your instructors haven't published any skills yet." : "Upload a demonstration video to create one."} />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data!.items.map((s) => (
            <Link key={s.id} to={`/app/skills/${s.id}`}>
              <Card className="flex h-full flex-col p-5 transition hover:border-accent">
                <div className="flex gap-1.5"><Badge>{s.domain}</Badge><Badge>{s.difficulty}</Badge>{!s.published_version_id && <Badge tone="uncertain">draft</Badge>}</div>
                <h3 className="mt-3 font-semibold">{s.title}</h3>
                <p className="mt-1 line-clamp-3 text-sm text-muted">{s.summary}</p>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}

export function SkillDetailPage() {
  const { id } = useParams();
  const { user } = useAuth();
  const nav = useNavigate();
  const { data, error, loading, reload } = useApi<SkillDetail>(`/skills/${id}`);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox message={error ?? "Not found"} onRetry={reload} />;

  const published = data.versions.find((v) => v.id === data.published_version_id);
  const latest = data.versions[data.versions.length - 1];
  const g = (published ?? latest).graph;
  const start = async (mode: "guided" | "assessment") => {
    setBusy(mode);
    setErr(null);
    try {
      const s = await api<LearningSession>("/sessions", { method: "POST", json: { skill_id: data.id, mode } });
      nav(`/app/sessions/${s.id}`);
    } catch (e) {
      setErr((e as Error).message);
      setBusy(null);
    }
  };

  return (
    <>
      <PageHeader title={data.title} subtitle={`${g.difficulty} · about ${g.estimated_duration} min · ${g.steps.length} steps`}
        actions={<>
          {user?.role !== "learner" && <Link to={`/app/skills/${data.id}/review`}><Button variant="secondary">Review &amp; edit</Button></Link>}
          {published && <><Button variant="secondary" busy={busy === "guided"} onClick={() => start("guided")}>Practise (guided)</Button>
            <Button busy={busy === "assessment"} onClick={() => start("assessment")}>Take assessment</Button></>}
        </>} />
      {err && <div className="mb-4"><ErrorBox message={err} /></div>}
      {!published && <div className="mb-4 rounded-lg bg-uncertain-soft p-3 text-sm text-uncertain">Not published yet. An expert must review and approve it before learners can use it.</div>}
      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="p-5 lg:col-span-2">
          <p className="text-sm text-muted">{g.summary}</p>
          <h2 className="mt-5 text-sm font-semibold">Procedure</h2>
          <ol className="mt-3 space-y-2">
            {g.steps.map((s, i) => (
              <li key={s.step_id} className="flex gap-3 rounded-lg border border-line p-3">
                <span className="font-mono text-xs text-muted">{String(i + 1).padStart(2, "0")}</span>
                <div className="min-w-0">
                  <p className="text-sm font-medium">{s.title} {s.safety.critical && <Badge tone="failed">safety</Badge>}</p>
                  <p className="mt-0.5 text-xs text-muted">Checked by: {s.validation.methods.map((m) => m.type.replace(/_/g, " ")).join(" + ")}
                    {s.transitions.some((t) => t.condition.type !== "verified" && t.condition.type !== "always") && " · branches"}</p>
                </div>
              </li>
            ))}
          </ol>
        </Card>
        <div className="space-y-4">
          <Card className="p-5"><h3 className="text-sm font-semibold">Tools</h3>
            <div className="mt-2 flex flex-wrap gap-1.5">{g.required_tools.map((t) => <Badge key={t}>{t.replace(/_/g, " ")}</Badge>)}</div>
            <h3 className="mt-4 text-sm font-semibold">Components</h3>
            <div className="mt-2 flex flex-wrap gap-1.5">{g.required_components.map((t) => <Badge key={t}>{t.replace(/_/g, " ")}</Badge>)}</div></Card>
          <Card className="p-5 text-sm"><h3 className="font-semibold">Guided vs assessment</h3>
            <p className="mt-2 text-muted">Guided practice lets you ask for help. An assessment must be done without help, and it is the only way to reach Proficient.</p></Card>
        </div>
      </div>
    </>
  );
}

export function ReportPage() {
  const { id } = useParams();
  const { data: r, error, loading, reload } = useApi<Report>(`/assessments/${id}`);
  if (loading) return <Loading />;
  if (error || !r) return <ErrorBox message={error ?? "Not found"} onRetry={reload} />;
  const m = r.metrics;
  const ratio = (x: { numerator: number; denominator: number; value: number | null }) =>
    x.value === null ? "not assessed" : `${Math.round(x.value * 100)}%`;
  const sub = (x: { numerator: number; denominator: number }) => x.denominator ? `${x.numerator} of ${x.denominator}` : "no evidence for this metric";

  return (
    <>
      <PageHeader title="Competency report" subtitle={`${r.mode === "assessment" ? "Independent assessment" : "Guided practice"} · ${fmtDate(r.created_at)}`}
        actions={<Button variant="secondary" onClick={() => window.print()}>Print</Button>} />
      <Card className="mb-5 flex flex-wrap items-center justify-between gap-4 p-5">
        <div><p className="text-xs font-medium uppercase tracking-wider text-muted">Result for this session</p>
          <p className="mt-1 text-2xl font-semibold">{r.session_level}</p></div>
        <Badge tone={LEVEL_TONE[r.session_level]}>{m.completed ? "Completed" : "Not completed"}</Badge>
      </Card>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Task completion" value={ratio(m.task_completion)} sub={sub(m.task_completion)} />
        <Stat label="Correct sequence" value={ratio(m.correct_sequence)} sub={`${m.out_of_sequence_attempts} out-of-order attempts`} />
        <Stat label="Safety compliance" value={ratio(m.safety_compliance)} sub={`${m.safety_violations} safety violations`} />
        <Stat label="Tool use" value={ratio(m.tool_selection)} sub={sub(m.tool_selection)} />
        <Stat label="Failed checks" value={m.mistakes} sub={m.mistake_ids.length ? m.mistake_ids.join(", ").replace(/_/g, " ") : "none identified"} />
        <Stat label="Recovered" value={ratio(m.recovery)} sub="failed steps later corrected" />
        <Stat label="Assistance" value={m.assistance_requests + m.instructor_signoffs} sub={`${m.assistance_requests} questions · ${m.instructor_signoffs} sign-offs`} />
        <Stat label="Time" value={m.duration_minutes !== null ? `${m.duration_minutes} min` : "n/a"} sub={`estimate ${m.estimated_minutes} min`} />
      </div>
      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Card className="p-5">
          <h2 className="text-sm font-semibold">How this level was decided</h2>
          <ul className="mt-3 space-y-2">
            {r.rule_trace.map((t) => (
              <li key={t.criterion} className="flex items-start gap-2 text-sm">
                <span className={t.passed ? "text-verified" : "text-failed"}>{t.passed ? "✓" : "✕"}</span>
                <span><span className="font-medium">{t.criterion.replace(/_/g, " ")}</span> <span className="text-muted">· {t.detail}</span></span>
              </li>
            ))}
          </ul>
        </Card>
        <Card className="p-5">
          <h2 className="text-sm font-semibold">Path taken</h2>
          <ol className="mt-3 flex flex-wrap gap-1.5 text-xs">{m.path.map((p, i) => <li key={i} className="rounded-md bg-surface-2 px-2 py-1 font-mono">{p}</li>)}</ol>
          {m.branches_taken.length > 0 && <p className="mt-3 text-sm text-muted">Branches: {m.branches_taken.join(", ")}</p>}
          <p className="mt-4 text-xs text-muted">Every number on this page is calculated from the evidence and validation events recorded in the session. {m.uncertain_validations} checks were inconclusive and needed more evidence.</p>
        </Card>
      </div>
    </>
  );
}

export function CompetencyProfile() {
  const { user } = useAuth();
  const comps = useApi<Competency[]>(user ? `/users/${user.id}/competencies` : null);
  const reports = useApi<Page<Report>>("/assessments?limit=50");
  const skills = useApi<Page<Skill>>("/skills");
  if (comps.loading || reports.loading || skills.loading) return <Loading />;
  const err = comps.error ?? reports.error ?? skills.error;
  if (err) return <ErrorBox message={err} />;
  const title = (id: string) => skills.data!.items.find((k) => k.id === id)?.title ?? "Skill";
  const criteria = comps.data![0]?.evidence.criteria;

  return (
    <>
      <PageHeader title="Competency profile" subtitle="Levels come from explicit criteria, not from how many courses you finished." />
      {comps.data!.length === 0 ? <Empty title="No competency data yet" hint="Complete a practical session to start your profile." /> : (
        <div className="grid gap-4 md:grid-cols-2">
          {comps.data!.map((c) => (
            <Card key={c.skill_id} className="p-5">
              <div className="flex items-center justify-between"><p className="font-medium">{title(c.skill_id)}</p><Badge tone={LEVEL_TONE[c.level]}>{c.level}</Badge></div>
              <dl className="mt-4 grid grid-cols-3 gap-2 text-center text-sm">
                <div className="rounded-lg bg-surface-2 p-2"><dt className="text-xs text-muted">Guided</dt><dd className="font-semibold">{c.evidence.guided_completions}</dd></div>
                <div className="rounded-lg bg-surface-2 p-2"><dt className="text-xs text-muted">Independent</dt><dd className="font-semibold">{c.evidence.independent_completions}</dd></div>
                <div className="rounded-lg bg-surface-2 p-2"><dt className="text-xs text-muted">Attempts</dt><dd className="font-semibold">{c.attempts}</dd></div>
              </dl>
              <p className="mt-3 text-xs text-muted">{c.evidence.basis}</p>
            </Card>
          ))}
        </div>
      )}
      {criteria && (
        <Card className="mt-5 p-5"><h2 className="text-sm font-semibold">Level criteria</h2>
          <dl className="mt-3 space-y-2 text-sm">{Object.entries(criteria).map(([k, v]) => <div key={k}><dt className="inline font-medium">{k}: </dt><dd className="inline text-muted">{v}</dd></div>)}</dl></Card>
      )}
      <h2 className="mb-3 mt-8 font-semibold">Reports</h2>
      {reports.data!.items.length === 0 ? <Empty title="No reports yet" /> : (
        <Card className="divide-y divide-line">
          {reports.data!.items.map((r) => (
            <Link key={r.id} to={`/app/reports/${r.id}`} className="flex items-center justify-between gap-3 p-4 hover:bg-surface-2">
              <div><p className="text-sm font-medium">{title(r.skill_id)}</p><p className="text-xs text-muted">{r.mode} · {fmtDate(r.created_at)}</p></div>
              <Badge tone={LEVEL_TONE[r.session_level]}>{r.session_level}</Badge>
            </Link>
          ))}
        </Card>
      )}
    </>
  );
}
