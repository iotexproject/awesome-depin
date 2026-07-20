import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { apiFetch } from "./api.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    apiFetch("/api/auth/me")
      .then((data) => active && setUser(data.user))
      .catch(() => active && setUser(null))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  const value = useMemo(
    () => ({
      user,
      loading,
      async login(payload) {
        const data = await apiFetch("/api/auth/login", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        setUser(data.user);
        return data.user;
      },
      async register(payload) {
        const data = await apiFetch("/api/auth/register", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        setUser(data.user);
        return data.user;
      },
      async logout() {
        await apiFetch("/api/auth/logout", { method: "POST" });
        setUser(null);
      },
      async refresh() {
        const data = await apiFetch("/api/auth/me");
        setUser(data.user);
        return data.user;
      },
    }),
    [loading, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
