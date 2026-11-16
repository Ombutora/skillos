import type { SessionView } from "../../api/types";
import { cx } from "../../components/ui";

/** Progress through the steps. Branch steps not on the learner's path are shown dimmed. */
export function StepRail({ view }: { view: SessionView }) {
  const { session, skill } = view;
  const verified = new Set(session.verified_steps);
  const onPath = new Set(session.path);
  const done = skill.steps.filter((s) => verified.has(s.step_id)).length;
  const blocked = session.state === "BLOCKED_BY_SAFETY";

  return (
    <div>
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-muted">Procedure</h2>
        <span className="text-xs tabular-nums text-muted">{done} verified</span>
      </div>
      <ol className="space-y-1">
        {skill.steps.map((s) => {
          const current = s.step_id === session.current_step;
          const ok = verified.has(s.step_id);
          return (
            <li key={s.step_id}
              aria-current={current ? "step" : undefined}
              className={cx("flex items-start gap-2.5 rounded-lg px-2.5 py-2 text-sm",
                current && (blocked ? "bg-failed-soft" : "bg-accent-soft"),
                !current && !ok && !onPath.has(s.step_id) && "opacity-55")}>
              <span className={cx("mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold",
                ok ? "bg-verified text-white" : current ? (blocked ? "bg-failed text-white" : "bg-accent text-white live-dot") : "border border-line text-muted")}>
                {ok ? "✓" : current && blocked ? "!" : ""}
              </span>
              <span className={cx("min-w-0", current && "font-medium")}>
                {s.title}
                {s.critical && <span className="ml-1.5 text-[10px] font-semibold uppercase text-failed">safety</span>}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
