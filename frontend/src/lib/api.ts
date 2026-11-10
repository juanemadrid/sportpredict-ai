const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

let globalAuthToken: string | null = null;

export function setGlobalAuthToken(token: string | null) {
  globalAuthToken = token;
}

export function getGlobalAuthToken(): string | null {
  return globalAuthToken;
}

export async function apiFetch<T>(
  path: string,
  options?: RequestInit,
  userRole: string = "ADMIN",
  userPlan: string = "PRO",
  tokenOverride?: string | null
): Promise<T> {
  const token = tokenOverride !== undefined ? tokenOverride : globalAuthToken;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options?.headers as Record<string, string> || {}),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  // En desarrollo/inspección local también se adjuntan cabeceras de depuración
  if (userRole) {
    headers["X-User-Role"] = userRole;
  }
  if (userPlan) {
    headers["X-User-Plan"] = userPlan;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
    cache: "no-store",
  });

  if (!res.ok) {
    let errText = `HTTP ${res.status}`;
    try {
      const errJson = await res.json();
      errText = errJson.detail || JSON.stringify(errJson);
    } catch {
      // ignore
    }
    throw new Error(errText);
  }
  return res.json() as Promise<T>;
}
