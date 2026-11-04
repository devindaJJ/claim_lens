import type { ClaimStatus, FieldName } from "./types";

export const FIELD_LABELS: Record<FieldName, string> = {
  policy_number: "Policy number",
  claimant_name: "Claimant",
  incident_date: "Incident date",
  amount: "Amount claimed",
  claim_type: "Claim type",
};

export const STATUS_LABELS: Record<ClaimStatus, string> = {
  queued: "Queued",
  processing: "Processing",
  needs_review: "Needs review",
  auto_approved: "Auto-approved",
  approved: "Approved",
  rejected: "Rejected",
  failed: "Failed",
};

export const RULE_LABELS: Record<string, string> = {
  required_fields: "Required fields present",
  policy_found: "Policy on file",
  claimant_insured: "Claimant is a named insured",
  incident_in_period: "Incident within policy period",
  coverage_applies: "Claim type is covered",
  within_limit: "Amount within coverage limit",
  no_exclusion: "No exclusion applies",
};

const currency = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const dateFmt = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });
const dateTimeFmt = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

export function formatAmount(value: string | null): string {
  if (value === null || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? currency.format(n) : value;
}

export function formatDate(value: string | null): string {
  if (!value) return "—";
  const d = new Date(`${value}T00:00:00`);
  return Number.isNaN(d.getTime()) ? value : dateFmt.format(d);
}

export function formatDateTime(value: string | null): string {
  return value ? dateTimeFmt.format(new Date(value)) : "—";
}

export function formatFieldValue(name: FieldName, value: string | null, claimTypes: Record<string, string>): string {
  if (value === null || value === "") return "—";
  if (name === "amount") return formatAmount(value);
  if (name === "incident_date") return formatDate(value);
  if (name === "claim_type") return claimTypes[value] ?? value;
  return value;
}

export type ConfidenceLevel = "high" | "medium" | "low";

export function confidenceLevel(value: number, threshold = 0.8): ConfidenceLevel {
  if (value >= threshold) return "high";
  if (value >= 0.5) return "medium";
  return "low";
}

export const percent = (value: number): string => `${Math.round(value * 100)}%`;
