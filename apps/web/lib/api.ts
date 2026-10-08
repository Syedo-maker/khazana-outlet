/**
 * The only place the browser talks to the API.
 *
 * Every call goes through `request`, so error shape, the bearer token and the
 * network failure message are handled once. A component never calls `fetch`.
 */

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/** The error shape the API returns from its own handler. */
export type ApiErrorBody = { code: string; message: string };

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }

  /** True when signing in again is the right recovery, not a retry. */
  get needsSignIn(): boolean {
    return this.status === 401;
  }
}

type RequestOptions = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  token?: string | null;
  signal?: AbortSignal;
};

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, token, signal } = options;

  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
      credentials: "omit",
    });
  } catch (cause) {
    // A network failure is not an API error and must not be reported as one.
    // On a patchy mobile connection this is the common case, so it gets its
    // own message rather than "something went wrong".
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError(0, "network", "Could not reach the server.");
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const parsed: unknown = text ? safeJson(text) : null;

  if (!response.ok) {
    const detail = extractError(parsed);
    throw new ApiError(response.status, detail.code, detail.message);
  }

  return parsed as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

/**
 * Pull a message out of whatever the server sent.
 *
 * FastAPI wraps some errors in `detail` and the application handler returns
 * `{code, message}` directly, so both shapes are handled rather than letting
 * a user see "[object Object]".
 */
function extractError(parsed: unknown): ApiErrorBody {
  if (parsed && typeof parsed === "object") {
    const record = parsed as Record<string, unknown>;

    if (typeof record.message === "string") {
      return {
        code: typeof record.code === "string" ? record.code : "error",
        message: record.message,
      };
    }

    const detail = record.detail;
    if (detail && typeof detail === "object") {
      const inner = detail as Record<string, unknown>;
      if (typeof inner.message === "string") {
        return {
          code: typeof inner.code === "string" ? inner.code : "error",
          message: inner.message,
        };
      }
    }
    if (typeof detail === "string") return { code: "error", message: detail };

    // Pydantic validation errors arrive as an array under detail.
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as Record<string, unknown>;
      if (typeof first.msg === "string") return { code: "validation", message: first.msg };
    }
  }
  return { code: "error", message: "Something went wrong." };
}

// ------------------------------------------------------------------ endpoints

export type TokenPair = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in_seconds: number;
};

export type OtpRequestResult = {
  sent: boolean;
  dev_code: string | null;
  message: string;
};

export type Me = {
  user: {
    id: string;
    phone: string;
    full_name: string;
    role: "brand" | "reseller" | "admin";
    email: string | null;
    preferred_language: string;
  };
  brand_ids: string[];
  is_admin: boolean;
};

export const api = {
  requestOtp: (phone: string) =>
    request<OtpRequestResult>("/auth/otp/request", {
      method: "POST",
      body: { phone },
    }),

  verifyOtp: (phone: string, code: string, fullName?: string) =>
    request<TokenPair>("/auth/otp/verify", {
      method: "POST",
      body: { phone, code, full_name: fullName ?? null },
    }),

  refresh: (refreshToken: string) =>
    request<TokenPair>("/auth/refresh", {
      method: "POST",
      body: { refresh_token: refreshToken },
    }),

  me: (token: string) => request<Me>("/auth/me", { token }),

  signOut: (token: string) => request<void>("/auth/logout", { method: "POST", token }),

  aiStatus: () =>
    request<{
      mode: string;
      default_model: string;
      bulk_model: string;
      daily_limit_usd: number;
      features: Record<string, boolean>;
    }>("/ai/status"),
};
