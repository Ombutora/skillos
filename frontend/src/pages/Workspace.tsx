import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Capabilities, EvidenceResult, Report, SessionView } from "../api/types";
import { Badge, Button, Card, ErrorBox, Loading } from "../components/ui";
import { AssistPanel } from "../features/workspace/AssistPanel";
import { BriefingGate } from "../features/workspace/Briefing";
import { CameraView, EvidencePanel } from "../features/workspace/EvidencePanel";
import { StepRail } from "../features/workspace/StepRail";
import { StateBanner, ValidationPanel } from "../features/workspace/ValidationPanel";
import { useApi } from "../hooks/useApi";
import { useCamera } from "../hooks/useCamera";
import { useSessionSocket } from "../hooks/useSessionSocket";

const ACTIVE = new Set(["IN_PROGRESS", "AWAITING_EVIDENCE", "NEEDS_CORRECTION", "BLOCKED_BY_SAFETY"]);

export default function Workspace() {
  const { id } = useParams();
  const nav = useNavigate();
  const { data: view, error, loading, reload, setData } = useApi<SessionView>(`/sessions/${id}`);
  const { data: caps } = useApi<Capabilities>("/system/capabilities");
  const [busy, setBusy] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<EvidenceResult | null>(null);
  const live = useSessionSocket(id, () => void reload());

  const s = view?.session;
  const working = !!s && ACTIVE.has(s.state);
  const camera = useCamera(!!s?.recording_consent && working);

  const run = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    setActionErr(null);
    try {
      await fn();
      await reload();
    } catch (e) {
      setActionErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const submitResult = (r: EvidenceResult) => {
    setLastResult(r);
    setData((v) => (v ? { ...v, session: r.session, last_validation: r.validation } : v));
  };

  if (loading && !view) return <Loading />;
  if (error || !view || !s) return <ErrorBox message={error ?? "Session not found"} onRetry={reload} />;
  const step = view.current_step;

  const header = (
    <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
      <div className="min-w-0">
        <p className="text-xs font-medium uppercase tracking-wider text-muted">{s.mode === "assessment" ? "Independent assessment" : "Guided practice"}</p>
        <h1 className="truncate text-xl font-semibold">{view.skill.title}</h1>
      </div>
      <div className="flex items-center gap-2">
        <Badge tone={live ? "verified" : "neutral"}>{live ? "Live" : "Offline: updates paused"}</Badge>
        <Badge>{s.state.replace(/_/g, " ").toLowerCase()}</Badge>
      </div>
    </div>
  );

  if (s.state === "CREATED") {
    return (<>{header}<Card className="mx-auto max-w-xl p-6 text-center">
      <p className="text-sm text-muted">Set up your training rig and tools before you start.</p>
      <Button className="mt-4" busy={busy === "start"} onClick={() => run("start", () => api(`/sessions/${id}/start`, { method: "POST" }))}>Start session</Button>
      {actionErr && <div className="mt-4"><ErrorBox message={actionErr} /></div>}
    </Card></>);
  }
  if (s.state === "PREPARING") {
    return (<>{header}<BriefingGate briefing={view.briefing} busy={busy === "ack"}
      onAccept={(consent) => run("ack", () => api(`/sessions/${id}/acknowledge`, { method: "POST", json: { safety_briefing_ack: true, recording_consent: consent } }))} />
      {actionErr && <div className="mx-auto mt-4 max-w-2xl"><ErrorBox message={actionErr} /></div>}</>);
  }
  if (s.state === "COMPLETED" || s.state === "ABANDONED") {
    return (<>{header}<Card className="mx-auto max-w-xl p-8 text-center">
      <p className="text-4xl">{s.state === "COMPLETED" ? "✓" : "—"}</p>
      <h2 className="mt-2 text-lg font-semibold">{s.state === "COMPLETED" ? "Procedure complete" : "Session abandoned"}</h2>
      <p className="mt-1 text-sm text-muted">The competency report is calculated from the evidence recorded in this session.</p>
      <Button className="mt-5" busy={busy === "report"} onClick={() => run("report", async () => {
        const r = await api<Report>(`/sessions/${id}/complete`, { method: "POST" });
        nav(`/app/reports/${r.id}`);
      })}>View competency report</Button>
      {actionErr && <div className="mt-4"><ErrorBox message={actionErr} /></div>}
    </Card></>);
  }

  const lastForStep = view.last_validation && step && view.last_validation.step_key === step.step_id ? view.last_validation : null;
  const lastOther = view.last_validation && !lastForStep ? view.last_validation : null;

  const capture = (mi: number) => run(`cap${mi}`, async () => {
    const blob = await camera.capture();
    if (!blob) throw new Error("Could not capture a frame. Is the camera running?");
    const fd = new FormData();
    fd.append("step_id", step!.step_id);
    fd.append("method_index", String(mi));
    fd.append("frame", blob, "frame.jpg");
    submitResult(await api<EvidenceResult>(`/sessions/${id}/observe`, { method: "POST", body: fd }));
  });
  const measure = (mi: number, value: number, unit: string) => run(`meas${mi}`, async () =>
    submitResult(await api<EvidenceResult>(`/sessions/${id}/evidence`, { method: "POST", json: { step_id: step!.step_id, items: [{ type: "measurement", method_index: mi, value, unit }] } })));
  const confirm = (mi: number) => run(`conf${mi}`, async () =>
    submitResult(await api<EvidenceResult>(`/sessions/${id}/evidence`, { method: "POST", json: { step_id: step!.step_id, items: [{ type: "learner_confirmation", method_index: mi, confirmed: true }] } })));

  return (
    <>
      {header}
      <div className="grid gap-5 lg:grid-cols-[220px_minmax(0,1fr)_320px]">
        <Card className="order-3 p-4 lg:order-1 lg:self-start"><StepRail view={view} /></Card>

        <div className="order-1 min-w-0 space-y-4 lg:order-2">
          <StateBanner state={s.state} />
          {step && (
            <Card className="p-5">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="accent">{step.kind.replace(/_/g, " ")}</Badge>
                {step.safety.critical && <Badge tone="failed">Safety-critical</Badge>}
                {step.required_tools.map((t) => <Badge key={t}>{t.replace(/_/g, " ")}</Badge>)}
              </div>
              <h2 className="mt-3 text-lg font-semibold">{step.title}</h2>
              {step.description && <p className="mt-1 text-sm text-muted">{step.description}</p>}
              <ol className="mt-4 list-decimal space-y-1.5 pl-5 text-sm">{step.instructions.map((i) => <li key={i}>{i}</li>)}</ol>
              {step.safety.requirements.length > 0 && (
                <div className="mt-4 rounded-lg bg-failed-soft p-3 text-sm text-failed">
                  <p className="font-semibold">Safety</p>
                  <ul className="mt-1 list-disc pl-5">{step.safety.requirements.map((r) => <li key={r}>{r}</li>)}</ul>
                </div>
              )}
              {step.reference_images.length > 0 && (
                <div className="mt-4 flex gap-2 overflow-x-auto">
                  {step.reference_images.map((src) => <img key={src} src={src} alt={`Reference: ${src.split("/").pop()?.replace(".svg", "").replace(/_/g, " ")}`} className="h-20 rounded-lg border border-line bg-surface-2 p-1" />)}
                </div>
              )}
            </Card>
          )}
          <CameraView camera={camera} consent={s.recording_consent} />
          {step && (
            <Card className="p-4">
              <EvidencePanel step={step} canSubmit={working} busy={busy} consent={s.recording_consent} aiAvailable={!!caps?.ai}
                camera={camera} onCapture={capture} onMeasure={measure} onConfirm={confirm} />
            </Card>
          )}
          {actionErr && <ErrorBox message={actionErr} />}
        </div>

        <div className="order-2 space-y-4 lg:order-3">
          <Card className="p-4">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted">Validation</h3>
            <ValidationPanel v={lastForStep} extra={lastResult} />
            {lastOther && lastOther.verdict === "VERIFIED" && <p className="mt-3 text-xs text-verified">Previous step verified: {lastOther.message}</p>}
          </Card>
          <Card className="p-4"><AssistPanel sessionId={s.id} mode={s.mode} disabled={!working} /></Card>
          <Card className="space-y-2 p-4">
            <Button variant="secondary" className="w-full" disabled={!working} busy={busy === "esc"}
              onClick={() => run("esc", () => api(`/sessions/${id}/escalate`, { method: "POST", json: { reason: "learner requested instructor" } }))}>
              Ask an instructor to check
            </Button>
            <Button variant="ghost" className="w-full" busy={busy === "abandon"}
              onClick={() => confirm_("Abandon this session? It will be recorded as incomplete.") && run("abandon", () => api(`/sessions/${id}/abandon`, { method: "POST" }))}>
              Abandon session
            </Button>
            <Link to="/app/skills" className="block text-center text-xs text-muted hover:text-text">Back to library</Link>
          </Card>
        </div>
      </div>
    </>
  );
}

const confirm_ = (msg: string) => window.confirm(msg);
