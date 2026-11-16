import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { Verdict } from "../api/types";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "ghost" | "danger";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-white hover:bg-accent-strong",
  secondary: "bg-surface text-text border border-line hover:bg-surface-2",
  ghost: "text-muted hover:text-text hover:bg-surface-2",
  danger: "bg-failed text-white hover:brightness-95",
};

export function Button({ variant = "primary", className, busy, children, ...p }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  return (
    <button
      {...p}
      disabled={p.disabled || busy}
      className={cx("inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition",
        "disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        VARIANTS[variant], className)}
    >
      {busy && <Spinner className="h-3.5 w-3.5" />}
      {children}
    </button>
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cx("rounded-xl border border-line bg-surface", className)}>{children}</div>;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
    </div>
  );
}

export function Spinner({ className = "h-5 w-5" }: { className?: string }) {
  return <span role="status" aria-label="Loading" className={cx("inline-block animate-spin rounded-full border-2 border-current border-r-transparent", className)} />;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="flex items-center gap-3 py-12 text-sm text-muted justify-center"><Spinner />{label}</div>;
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start justify-between gap-4 rounded-lg border border-failed/30 bg-failed-soft p-4 text-sm text-failed">
      <span>{message}</span>
      {onRetry && <button onClick={onRetry} className="font-medium underline">Retry</button>}
    </div>
  );
}

export function Empty({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line bg-surface px-6 py-12 text-center">
      <p className="font-medium">{title}</p>
      {hint && <p className="mt-1 text-sm text-muted">{hint}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

const VERDICT_STYLE: Record<Verdict, string> = {
  VERIFIED: "bg-verified-soft text-verified",
  UNCERTAIN: "bg-uncertain-soft text-uncertain",
  FAILED: "bg-failed-soft text-failed",
};
const VERDICT_ICON: Record<Verdict, string> = { VERIFIED: "✓", UNCERTAIN: "?", FAILED: "✕" };

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-semibold tracking-wide", VERDICT_STYLE[verdict])}>
      <span aria-hidden>{VERDICT_ICON[verdict]}</span>{verdict}
    </span>
  );
}

export function Badge({ tone = "neutral", children }: { tone?: "neutral" | "accent" | "verified" | "uncertain" | "failed"; children: ReactNode }) {
  const t = {
    neutral: "bg-surface-2 text-muted border border-line",
    accent: "bg-accent-soft text-accent",
    verified: "bg-verified-soft text-verified",
    uncertain: "bg-uncertain-soft text-uncertain",
    failed: "bg-failed-soft text-failed",
  }[tone];
  return <span className={cx("inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium", t)}>{children}</span>;
}

export const LEVEL_TONE: Record<string, "neutral" | "accent" | "verified" | "uncertain" | "failed"> = {
  NOVICE: "neutral", DEVELOPING: "uncertain", COMPETENT: "accent", PROFICIENT: "verified", EXPERT: "verified",
};

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

export const inputCls = "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20";

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <Card className="p-4">
      <p className="text-xs font-medium uppercase tracking-wider text-muted">{label}</p>
      <p className="mt-2 text-2xl font-semibold tabular-nums">{value}</p>
      {sub && <p className="mt-1 text-xs text-muted">{sub}</p>}
    </Card>
  );
}

export function pct(v: number | null | undefined) {
  return v === null || v === undefined ? "n/a" : `${Math.round(v * 100)}%`;
}

export function fmtDate(s: string | null) {
  return s ? new Date(s).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—";
}
