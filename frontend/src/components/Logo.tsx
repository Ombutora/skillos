export function Logo({ dark = false }: { dark?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2 font-semibold tracking-tight">
      <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden>
        <rect width="32" height="32" rx="7" fill={dark ? "#1a2640" : "#0b1220"} />
        <path d="M8 21l5-10 4 7 2-3 4 6" stroke="#2f6bff" strokeWidth="2.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="23" cy="21" r="1.8" fill="#0e9f6e" />
      </svg>
      <span className={dark ? "text-white" : "text-text"}>SkillOS</span>
    </span>
  );
}
