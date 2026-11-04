import type { ClaimDetail, ClaimList, ClaimStatus, ClaimSummary, ClaimTypeOption, FieldName, Stats } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, message);
  }
  return response.json() as Promise<T>;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  listClaims(statuses: ClaimStatus[] = [], limit = 100): Promise<ClaimList> {
    const params = new URLSearchParams({ limit: String(limit) });
    statuses.forEach((s) => params.append("status", s));
    return request(`/api/claims?${params}`);
  },
  stats: (): Promise<Stats> => request("/api/claims/stats"),
  getClaim: (id: string): Promise<ClaimDetail> => request(`/api/claims/${id}`),
  documentUrl: (id: string): string => `/api/claims/${id}/document`,
  claimTypes: (): Promise<ClaimTypeOption[]> => request("/api/claim-types"),

  upload(file: File): Promise<ClaimSummary> {
    const form = new FormData();
    form.append("file", file);
    return request("/api/claims", { method: "POST", body: form });
  },
  reviewField(id: string, name: FieldName, action: "accept" | "correct", value?: string): Promise<ClaimDetail> {
    return request(`/api/claims/${id}/fields/${name}`, json("PATCH", { action, value }));
  },
  decide(id: string, decision: "approve" | "reject", notes: string): Promise<ClaimDetail> {
    return request(`/api/claims/${id}/decision`, json("POST", { decision, notes: notes || null }));
  },
  reprocess: (id: string): Promise<ClaimSummary> => request(`/api/claims/${id}/reprocess`, { method: "POST" }),
};
