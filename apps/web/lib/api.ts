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
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  token?: string | null;
  signal?: AbortSignal;
};

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, token, signal } = options;

  // FormData carries its own multipart boundary in the Content-Type header, so
  // setting that header here would produce a boundary that does not match the
  // body and the server would reject it as malformed.
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;

  const headers: Record<string, string> = {};
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method,
      headers,
      body: requestBody(body, isForm),
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

function requestBody(body: unknown, isForm: boolean): BodyInit | undefined {
  if (body === undefined) return undefined;
  if (isForm) return body as FormData;
  return JSON.stringify(body);
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

// ------------------------------------------------------------------- catalog

export type LotStatus =
  | "draft"
  | "pending_approval"
  | "approved"
  | "live"
  | "paused"
  | "sold"
  | "withdrawn"
  | "expired";

export type Visibility = "public" | "private" | "unbranded";
export type ConditionGrade = "A" | "B" | "C";

export type PhotoKind =
  | "full_lot"
  | "front"
  | "back"
  | "label"
  | "size_spread"
  | "defect"
  | "packaging";

export type ManifestLine = { size: string; color: string; pieces: number };
export type ManifestLineOut = ManifestLine & { id: string };

export type LotPhoto = {
  id: string;
  file_key: string;
  kind: PhotoKind;
  sort_order: number;
  width: number | null;
  height: number | null;
  bytes_stored: number | null;
};

export type LotDefect = {
  id: string;
  issue: string;
  pieces_affected: number;
  photo_id: string | null;
};

export type Lot = {
  id: string;
  lot_code: string;
  brand_id: string;
  category_id: string;
  title: string;
  description: string | null;
  season: string | null;
  condition_grade: ConditionGrade;
  total_pieces: number;
  retail_price_per_piece_pkr: number;
  lot_price_pkr: number;
  min_order_pieces: number;
  stock_city: string;
  status: LotStatus;
  visibility: Visibility;
  expiry_date: string | null;
  available_until: string | null;
  // Derived server side, so the client never disagrees about a discount.
  price_per_piece_pkr: number;
  discount_percent: number;
  manifest_total: number;
  is_manifest_balanced: boolean;
};

export type LotDetail = Lot & {
  manifest_lines: ManifestLineOut[];
  photos: LotPhoto[];
  defects: LotDefect[];
  excluded_cities: string[];
};

export type Readiness = { ready: boolean; blockers: string[]; warnings: string[] };

/** A proposal from the extractor. Nothing has been saved yet. */
export type ManifestImport = {
  rows: ManifestLine[];
  total_pieces: number;
  declared_total: number | null;
  lot_total_pieces: number;
  matches_lot_total: boolean;
  confidence: number;
  warnings: string[];
  model: string;
  from_fixture: boolean;
  cost_usd: number;
};

export type QueueItem = {
  lot: Lot;
  risk_score: number;
  risk_band: "low" | "medium" | "high" | "unknown";
  findings: string[];
};

export type ApprovalEntry = {
  id: string;
  action: string;
  actor_user_id: string | null;
  actor_role: string;
  visibility_at_action: Visibility;
  note: string | null;
  created_at: string;
};

export type LotList = { items: Lot[]; total: number; limit: number; offset: number };

export const catalog = {
  listLots: (token: string, params: { status?: LotStatus; search?: string } = {}) => {
    const query = new URLSearchParams();
    if (params.status) query.set("status", params.status);
    if (params.search) query.set("search", params.search);
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return request<LotList>(`/lots${suffix}`, { token });
  },

  getLot: (token: string, lotId: string) => request<LotDetail>(`/lots/${lotId}`, { token }),

  readiness: (token: string, lotId: string) =>
    request<Readiness>(`/lots/${lotId}/readiness`, { token }),

  setManifest: (token: string, lotId: string, lines: ManifestLine[]) =>
    request<LotDetail>(`/lots/${lotId}/manifest`, { method: "PUT", token, body: { lines } }),

  importManifest: (token: string, lotId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<ManifestImport>(`/lots/${lotId}/manifest/import`, {
      method: "POST",
      token,
      body: form,
    });
  },

  addPhoto: (token: string, lotId: string, file: File, kind: PhotoKind) => {
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    return request<LotPhoto>(`/lots/${lotId}/photos`, { method: "POST", token, body: form });
  },

  removePhoto: (token: string, lotId: string, photoId: string) =>
    request<void>(`/lots/${lotId}/photos/${photoId}`, { method: "DELETE", token }),

  submit: (token: string, lotId: string) =>
    request<LotDetail>(`/lots/${lotId}/submit`, { method: "POST", token }),

  approve: (
    token: string,
    lotId: string,
    body: { note?: string | null; visibility?: Visibility | null; publish?: boolean } = {},
  ) => request<LotDetail>(`/lots/${lotId}/approve`, { method: "POST", token, body }),

  reject: (token: string, lotId: string, note: string) =>
    request<LotDetail>(`/lots/${lotId}/reject`, { method: "POST", token, body: { note } }),

  pause: (token: string, lotId: string) =>
    request<LotDetail>(`/lots/${lotId}/pause`, { method: "POST", token, body: { note: null } }),

  resume: (token: string, lotId: string) =>
    request<LotDetail>(`/lots/${lotId}/resume`, { method: "POST", token }),

  withdraw: (token: string, lotId: string) =>
    request<LotDetail>(`/lots/${lotId}/withdraw`, { method: "POST", token, body: { note: null } }),

  setVisibility: (token: string, lotId: string, visibility: Visibility) =>
    request<LotDetail>(`/lots/${lotId}/visibility`, { method: "PUT", token, body: { visibility } }),

  approvalTrail: (token: string, lotId: string) =>
    request<ApprovalEntry[]>(`/lots/${lotId}/approvals`, { token }),

  queue: (token: string) => request<QueueItem[]>("/lots/queue", { token }),
};
