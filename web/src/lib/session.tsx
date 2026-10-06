"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { api, type DemoUser, type Health } from "./api";

interface Session {
  users: DemoUser[];
  user: DemoUser | null;
  setUser: (email: string) => void;
  /** A bearer token for any demo user, from the dev identity provider (cached until shortly before expiry). */
  tokenFor: (email: string) => Promise<string>;
  health: Health | null;
  error: string | null;
}

const SessionContext = createContext<Session | null>(null);
const STORAGE_KEY = "clearance.user";
const DEFAULT_USER = "dan.kim@fernhill.test";

export function SessionProvider({ children }: { children: ReactNode }) {
  const [users, setUsers] = useState<DemoUser[]>([]);
  const [email, setEmail] = useState<string>(() => {
    if (typeof window === "undefined") return DEFAULT_USER;
    try {
      return window.localStorage.getItem(STORAGE_KEY) ?? DEFAULT_USER;
    } catch {
      return DEFAULT_USER; // storage unavailable
    }
  });
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const tokens = useRef(new Map<string, { token: string; expires: number }>());

  useEffect(() => {
    Promise.all([api.users(), api.health()])
      .then(([list, status]) => {
        setUsers(list);
        setHealth(status);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  const setUser = useCallback((next: string) => {
    setEmail(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // ignore
    }
  }, []);

  const tokenFor = useCallback(async (address: string) => {
    const cached = tokens.current.get(address);
    if (cached && cached.expires > Date.now() + 60_000) return cached.token;
    const issued = await api.token(address);
    tokens.current.set(address, { token: issued.id_token, expires: Date.now() + issued.expires_in * 1000 });
    return issued.id_token;
  }, []);

  const value = useMemo<Session>(
    () => ({
      users,
      user: users.find((u) => u.email === email) ?? null,
      setUser,
      tokenFor,
      health,
      error,
    }),
    [users, email, setUser, tokenFor, health, error],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession must be used inside SessionProvider");
  return session;
}
