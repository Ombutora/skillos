import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import type { SkillDetail, SkillGraph, Step, ValidationReport, Version } from "../api/types";
import { Badge, Button, Card, cx, ErrorBox, Field, fmtDate, inputCls, Loading, PageHeader } from "../components/ui";
import { useApi } from "../hooks/useApi";

const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);
const warnKey = (w: { code: string; step_id: string | null }) => `${w.code}:${w.step_id}`;

export default function Review() {
  const { id } = useParams();
  const { data: skill, error, loading, reload } = useApi<SkillDetail>(`/skills/${id}`);
  const [versionId, setVersionId] = useState<string | null>(null);
  const [graph, setGraph] = useState<SkillGraph | null>(null);
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState<"flow" | "json">("flow");
  const [jsonText, setJsonText] = useState("");
  const [acks, setAcks] = useState<Set<string>>(new Set());
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: "ok" | "err"; text: string } | null>(null);

  const version: Version | undefined = useMemo(
    () => skill?.versions.find((v) => v.id === versionId) ?? skill?.versions[skill.versions.length - 1], [skill, versionId]);

  useEffect(() => {
    if (!version) return;
    setGraph(structuredClone(version.graph));
    setReport(version.validation_report);
    setJsonText(JSON.stringify(version.graph, null, 2));
    setAcks(new Set());
    setSelected(version.graph.entry_step);
  }, [version]);

  const dirty = !!graph && !!version && JSON.stringify(graph) !== JSON.stringify(version.graph);

  // live re-validation of the working copy
  useEffect(() => {
    if (!graph || !dirty) return;
    const t = setTimeout(() => {
      api<ValidationReport>("/skills/validate", { method: "POST", json: { graph } }).then(setReport).catch(() => undefined);
    }, 500);
    return () => clearTimeout(t);
  }, [graph, dirty]);

  if (loading) return <Loading />;
  if (error || !skill || !version || !graph) return <ErrorBox message={error ?? "Not found"} onRetry={reload} />;

  const step = graph.steps.find((s) => s.step_id === selected) ?? null;
  const issuesFor = (sid: string) => [...(report?.errors ?? []), ...(report?.warnings ?? [])].filter((i) => i.step_id === sid);
  const updateStep = (patch: Partial<Step>) =>
    setGraph((g) => g && { ...g, steps: g.steps.map((s) => (s.step_id === selected ? { ...s, ...patch } : s)) });

  const act = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setMsg(null);
    try {
      await fn();
    } catch (e) {
      setMsg({ tone: "err", text: (e as Error).message });
    } finally {
      setBusy(null);
    }
  };
  const save = () => act("save", async () => {
    const v = await api<Version>(`/skills/${skill.id}`, { method: "PUT", json: { graph, change_note: note || "Expert edit" } });
    await reload();
    setVersionId(v.id);
    setNote("");
    setMsg({ tone: "ok", text: `Saved as version ${v.version_number}.` });
  });
  const publish = () => act("publish", async () => {
    const v = await api<Version>(`/skills/${skill.id}/publish?version_id=${version.id}`, { method: "POST", json: { acknowledged_warnings: [...acks], comment: note } });
    await reload();
    setVersionId(v.id);
    setMsg({ tone: "ok", text: `Version ${v.version_number} is published and available to learners.` });
  });
  const applyJson = () => {
    try {
      setGraph(JSON.parse(jsonText));
      setMsg(null);
    } catch {
      setMsg({ tone: "err", text: "The JSON is not valid." });
    }
  };

  const warnings = report?.warnings ?? [];
  const canPublish = version.status !== "published" && !dirty && report?.ok && warnings.every((w) => acks.has(warnKey(w)));
  const origin = graph.provenance?.origin;

  return (
    <>
      <PageHeader title={`Review: ${skill.title}`}
        subtitle={<>{origin === "extracted" ? "Generated from a demonstration video. Check every step against the source." : "Authored procedure."} Published skills are never edited in place. Changes create a new version.</>}
        actions={
          <select className={cx(inputCls, "w-auto")} value={version.id} onChange={(e) => setVersionId(e.target.value)} aria-label="Version">
            {skill.versions.map((v) => <option key={v.id} value={v.id}>v{v.version_number} · {v.status}</option>)}
          </select>
        } />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-4">
          <div className="flex gap-1 rounded-lg bg-surface p-1 text-sm ring-1 ring-line w-fit">
            {(["flow", "json"] as const).map((t) => (
              <button key={t} onClick={() => { setTab(t); if (t === "json") setJsonText(JSON.stringify(graph, null, 2)); }}
                className={cx("rounded-md px-3 py-1.5", tab === t ? "bg-ink-900 text-white" : "text-muted hover:text-text")}>{t === "flow" ? "Graph" : "JSON"}</button>
            ))}
          </div>

          {tab === "flow" ? (
            <ol className="space-y-2">
              {graph.steps.map((s, i) => {
                const issues = issuesFor(s.step_id);
                return (
                  <li key={s.step_id}>
                    <button onClick={() => setSelected(s.step_id)}
                      className={cx("w-full rounded-xl border bg-surface p-4 text-left transition",
                        selected === s.step_id ? "border-accent ring-2 ring-accent/20" : "border-line hover:border-ink-400")}>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs text-muted">{String(i + 1).padStart(2, "0")}</span>
                        <span className="font-medium">{s.title}</span>
                        {s.step_id === graph.entry_step && <Badge tone="accent">entry</Badge>}
                        {s.terminal && <Badge>end</Badge>}
                        {s.safety.critical && <Badge tone="failed">safety-critical</Badge>}
                        {s.confidence !== null && <Badge tone={s.confidence < 0.6 ? "uncertain" : "neutral"}>conf {s.confidence.toFixed(2)}</Badge>}
                        {issues.some((x) => x.severity === "error") && <Badge tone="failed">{issues.filter((x) => x.severity === "error").length} error</Badge>}
                        {issues.some((x) => x.severity === "warning") && <Badge tone="uncertain">{issues.filter((x) => x.severity === "warning").length} warning</Badge>}
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1.5 text-xs text-muted">
                        <span>checks: {s.validation.methods.map((m) => m.type.replace(/_/g, " ")).join(" + ")}</span>
                        {s.transitions.map((t, k) => (
                          <span key={k} className={cx("rounded px-1.5 font-mono", t.condition.type === "verified" || t.condition.type === "always" ? "bg-surface-2" : "bg-uncertain-soft text-uncertain")}>
                            → {t.to}{t.condition.type !== "verified" ? ` [${t.condition.type}${t.condition.value != null ? ` ${t.condition.value}` : ""}]` : ""}
                          </span>
                        ))}
                      </div>
                    </button>
                  </li>
                );
              })}
            </ol>
          ) : (
            <Card className="p-4">
              <textarea className={cx(inputCls, "h-[60vh] font-mono text-xs")} spellCheck={false} value={jsonText} onChange={(e) => setJsonText(e.target.value)} aria-label="Skill graph JSON" />
              <Button className="mt-3" variant="secondary" onClick={applyJson}>Apply JSON</Button>
            </Card>
          )}
        </div>

        <div className="space-y-4 xl:sticky xl:top-6 xl:self-start">
          <Card className="p-4">
            <div className="flex items-center justify-between"><h2 className="text-sm font-semibold">Publish gate</h2>
              <Badge tone={report?.ok ? "verified" : "failed"}>{report?.ok ? "no errors" : `${report?.errors.length ?? 0} errors`}</Badge></div>
            {report && report.errors.length > 0 && (
              <ul className="mt-3 space-y-1.5 text-xs">{report.errors.map((e, i) => (
                <li key={i} className="text-failed"><button className="text-left hover:underline" onClick={() => e.step_id && setSelected(e.step_id)}>
                  <span className="font-mono">{e.step_id ?? "skill"}</span>: {e.message}</button></li>))}</ul>
            )}
            {warnings.length > 0 && (
              <div className="mt-3 space-y-2 border-t border-line pt-3">
                <p className="text-xs font-medium">Acknowledge each warning after checking it:</p>
                {warnings.map((w) => (
                  <label key={warnKey(w)} className="flex items-start gap-2 text-xs">
                    <input type="checkbox" className="mt-0.5 accent-accent" checked={acks.has(warnKey(w))}
                      onChange={(e) => setAcks((a) => { const n = new Set(a); if (e.target.checked) n.add(warnKey(w)); else n.delete(warnKey(w)); return n; })} />
                    <span className="text-uncertain"><span className="font-mono">{w.step_id}</span>: {w.message}</span>
                  </label>
                ))}
              </div>
            )}
            <Field label="Change note / approval comment"><input className={cx(inputCls, "mt-1")} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
            <div className="mt-3 flex gap-2">
              <Button variant="secondary" disabled={!dirty} busy={busy === "save"} onClick={save}>Save new version</Button>
              <Button disabled={!canPublish} busy={busy === "publish"} onClick={publish}>{version.status === "published" ? "Published" : "Approve & publish"}</Button>
            </div>
            {dirty && <p className="mt-2 text-xs text-muted">Unsaved changes. Save them as a new version before publishing.</p>}
            {version.approved_at && <p className="mt-2 text-xs text-muted">Approved {fmtDate(version.approved_at)}</p>}
            {msg && <p className={cx("mt-2 text-xs", msg.tone === "ok" ? "text-verified" : "text-failed")}>{msg.text}</p>}
          </Card>

          {step && tab === "flow" && <StepEditor step={step} onChange={updateStep} />}
        </div>
      </div>
    </>
  );
}

function StepEditor({ step, onChange }: { step: Step; onChange: (p: Partial<Step>) => void }) {
  const [methods, setMethods] = useState(JSON.stringify(step.validation, null, 2));
  const [methodErr, setMethodErr] = useState<string | null>(null);
  useEffect(() => { setMethods(JSON.stringify(step.validation, null, 2)); setMethodErr(null); }, [step.step_id, step.validation]);

  return (
    <Card className="space-y-3 p-4">
      <div className="flex items-center justify-between"><h2 className="text-sm font-semibold">Edit step</h2><span className="font-mono text-xs text-muted">{step.step_id}</span></div>
      <Field label="Title"><input className={inputCls} value={step.title} onChange={(e) => onChange({ title: e.target.value })} /></Field>
      <Field label="Instructions" hint="One per line."><textarea className={cx(inputCls, "h-28")} defaultValue={step.instructions.join("\n")} key={`i-${step.step_id}`}
        onBlur={(e) => onChange({ instructions: lines(e.target.value) })} /></Field>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="accent-accent" checked={step.safety.critical}
        onChange={(e) => onChange({ safety: { ...step.safety, critical: e.target.checked } })} /> Safety-critical</label>
      <Field label="Safety requirements" hint="One per line."><textarea className={cx(inputCls, "h-20")} defaultValue={step.safety.requirements.join("\n")} key={`s-${step.step_id}`}
        onBlur={(e) => onChange({ safety: { ...step.safety, requirements: lines(e.target.value) } })} /></Field>
      <Field label="Validation (JSON)" hint="Methods: visual, measurement, learner_confirmation, instructor_signoff.">
        <textarea className={cx(inputCls, "h-40 font-mono text-xs")} spellCheck={false} value={methods} onChange={(e) => setMethods(e.target.value)}
          onBlur={() => { try { onChange({ validation: JSON.parse(methods) }); setMethodErr(null); } catch { setMethodErr("Invalid JSON"); } }} />
      </Field>
      {methodErr && <p className="text-xs text-failed">{methodErr}</p>}
      {(step.evidence_refs.length > 0 || step.expert_annotations.length > 0) && (
        <div className="border-t border-line pt-3 text-xs">
          <p className="font-medium">Source evidence</p>
          {step.evidence_refs.map((r, i) => (
            <p key={i} className="mt-1 text-muted">Video {r.t_start?.toFixed(1)}s–{r.t_end?.toFixed(1)}s{r.transcript_excerpt && <>: “{r.transcript_excerpt.slice(0, 160)}”</>}</p>
          ))}
          {step.expert_annotations.map((a, i) => <p key={i} className="mt-1 text-uncertain">{a.text}</p>)}
          {step.expected_observations.length > 0 && <p className="mt-1 text-muted">Observed: {step.expected_observations.join("; ")}</p>}
        </div>
      )}
    </Card>
  );
}
