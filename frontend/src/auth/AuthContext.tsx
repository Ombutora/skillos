import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { accessToken, api, saveTokens } from "../api/client";
import type { User } from "../api/types";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  register: (body: { email: string; password: string; full_name: string; organization_name: string }) => Promise<User>;
  logout: () => void;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(!!accessToken());

  const loadMe = useCallback(async () => {
    const me = await api<User>("/auth/me");
    setUser(me);
    return me;
  }, []);

  useEffect(() => {
    if (!accessToken()) return;
    loadMe().catch(() => saveTokens(null)).finally(() => setLoading(false));
  }, [loadMe]);

  const login = async (email: string, password: string) => {
    saveTokens(await api("/auth/login", { method: "POST", json: { email, password } }));
    return loadMe();
  };
  const register: AuthState["register"] = async (body) => {
    saveTokens(await api("/auth/register", { method: "POST", json: body }));
    return loadMe();
  };
  const logout = () => {
    saveTokens(null);
    setUser(null);
  };

  return <Ctx.Provider value={{ user, loading, login, register, logout }}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}

export const homeFor = (u: User) => (u.role === "learner" ? "/app" : u.role === "expert" ? "/app/expert" : "/app/admin");
