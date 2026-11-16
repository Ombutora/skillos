import { useState } from "react";
import { api } from "../../api/client";
import { Button, inputCls } from "../../components/ui";

interface Answer { q: string; source: string; answer: string; note?: string }

export function AssistPanel({ sessionId, mode, disabled }: { sessionId: string; mode: string; disabled: boolean }) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [items, setItems] = useState<Answer[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const ask = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api<Omit<Answer, "q">>(`/sessions/${sessionId}/assist`, { method: "POST", json: { question: q } });
      setItems((xs) => [...xs, { q, ...r }]);
      setQ("");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">Ask for help</h3>
      {mode === "assessment" && <p className="mt-1 text-xs text-uncertain">Assessment mode: asking for help is recorded and limits the result to Competent.</p>}
      <div className="mt-2 max-h-64 space-y-3 overflow-y-auto">
        {items.map((a, i) => (
          <div key={i} className="text-sm">
            <p className="font-medium">{a.q}</p>
            <p className="mt-1 whitespace-pre-line text-muted">{a.answer}</p>
            {a.source !== "ai" && <p className="mt-1 text-xs text-uncertain">{a.note ?? "Shown from the approved procedure text."}</p>}
          </div>
        ))}
      </div>
      <form className="mt-2 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (q.trim()) void ask(); }}>
        <input className={inputCls} placeholder="e.g. Which terminal is BAT+?" value={q} maxLength={1000}
          onChange={(e) => setQ(e.target.value)} disabled={disabled} aria-label="Question" />
        <Button type="submit" variant="secondary" disabled={disabled || !q.trim()} busy={busy}>Ask</Button>
      </form>
      {err && <p className="mt-1 text-xs text-failed">{err}</p>}
    </div>
  );
}
