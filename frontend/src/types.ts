export type ClaimStatus =
  | "queued"
  | "processing"
  | "needs_review"
  | "auto_approved"
  | "approved"
  | "rejected"
  | "failed";

export type FieldStatus = "pending" | "accepted" | "corrected";

export type FieldName = "policy_number" | "claimant_name" | "incident_date" | "amount" | "claim_type";

export interface ClaimField {
  name: FieldName;
  value: string | null;
  extracted_value: string | null;
  corrected_value: string | null;
  confidence: number;
  grounded: boolean;
  evidence: string | null;
  status: FieldStatus;
  reviewed_at: string | null;
}

export interface RuleEvidence {
  chunk_id: string;
  policy_number: string;
  section: string;
  group: string;
  excerpt: string;
  score: number | null;
}

export interface RuleOutcome {
  code: string;
  passed: boolean;
  message: string;
  evidence: RuleEvidence[];
}

export interface ClaimSummary {
  id: string;
  filename: string;
  status: ClaimStatus;
  policy_number: string | null;
  claimant_name: string | null;
  amount: string | null;
  claim_type: string | null;
  min_confidence: number | null;
  failed_rules: number;
  review_reasons: string[];
  created_at: string;
  processed_at: string | null;
}

export interface ClaimDetail extends ClaimSummary {
  extractor: string | null;
  text_method: string | null;
  ocr_confidence: number | null;
  page_count: number | null;
  description: string | null;
  error: string | null;
  decision_notes: string | null;
  decided_at: string | null;
  fields: ClaimField[];
  rules: RuleOutcome[];
}

export interface ClaimList {
  items: ClaimSummary[];
  total: number;
}

export interface Stats {
  counts: Record<ClaimStatus, number>;
  total: number;
}

export interface ClaimTypeOption {
  value: string;
  label: string;
}
