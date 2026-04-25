"use client";

import { useEffect, useState } from "react";

export type UserRole = "admin" | "user" | "viewer";

interface AuthState {
  authenticated: boolean;
  role: UserRole;
  displayName: string;
  isAdmin: boolean;
  isViewer: boolean;
  /**
   * True for admin and user roles. False for viewer (strictly read-only).
   * Use this to gate write actions on individual leads (stage changes,
   * adding contacts, uploading lead documents, sending outreach, etc).
   */
  canEdit: boolean;
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
    isViewer: false,
    canEdit: false,
    loading: true,
  });

  useEffect(() => {
    const apply = (role: UserRole, displayName: string, authenticated: boolean) => ({
      authenticated,
      role,
      displayName,
      isAdmin: role === "admin",
      isViewer: role === "viewer",
      canEdit: role === "admin" || role === "user",
      loading: false,
    });

    // Check sessionStorage cache first
    const cached = sessionStorage.getItem("insure_auth");
    if (cached) {
      try {
        const parsed = JSON.parse(cached) as { role?: UserRole; displayName?: string; authenticated?: boolean };
        setState(apply(parsed.role ?? "user", parsed.displayName ?? "", parsed.authenticated ?? false));
        return;
      } catch {
        // stale cache, re-fetch
      }
    }

    fetch("/api/auth")
      .then((r) => r.json())
      .then((d) => {
        const auth = apply((d.role ?? "user") as UserRole, d.displayName ?? "", d.authenticated ?? false);
        setState(auth);
        sessionStorage.setItem(
          "insure_auth",
          JSON.stringify({ role: auth.role, displayName: auth.displayName, authenticated: auth.authenticated }),
        );
      })
      .catch(() => {
        setState((s) => ({ ...s, loading: false }));
      });
  }, []);

  return state;
}
