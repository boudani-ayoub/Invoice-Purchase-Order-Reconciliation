"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { AUTH_EXPIRED_EVENT } from "@/constants/auth";
import { authAction, getSession } from "@/lib/api/auth";
import type { AuthSession } from "@/types/auth";

interface AuthContextValue {
  session: AuthSession | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
  selectOrganization: (organizationId: string) => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const revision = useRef(0);
  const refresh = useCallback(() => {
    const requestRevision = ++revision.current;
    return getSession()
      .then(
        (session) => {
          if (revision.current === requestRevision) {
            setSession(session);
            setError(null);
          }
        },
        () => {
          if (revision.current === requestRevision) {
            setSession(null);
            setError("Unable to check your session. Please try again.");
          }
        },
      )
      .finally(() => {
        if (revision.current === requestRevision) setLoading(false);
      });
  }, []);

  useEffect(() => {
    void refresh();
    const expired = () => {
      revision.current += 1;
      setSession(null);
      setLoading(false);
    };
    window.addEventListener(AUTH_EXPIRED_EVENT, expired);
    return () => {
      revision.current += 1;
      window.removeEventListener(AUTH_EXPIRED_EVENT, expired);
    };
  }, [refresh]);

  const logout = useCallback(async () => {
    await authAction("logout");
    revision.current += 1;
    setSession(null);
  }, []);
  const selectOrganization = useCallback(
    async (organizationId: string) => {
      await authAction("select-organization", {
        organization_id: organizationId,
      });
      await refresh();
    },
    [refresh],
  );

  return (
    <AuthContext.Provider
      value={{ session, loading, error, refresh, logout, selectOrganization }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("Authentication context is missing.");
  return value;
}
