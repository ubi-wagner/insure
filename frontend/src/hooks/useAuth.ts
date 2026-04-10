"use client";

import { useEffect, useState } from "react";

interface AuthState {
  authenticated: boolean;
  role: "admin" | "user";
  displayName: string;
  isAdmin: boolean;
  loading: boolean;
}

/**
 * Client-side auth hook. Calls GET /api/auth to read role from cookie.
 * Caches in sessionStorage for the tab lifetime to avoid re-fetching
 * on every navigation.
 */
export function useAuth(): AuthState {
  const [state, setState] = useState<AuthState>({
    authenticated: false,
    role: "user",
    displayName: "",
    isAdmin: false,
    loading: true,
  });

  useEffect(() => {
    // Check sessionStorage cache first
    const cached = sessionStorage.getItem("insure_auth");
    if (cached) {
      try {
        const parsed = JSON.parse(cached);
        setState({ ...parsed, loading: false, isAdmin: parsed.role === "admin" });
        return;
      } catch {
        // stale cache, re-fetch
      }
    }

    fetch("/api/auth")
      .then((r) => r.json())
      .then((d) => {
        const auth = {
          authenticated: d.authenticated ?? false,
          role: (d.role ?? "user") as "admin" | "user",
          displayName: d.displayName ?? "",
          isAdmin: d.role === "admin",
          loading: false,
        };
        setState(auth);
        sessionStorage.setItem("insure_auth", JSON.stringify(auth));
      })
      .catch(() => {
        setState((s) => ({ ...s, loading: false }));
      });
  }, []);

  return state;
}
