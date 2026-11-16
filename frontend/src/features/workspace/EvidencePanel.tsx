import { useState, type RefObject } from "react";
import type { Method, Step } from "../../api/types";
import { Badge, Button, cx, inputCls } from "../../components/ui";
import type { CameraStatus } from "../../hooks/useCamera";

interface Props {
  step: Step;
  canSubmit: boolean;
  busy: string | null; // which action is running
  consent: boolean;
  aiAvailable: boolean;
  camera: { videoRef: RefObject<HTMLVideoElement | null>; status: CameraStatus; start: () => void };
  onCapture: (methodIndex: number) => void;
  onMeasure: (methodIndex: number, value: number, unit: string) => void;
  onConfirm: (methodIndex: number) => void;
}

export function CameraView({ camera, consent }: Pick<Props, "camera" | "consent">) {
  const msg: Partial<Record<CameraStatus, string>> = {
    denied: "Camera permission was denied. Allow it in your browser's site settings, then retry.",
    unavailable: "No camera found on this device.",
    error: "The camera could not be started.",
    starting: "Starting camera…",
  };
  return (
    <div className="relative aspect-video overflow-hidden rounded-xl bg-ink-950">
      <video ref={camera.videoRef} playsInline muted className={cx("h-full w-full object-cover", camera.status !== "live" && "invisible")} />
      {camera.status === "live" && (
        <span className="absolute left-3 top-3 inline-flex items-center gap-1.5 rounded-md bg-ink-900/80 px-2 py-1 text-xs font-medium text-white">
          <span className="h-2 w-2 rounded-full bg-failed" /> Camera on
        </span>
      )}
      {camera.status !== "live" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center text-sm text-ink-300">
          {!consent ? "Camera is off: no recording consent for this session." : msg[camera.status] ?? "Camera is off."}
          {consent && ["denied", "error", "idle"].includes(camera.status) && (
            <Button variant="secondary" onClick={camera.start}>Start camera</Button>
          )}
        </div>
      )}
    </div>
  );
}

export function EvidencePanel(p: Props) {
  const methods = p.step.validation.methods;
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">Evidence required</h3>
        <span className="text-xs text-muted">{p.step.validation.policy === "all" ? "All checks must pass" : "Any one check passes"}</span>
      </div>
      {methods.map((m, i) => <MethodRow key={i} index={i} method={m} {...p} />)}
    </div>
  );
}

function MethodRow({ index, method: m, ...p }: Props & { index: number; method: Method }) {
  const [value, setValue] = useState("");
  const disabled = !p.canSubmit || p.busy !== null;

  if (m.type === "visual") {
    const why = !p.consent ? "needs recording consent" : !p.aiAvailable ? "camera checking (AI) is not configured" : p.camera.status !== "live" ? "camera not running" : null;
    return (
      <div className="rounded-lg border border-line p-3">
        <div className="flex items-center justify-between gap-2"><Badge tone="accent">Camera check</Badge>{m.camera_guidance && <span className="text-xs text-muted">{m.camera_guidance}</span>}</div>
        <ul className="mt-2 space-y-1 text-sm">{m.criteria.map((c) => <li key={c.id} className="flex gap-2"><span className="text-muted">○</span>{c.description}</li>)}</ul>
        <Button className="mt-3 w-full" disabled={disabled || !!why} busy={p.busy === `cap${index}`} onClick={() => p.onCapture(index)}>Capture and check</Button>
        {why && <p className="mt-1.5 text-xs text-uncertain">Unavailable: {why}. You can ask for an instructor instead.</p>}
      </div>
    );
  }
  if (m.type === "measurement") {
    const range = [m.min, m.max].every((x) => x !== null) ? `${m.min} – ${m.max} ${m.unit}` : m.min !== null ? `≥ ${m.min} ${m.unit}` : `≤ ${m.max} ${m.unit}`;
    const n = Number(value);
    return (
      <form className="rounded-lg border border-line p-3" onSubmit={(e) => { e.preventDefault(); if (value !== "" && Number.isFinite(n)) p.onMeasure(index, n, m.unit); }}>
        <div className="flex items-center justify-between gap-2"><Badge tone="accent">Multimeter reading</Badge><span className="font-mono text-xs text-muted">expected {range}</span></div>
        <p className="mt-2 text-sm">{m.probe_points}</p>
        {m.negative_means_reversed_polarity && <p className="mt-1 text-xs text-muted">Enter the sign exactly as shown. A negative reading means polarity is reversed.</p>}
        <div className="mt-3 flex gap-2">
          <div className="relative flex-1">
            <input inputMode="decimal" aria-label={`Reading in ${m.unit}`} className={cx(inputCls, "pr-10 font-mono")} placeholder="e.g. 12.6"
              value={value} onChange={(e) => setValue(e.target.value.replace(/[^0-9.\-]/g, ""))} />
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-muted">{m.unit}</span>
          </div>
          <Button type="submit" disabled={disabled || value === "" || !Number.isFinite(n)} busy={p.busy === `meas${index}`}>Submit</Button>
        </div>
      </form>
    );
  }
  if (m.type === "learner_confirmation") {
    return (
      <div className="flex items-center justify-between gap-3 rounded-lg border border-line p-3">
        <div><Badge>Self-check</Badge><p className="mt-1.5 text-sm">{m.prompt}</p></div>
        <Button variant="secondary" disabled={disabled} busy={p.busy === `conf${index}`} onClick={() => p.onConfirm(index)}>Confirm</Button>
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-line p-3"><Badge>Instructor sign-off</Badge><p className="mt-1.5 text-sm">{m.prompt || "An instructor must check this step."}</p></div>
  );
}
