import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Capabilities, Job, LearningSession, Page, Skill, User, Video } from "../api/types";
import { Badge, Button, Card, Empty, ErrorBox, Field, fmtDate, inputCls, Loading, PageHeader, Stat } from "../components/ui";
import { useApi } from "../hooks/useApi";

export function ExpertDashboard() {
  const skills = useApi<Page<Skill>>("/skills?limit=100");
  const review = useApi<Page<LearningSession>>("/sessions?state=NEEDS_HUMAN_REVIEW&limit=50");
  const blocked = useApi<Page<LearningSession>>("/sessions?state=BLOCKED_BY_SAFETY&limit=50");
  const learners = useApi<Page<User>>("/users?role=learner&limit=200");
  if (skills.loading || review.loading || blocked.loading || learners.loading) return <Loading />;
  const err = skills.error ?? review.error ?? blocked.error ?? learners.error;
  if (err) return <ErrorBox message={err} />;
  const drafts = skills.data!.items.filter((s) => !s.published_version_id);
  const name = (id: string) => learners.data!.items.find((u) => u.id === id)?.full_name ?? "Learner";
  const title = (id: string) => skills.data!.items.find((s) => s.id === id)?.title ?? "Skill";

  return (
    <>
      <PageHeader title="Expert dashboard" subtitle="Review generated skills and support learners who need you."
        actions={<Link to="/app/capture"><Button>Capture new skill</Button></Link>} />
      <div className="grid gap-4 sm:grid-cols-4">
        <Stat label="Published skills" value={skills.data!.items.length - drafts.length} />
        <Stat label="Drafts to review" value={drafts.length} />
        <Stat label="Awaiting sign-off" value={review.data!.total} />
        <Stat label="Blocked for safety" value={blocked.data!.total} />
      </div>
      <div className="mt-8 grid gap-6 lg:grid-cols-2">
        <section>
          <h2 className="mb-3 font-semibold">Learners waiting for you</h2>
          {review.data!.items.length === 0 ? <Empty title="Nobody is waiting" hint="Sessions escalated to an instructor appear here." /> : (
            <div className="space-y-3">{review.data!.items.map((s) => <SignoffCard key={s.id} s={s} who={name(s.learner_id)} skill={title(s.skill_id)} onDone={review.reload} />)}</div>
          )}
          {blocked.data!.items.length > 0 && (
            <>
              <h3 className="mb-2 mt-6 text-sm font-semibold text-failed">Blocked for safety right now</h3>
              <Card className="divide-y divide-line">{blocked.data!.items.map((s) => (
                <div key={s.id} className="flex items-center justify-between gap-3 p-3 text-sm">
                  <span>{name(s.learner_id)} · {title(s.skill_id)}</span><span className="font-mono text-xs text-muted">{s.current_step}</span>
                </div>))}</Card>
            </>
          )}
        </section>
        <section>
          <h2 className="mb-3 font-semibold">Drafts needing review</h2>
          {drafts.length === 0 ? <Empty title="No drafts" hint="Skills extracted from videos land here before publication." /> : (
            <Card className="divide-y divide-line">{drafts.map((s) => (
              <Link key={s.id} to={`/app/skills/${s.id}/review`} className="flex items-center justify-between gap-3 p-4 hover:bg-surface-2">
                <div><p className="text-sm font-medium">{s.title}</p><p className="text-xs text-muted">created {fmtDate(s.created_at)}</p></div>
                <Badge tone="uncertain">review</Badge>
              </Link>))}</Card>
          )}
        </section>
      </div>
    </>
  );
}

function SignoffCard({ s, who, skill, onDone }: { s: LearningSession; who: string; skill: string; onDone: () => void }) {
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState<boolean | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const act = async (approved: boolean) => {
    setBusy(approved);
    setErr(null);
    try {
      await api(`/sessions/${s.id}/signoff`, { method: "POST", json: { approved, comment } });
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  return (
    <Card className="p-4">
      <p className="text-sm font-medium">{who} · {skill}</p>
      <p className="mt-0.5 text-xs text-muted">Step <span className="font-mono">{s.current_step}</span> · {s.mode}</p>
      <input className={`${inputCls} mt-3`} placeholder="What you checked in person" value={comment} onChange={(e) => setComment(e.target.value)} />
      <div className="mt-3 flex gap-2">
        <Button busy={busy === true} disabled={!comment.trim()} onClick={() => act(true)}>Sign off step</Button>
        <Button variant="secondary" busy={busy === false} onClick={() => act(false)}>Reject</Button>
      </div>
      <p className="mt-2 text-xs text-muted">Sign-offs are recorded as instructor-verified, not camera-verified, and appear in the learner's report.</p>
      {err && <p className="mt-2 text-xs text-failed">{err}</p>}
    </Card>
  );
}

export function Capture() {
  const nav = useNavigate();
  const caps = useApi<Capabilities>("/system/capabilities");
  const videos = useApi<Page<Video>>("/videos?limit=50");
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const upload = async () => {
    if (!file) return;
    setBusy(true);
    setErr(null);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("title", title || file.name);
    fd.append("consent_confirmed", String(consent));
    try {
      await api<Video>("/videos/upload", { method: "POST", body: fd });
      setFile(null);
      setTitle("");
      setConsent(false);
      videos.reload();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader title="Capture a skill" subtitle="Upload a demonstration. SkillOS extracts a draft skill graph for you to review." />
      {caps.data && (!caps.data.ai || !caps.data.ffmpeg) && (
        <div className="mb-5 rounded-lg border border-uncertain/40 bg-uncertain-soft p-4 text-sm text-uncertain">
          <p className="font-semibold">Extraction is not fully configured on this server</p>
          <ul className="mt-1 list-disc pl-5">
            {!caps.data.ai && (caps.data.ai_provider === "hf"
              ? <li>AI is off: set <span className="font-mono">HF_TOKEN</span> and <span className="font-mono">SKILLOS_HF_MODEL</span>.</li>
              : <li>AI is off: set <span className="font-mono">OPENAI_API_KEY</span> and <span className="font-mono">OPENAI_MODEL</span>.</li>)}
            {!caps.data.ffmpeg && <li>FFmpeg is not installed (it is included in the Docker image).</li>}
          </ul>
          <p className="mt-1">You can still upload videos now and run extraction later.</p>
        </div>
      )}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,420px)_1fr]">
        <Card className="space-y-4 p-5">
          <Field label="Demonstration video" hint="MP4, MOV or WebM, up to 500 MB. Film the work area closely and narrate what you do.">
            <input type="file" accept="video/mp4,video/quicktime,video/webm" className="block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-accent-soft file:px-3 file:py-2 file:text-accent"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </Field>
          <Field label="Title"><input className={inputCls} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Installing a 12 V lighting kit" /></Field>
          <label className="flex items-start gap-3 text-sm">
            <input type="checkbox" className="mt-0.5 h-4 w-4 accent-accent" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            Everyone who appears in or is heard in this video has consented to it being recorded and processed.
          </label>
          {err && <ErrorBox message={err} />}
          <Button className="w-full" disabled={!file || !consent} busy={busy} onClick={upload}>Upload</Button>
        </Card>
        <section>
          <h2 className="mb-3 font-semibold">Videos</h2>
          {videos.loading ? <Loading /> : videos.error ? <ErrorBox message={videos.error} /> : videos.data!.items.length === 0 ? (
            <Empty title="No videos yet" hint="Uploaded demonstrations appear here." />
          ) : (
            <div className="space-y-3">{videos.data!.items.map((v) => <VideoRow key={v.id} v={v} aiReady={!!caps.data?.ai} onOpenDraft={(sid) => nav(`/app/skills/${sid}/review`)} />)}</div>
          )}
        </section>
      </div>
    </>
  );
}

function VideoRow({ v, aiReady, onOpenDraft }: { v: Video; aiReady: boolean; onOpenDraft: (skillId: string) => void }) {
  const jobs = useApi<Job[]>(`/videos/${v.id}/processing-status`);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const job = jobs.data?.[0];
  const running = job && (job.status === "queued" || job.status === "running");
  const timer = useRef<ReturnType<typeof setInterval>>(undefined);

  useEffect(() => {
    if (!running) return;
    timer.current = setInterval(jobs.reload, 2500);
    return () => clearInterval(timer.current);
  }, [running, jobs.reload]);

  const extract = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api(`/extraction/${v.id}`, { method: "POST" });
      jobs.reload();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const skillId = job?.result?.skill_id as string | undefined;
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0"><p className="truncate text-sm font-medium">{v.title}</p>
          <p className="text-xs text-muted">{(v.size_bytes / 1e6).toFixed(1)} MB · {v.duration_s ? `${Math.round(v.duration_s)} s · ` : ""}{fmtDate(v.created_at)}</p></div>
        {job?.status === "succeeded" && skillId ? <Button variant="secondary" onClick={() => onOpenDraft(skillId)}>Review draft</Button>
          : <Button disabled={!aiReady || !!running} busy={busy} onClick={extract}>{job?.status === "failed" ? "Retry extraction" : "Extract skill"}</Button>}
      </div>
      {job && (
        <div className="mt-3">
          <div className="flex justify-between text-xs"><span className="text-muted">{job.stage.replace(/_/g, " ")}</span>
            <Badge tone={job.status === "succeeded" ? "verified" : job.status === "failed" ? "failed" : "accent"}>{job.status}</Badge></div>
          {running && <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-2"><div className="h-full bg-accent transition-all" style={{ width: `${Math.round(job.progress * 100)}%` }} /></div>}
          {job.error && <p className="mt-2 text-xs text-failed">{job.error}</p>}
        </div>
      )}
      {err && <p className="mt-2 text-xs text-failed">{err}</p>}
    </Card>
  );
}
