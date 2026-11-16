import { useState } from "react";
import { NavLink, Navigate, Outlet, useLocation } from "react-router-dom";
import type { Role } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Logo } from "./Logo";
import { cx, Loading } from "./ui";

const NAV: { to: string; label: string; roles: Role[]; end?: boolean }[] = [
  { to: "/app", label: "Dashboard", roles: ["learner"], end: true },
  { to: "/app/expert", label: "Expert dashboard", roles: ["expert", "admin"], end: true },
  { to: "/app/skills", label: "Skill library", roles: ["learner", "expert", "admin"] },
  { to: "/app/capture", label: "Capture skill", roles: ["expert", "admin"] },
  { to: "/app/competency", label: "My competency", roles: ["learner"] },
  { to: "/app/org", label: "Organization", roles: ["expert", "admin"] },
  { to: "/app/admin", label: "Administration", roles: ["admin"] },
];

export function AppShell() {
  const { user, loading, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  if (loading) return <Loading label="Signing you in…" />;
  if (!user) return <Navigate to="/login" state={{ from: loc.pathname }} replace />;

  const links = NAV.filter((n) => n.roles.includes(user.role));
  const nav = (
    <nav className="flex flex-col gap-1">
      {links.map((n) => (
        <NavLink key={n.to} to={n.to} end={n.end} onClick={() => setOpen(false)}
          className={({ isActive }) => cx("rounded-lg px-3 py-2 text-sm transition",
            isActive ? "bg-ink-700 text-white" : "text-ink-300 hover:bg-ink-800 hover:text-white")}>
          {n.label}
        </NavLink>
      ))}
    </nav>
  );

  return (
    <div className="flex min-h-full">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col justify-between bg-ink-900 p-4 lg:flex">
        <div className="space-y-8"><div className="px-2 pt-1"><Logo dark /></div>{nav}</div>
        <UserBox name={user.full_name} role={user.role} onLogout={logout} />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between bg-ink-900 px-4 py-3 lg:hidden">
          <Logo dark />
          <button onClick={() => setOpen(!open)} aria-expanded={open} aria-label="Menu" className="rounded-md p-2 text-ink-300 hover:text-white">
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 7h16M4 12h16M4 17h16" /></svg>
          </button>
        </header>
        {open && <div className="space-y-4 bg-ink-900 p-4 lg:hidden">{nav}<UserBox name={user.full_name} role={user.role} onLogout={logout} /></div>}
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8"><Outlet /></main>
      </div>
    </div>
  );
}

function UserBox({ name, role, onLogout }: { name: string; role: string; onLogout: () => void }) {
  return (
    <div className="rounded-lg bg-ink-800 p-3">
      <p className="truncate text-sm font-medium text-white">{name}</p>
      <p className="text-xs capitalize text-ink-400">{role}</p>
      <button onClick={onLogout} className="mt-2 text-xs text-ink-300 hover:text-white">Sign out</button>
    </div>
  );
}

export function RequireRole({ roles, children }: { roles: Role[]; children: React.ReactNode }) {
  const { user } = useAuth();
  if (!user || !roles.includes(user.role)) return <Navigate to="/app" replace />;
  return <>{children}</>;
}
