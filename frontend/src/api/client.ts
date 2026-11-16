const BASE = "/api/v1";
const KEY = "skillos.tokens";

interface Tokens { access_token: string; refresh_token: string }

export class ApiError extends Error {
  constructor(public status: number, message: string, public detail: unknown) {
    super(message);
  }
}

// Tokens live in sessionStorage: they survive reloads but not a closed tab.
function load(): Tokens | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Tokens) : null;
  } catch {
    return null;
  }
}

export function saveTokens(t: Tokens | null) {
  try {
    if (t) sessionStorage.setItem(KEY, JSON.stringify(t));
    else sessionStorage.removeItem(KEY);
  } catch {
    /* storage unavailable: session lasts until reload */
  }
  memory = t;
}

let memory: Tokens | null = load();
export const accessToken = () => memory?.access_token ?? null;

function messageOf(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    const d = detail as { message?: string; msg?: string };
    if (d.message) return d.message;
    if (Array.isArray(detail)) return detail.map((e) => (e as { msg?: string }).msg ?? "").join("; ");
  }
  return fallback;
}

let refreshing: Promise<boolean> | null = null;
async function refresh(): Promise<boolean> {
  if (!memory?.refresh_token) return false;
  refreshing ??= fetch(`${BASE}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: memory.refresh_token }),
  })
    .then(async (r) => {
      if (!r.ok) return false;
      saveTokens(await r.json());
      return true;
    })
    .catch(() => false)
    .finally(() => (refreshing = null));
  return refreshing;
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}, retry = true): Promise<T> {
  const headers = new Headers(init.headers);
  if (memory) headers.set("Authorization", `Bearer ${memory.access_token}`);
  let body = init.body;
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.json);
  }
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers, body });
  } catch {
    throw new ApiError(0, "Can't reach the SkillOS server. Check your connection.", null);
  }
  if (res.status === 401 && retry && (await refresh())) return api<T>(path, init, false);
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = data?.detail ?? data;
    throw new ApiError(res.status, messageOf(detail, `Request failed (${res.status})`), detail);
  }
  return data as T;
}

export function wsUrl(path: string): string {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}${BASE}${path}?token=${encodeURIComponent(accessToken() ?? "")}`;
}
