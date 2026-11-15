// Types come from schema.d.ts, generated from the backend's OpenAPI contract (npm run gen:types). Never hand-edit them.
import type { components } from "./schema";

export type S = components["schemas"];
export type BorrowerProfile = S["BorrowerProfile"];
export type Borrower = S["BorrowerOut"];
export type Case = S["CaseOut"];
export type Doc = S["DocumentOut"];
export type Investigation = S["InvestigationOut"];
export type Finding = S["FindingOut"];
export type Narrative = S["Narrative"];
export type Restructure = S["RestructureOut"];
export type RestructureInput = S["RestructureInput"];
export type Recommendations = S["RecommendationsOut"];
export type LoanOption = S["OptionOut"];
export type Proposal = S["ProposalOut"];
export type Application = S["ApplicationOut"];
export type LenderProduct = S["LenderProduct"];
export type Priority = Recommendations["priority"];

export type ApiErrorKind = "network" | "notFound" | "validation" | "conflict" | "forbidden" | "server";

export class ApiError extends Error {
  constructor(public kind: ApiErrorKind, message: string, public fields: Record<string, string> = {}) {
    super(message);
  }
}

/** A message that is safe to show: the server's own wording where it wrote one for people. */
export function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.kind === "network") return "Can't reach the LoanKart.ai server. Check that the backend is running, then try again.";
    return err.message;
  }
  return "Something went wrong. Please try again.";
}

const BASE = import.meta.env.VITE_API_BASE_URL ?? "";
/** Absolute URL for a backend path such as a PDF link. */
export const apiUrl = (path: string) => BASE + path;

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    const json = init?.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : undefined;
    res = await fetch(BASE + path, { ...init, headers: { ...json, ...init?.headers } });
  } catch {
    throw new ApiError("network", "network");
  }
  if (res.ok) return res.json() as Promise<T>;

  const body = await res.json().catch(() => ({}));
  const detail = body?.detail;
  const text = typeof detail === "string" ? detail : `HTTP ${res.status}`;
  if (res.status === 404) throw new ApiError("notFound", text);
  if (res.status === 409) throw new ApiError("conflict", text);
  if (res.status === 403) throw new ApiError("forbidden", text);
  if (res.status === 422 && Array.isArray(detail)) {
    // FastAPI 422: [{loc: ["body", field], msg}], or loc ["body"] for cross-field rules.
    const fields: Record<string, string> = {};
    for (const e of detail) fields[String(e.loc?.[e.loc.length - 1] ?? "body")] = e.msg;
    throw new ApiError("validation", detail.map((e: { msg: string }) => e.msg).join(" "), fields);
  }
  if (res.status === 422) throw new ApiError("validation", text);
  throw new ApiError("server", text);
}

const post = (data: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(data) });

export const api = {
  health: () => request<{ status: string }>("/health"),
  getDemo: () => request<Borrower>("/api/demo/borrower"),
  create: (p: BorrowerProfile) => request<Borrower>("/api/borrowers", post(p)),
  get: (id: string) => request<Borrower>(`/api/borrowers/${encodeURIComponent(id)}`),
  update: (id: string, p: BorrowerProfile) =>
    request<Borrower>(`/api/borrowers/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(p) }),
};
