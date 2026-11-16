import type { EvidenceResult, SessionState, ValidationResult } from "../../api/types";
import { cx, VerdictBadge } from "../../components/ui";

const STATE_COPY: Partial<Record<SessionState, { tone: string; title: string; body: string }>> = {
  BLOCKED_BY_SAFETY: { tone: "border-failed bg-failed-soft text-failed", title: "Stopped for safety",
    body: "Correct the problem described below and submit new evidence. You cannot continue until this step is verified." },
  NEEDS_CORRECTION: { tone: "border-failed/40 bg-failed-soft text-failed", title: "Correction needed", body: "Fix the issue and submit evidence again." },
  AWAITING_EVIDENCE: { tone: "border-uncertain/40 bg-uncertain-soft text-uncertain", title: "Not enough evidence",
    body: "SkillOS could not confirm this step. Provide the missing or clearer evidence." },
  NEEDS_HUMAN_REVIEW: { tone: "border-uncertain/40 bg-uncertain-soft text-uncertain", title: "Waiting for an instructor",
    body: "An instructor has been asked to check this step. Updates appear here automatically." },
};

export function StateBanner({ state }: { state: SessionState }) {
  const c = STATE_COPY[state];
  if (!c) return null;
  return (
    <div role={state === "BLOCKED_BY_SAFETY" ? "alert" : "status"} className={cx("rounded-xl border-l-4 p-4", c.tone)}>
      <p className="font-semibold">{c.title}</p>
      <p className="mt-0.5 text-sm opacity-90">{c.body}</p>
    </div>
  );
}

export function ValidationPanel({ v, extra }: { v: ValidationResult | null; extra?: EvidenceResult | null }) {
  if (!v) return <p className="text-sm text-muted">No evidence submitted for this session yet.</p>;
  return (
    <div className="space-y-3" aria-live="polite">
      <div className="flex items-center justify-between gap-2">
        <VerdictBadge verdict={v.verdict} />
        {v.confidence !== null && <span className="font-mono text-xs text-muted">min confidence {v.confidence.toFixed(2)}</span>}
      </div>
      <p className={cx("text-sm", v.safety_violation && "font-semibold text-failed")}>{v.message}</p>
      <ul className="space-y-1.5 border-t border-line pt-3">
        {v.method_results.filter((m) => m.method_index >= 0).map((m) => (
          <li key={m.method_index} className="flex items-start gap-2 text-xs">
            <span className={cx("mt-0.5 h-2 w-2 shrink-0 rounded-full",
              m.verdict === "VERIFIED" ? "bg-verified" : m.verdict === "FAILED" ? "bg-failed" : "bg-uncertain")} />
            <span><span className="font-medium">{m.method_type.replace(/_/g, " ")}</span>: {m.message}</span>
          </li>
        ))}
      </ul>
      {extra?.observations && extra.validation.id === v.id && (
        <details className="text-xs text-muted">
          <summary className="cursor-pointer">What the camera check saw</summary>
          <ul className="mt-2 space-y-1">
            {extra.observations.map((o) => (
              <li key={o.criterion_id}><span className="font-mono">{o.criterion_id}</span>: {o.status} ({o.confidence.toFixed(2)}) {o.note}</li>
            ))}
          </ul>
          {extra.detections && extra.detections.length > 0 && (
            <p className="mt-2">Detector hints: {extra.detections.map((d) => `${d.label} ${d.confidence.toFixed(2)}`).join(", ")}</p>
          )}
        </details>
      )}
    </div>
  );
}
