import { useCallback } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ConfidenceMeter, StatusBadge } from "../components/Badges";
import { UploadButton } from "../components/UploadButton";
import { formatAmount, formatDateTime, STATUS_LABELS } from "../format";
import type { ClaimList, ClaimStatus, Stats } from "../types";
import { usePolling } from "../usePolling";

const FILTERS: { key: string; label: string; statuses: ClaimStatus[] }[] = [
  { key: "review", label: "Review queue", statuses: ["needs_review"] },
  { key: "auto", label: "Auto-approved", statuses: ["auto_approved"] },
  { key: "in-progress", label: "In progress", statuses: ["queued", "processing"] },
  { key: "decided", label: "Decided", statuses: ["approved", "rejected"] },
  { key: "failed", label: "Failed", statuses: ["failed"] },
  { key: "all", label: "All claims", statuses: [] },
];

const isActive = (s: ClaimStatus) => s === "queued" || s === "processing";

export function QueuePage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const filter = FILTERS.find((f) => f.key === params.get("view")) ?? FILTERS[0];

  const load = useCallback(async (): Promise<{ list: ClaimList; stats: Stats }> => {
    const [list, stats] = await Promise.all([api.listClaims(filter.statuses), api.stats()]);
    return { list, stats };
  }, [filter]);

  const { data: loaded, error, reload } = usePolling(
    load,
    (d) => d.stats.counts.queued + d.stats.counts.processing > 0,
    filter.key,
  );
  const data = loaded?.list;
  const stats = loaded?.stats;

  const count = (statuses: ClaimStatus[]) =>
    stats ? (statuses.length ? statuses.reduce((n, s) => n + stats.counts[s], 0) : stats.total) : null;

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1>Claims</h1>
          <p className="muted">Uploaded claim packets are extracted, checked against policy rules and routed here.</p>
        </div>
        <UploadButton onUploaded={() => void reload()} />
      </div>

      <nav className="tabs" aria-label="Claim filters">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            className={`tab${f.key === filter.key ? " tab--active" : ""}`}
            onClick={() => setParams(f.key === "review" ? {} : { view: f.key })}
          >
            {f.label}
            <span className="tab__count">{count(f.statuses) ?? "·"}</span>
          </button>
        ))}
      </nav>

      {error && <div className="alert alert--error">Could not load claims: {error}</div>}

      <div className="card table-card">
        <table className="table">
          <thead>
            <tr>
              <th>Document</th>
              <th>Claimant</th>
              <th>Policy</th>
              <th className="num">Amount</th>
              <th>Lowest confidence</th>
              <th>Checks</th>
              <th>Status</th>
              <th>Received</th>
            </tr>
          </thead>
          <tbody>
            {data?.items.map((claim) => (
              <tr key={claim.id} onClick={() => navigate(`/claims/${claim.id}`)} className="table__row">
                <td>
                  <Link to={`/claims/${claim.id}`} className="table__link" onClick={(e) => e.stopPropagation()}>
                    {claim.filename}
                  </Link>
                </td>
                <td>{claim.claimant_name ?? <span className="muted">—</span>}</td>
                <td className="mono">{claim.policy_number ?? <span className="muted">—</span>}</td>
                <td className="num">{formatAmount(claim.amount)}</td>
                <td>{claim.min_confidence !== null && !isActive(claim.status) ? <ConfidenceMeter value={claim.min_confidence} /> : <span className="muted">—</span>}</td>
                <td>
                  {isActive(claim.status) ? (
                    <span className="muted">—</span>
                  ) : claim.failed_rules > 0 ? (
                    <span className="tag tag--fail">{claim.failed_rules} failed</span>
                  ) : (
                    <span className="tag tag--pass">All passed</span>
                  )}
                </td>
                <td>
                  <StatusBadge status={claim.status} />
                </td>
                <td className="muted nowrap">{formatDateTime(claim.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data && data.items.length === 0 && (
          <div className="empty">
            <p>
              No claims {filter.statuses.length ? `with status “${filter.statuses.map((s) => STATUS_LABELS[s]).join(" / ")}”` : "yet"}.
            </p>
            <p className="muted">Upload a claim PDF to get started.</p>
          </div>
        )}
        {!data && !error && <div className="empty muted">Loading…</div>}
      </div>
    </div>
  );
}
