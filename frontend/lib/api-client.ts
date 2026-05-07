export type ApiEnvelope<T> = {
  success: boolean;
  message?: string | null;
  data?: T;
  errors?: { code: string; message: string; detail?: string | null }[];
};

function getCorrelationId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `cid-${Date.now()}`;
}

export function getApiBaseUrl(): string {
  let base = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "";
  if (!base) {
    throw new Error("NEXT_PUBLIC_API_BASE_URL is not configured.");
  }
  // Paths already start with `/api/v1/...`; strip duplicate prefix if env includes it.
  base = base.replace(/\/api\/v1$/i, "");
  return base;
}

/**
 * Extracts a human-readable error message from a FastAPI error response body.
 *
 * FastAPI can return `detail` as:
 *  - a plain string  → use directly
 *  - an object with a `message` key  → {"code": "...", "message": "..."}
 *  - an array of Pydantic validation errors → [{loc, msg, type}, ...]
 *
 * Calling String() on an object or array produces "[object Object]", which is
 * the "[object Object]" bug visible in the UI.
 */
export function extractErrorMessage(body: unknown, status: number): string {
  if (typeof body === "object" && body !== null && "detail" in body) {
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      // Pydantic v2 validation error list: [{loc, msg, type, ...}]
      const msgs = detail
        .map((e) => (typeof e === "object" && e !== null && "msg" in e ? String((e as { msg: unknown }).msg) : null))
        .filter(Boolean);
      if (msgs.length > 0) return msgs.join("; ");
    }
    if (typeof detail === "object" && detail !== null && "message" in detail) {
      return String((detail as { message: unknown }).message);
    }
  }
  return `Request failed (${status})`;
}

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<ApiEnvelope<T>> {
  const correlationId = getCorrelationId();
  const url = `${getApiBaseUrl()}${path.startsWith("/") ? path : `/${path}`}`;
  const res = await fetch(url, {
    ...init,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-Correlation-ID": correlationId,
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    throw new Error(`Non-JSON response (${res.status}) from ${url}`);
  }
  if (!res.ok) {
    const msg = extractErrorMessage(body, res.status);
    throw new Error(msg);
  }
  return body as ApiEnvelope<T>;
}
