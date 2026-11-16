import { useState } from "react";
import type { Briefing as B } from "../../api/types";
import { Button, Card } from "../../components/ui";

export function BriefingGate({ briefing, onAccept, busy }: { briefing: B; onAccept: (consent: boolean) => void; busy: boolean }) {
  const [ack, setAck] = useState(false);
  const [consent, setConsent] = useState(false);
  return (
    <Card className="mx-auto max-w-2xl p-6">
      <h2 className="text-lg font-semibold">Safety briefing</h2>
      <p className="mt-2 rounded-lg bg-failed-soft p-3 text-sm font-medium text-failed">{briefing.scope}</p>
      {briefing.hazards.length > 0 && (
        <div className="mt-4">
          <h3 className="text-sm font-semibold">Hazards in this procedure</h3>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {briefing.hazards.map((h) => <span key={h} className="rounded-md bg-surface-2 px-2 py-1 text-xs">{h.replace(/_/g, " ")}</span>)}
          </div>
        </div>
      )}
      {briefing.requirements.length > 0 && (
        <ul className="mt-4 list-disc space-y-1 pl-5 text-sm">
          {briefing.requirements.map((r) => <li key={r}>{r}</li>)}
        </ul>
      )}
      <div className="mt-6 space-y-3 border-t border-line pt-5 text-sm">
        <label className="flex items-start gap-3">
          <input type="checkbox" className="mt-0.5 h-4 w-4 accent-accent" checked={ack} onChange={(e) => setAck(e.target.checked)} />
          <span>I have read the safety briefing and I am working on an isolated low-voltage training rig.</span>
        </label>
        <label className="flex items-start gap-3">
          <input type="checkbox" className="mt-0.5 h-4 w-4 accent-accent" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          <span>
            I consent to SkillOS using my camera to check my work. Frames I submit are stored with this session and can be
            seen by my instructors. <span className="text-muted">Without consent, camera-checked steps need an instructor instead.</span>
          </span>
        </label>
      </div>
      <Button className="mt-6 w-full" disabled={!ack} busy={busy} onClick={() => onAccept(consent)}>Begin procedure</Button>
    </Card>
  );
}
