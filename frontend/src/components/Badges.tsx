import { confidenceLevel, percent, STATUS_LABELS } from "../format";
import type { ClaimStatus } from "../types";

export function StatusBadge({ status }: { status: ClaimStatus }) {
  return (
    <span className={`badge badge--${status}`}>
      {(status === "processing" || status === "queued") && <span className="spinner" aria-hidden />}
      {STATUS_LABELS[status]}
    </span>
  );
}

export function ConfidenceMeter({ value, compact = false }: { value: number; compact?: boolean }) {
  const level = confidenceLevel(value);
  return (
    <span className={`confidence confidence--${level}`} title={`Confidence ${percent(value)}`}>
      <span className="confidence__track">
        <span className="confidence__fill" style={{ width: percent(value) }} />
      </span>
      {!compact && <span className="confidence__value">{percent(value)}</span>}
    </span>
  );
}
