import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { StatusBadge } from "../components/Badges";
import { FieldCard } from "../components/FieldCard";
import { PdfViewer } from "../components/PdfViewer";
import { RuleList } from "../components/RuleList";
import { formatDateTime, percent } from "../format";
import type { ClaimDetail, ClaimField, ClaimTypeOption } from "../types";
import { usePolling } from "../usePolling";

const TEXT_METHOD = { pdf_text: "PDF text layer", ocr: "OCR (scanned)", mixed: "PDF text + OCR" } as const;

export function ClaimPage() {
  const { id = "" } = useParams();
  const [claimTypes, setClaimTypes] = useState<ClaimTypeOption[]>([]);
  const [busyField, setBusyField] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [deciding, setDeciding] = useState(false);

  const load = useCallback(() => api.getClaim(id), [id]);
  const { data: claim, error, setData, reload } = usePolling(
    load,
    (c) => c.status === "queued" || c.status === "processing",
    id,
  );

  useEffect(() => {
    api.claimTypes().then(setClaimTypes).catch(() => setClaimTypes([]));
  }, []);

  useEffect(() => {
    if (claim?.decision_notes) setNotes(claim.decision_notes);
  }, [claim?.decision_notes]);

  async function run<T>(action: () => Promise<T>): Promise<T | null> {
    setActionError(null);
    try {
      return await action();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Something went wrong");
      return null;
    }
  }

  async function review(field: ClaimField, action: "accept" | "correct", value?: string): Promise<boolean> {
    setBusyField(field.name);
    const updated = await run(() => api.reviewField(id, field.name, action, value));
    setBusyField(null);
    if (updated) setData(updated);
    return updated !== null;
  }

  async function acceptAll(c: ClaimDetail) {
    for (const field of c.fields.filter((f) => f.status === "pending" && f.value !== null)) {
      if (!(await review(field, "accept"))) return;
    }
  }

  async function decide(decision: "approve" | "reject") {
    setDeciding(true);
    const updated = await run(() => api.decide(id, decision, notes));
    setDeciding(false);
    if (updated) setData(updated);
  }

  async function reprocess() {
    if (await run(() => api.reprocess(id))) reload();
  }

  if (error && !claim) return <div className="page"><div className="alert alert--error">Could not load claim: {error}</div></div>;
  if (!claim) return <div className="page muted">Loading…</div>;

  const processing = claim.status === "queued" || claim.status === "processing";
  const decided = claim.status === "approved" || claim.status === "rejected";
  const pending = claim.fields.filter((f) => f.status === "pending");
  const readOnly = decided || processing || claim.status === "failed";

  return (
    <div className="review">
      <section className="review__document" aria-label="Claim document">
        <PdfViewer url={api.documentUrl(claim.id)} title={claim.filename} />
      </section>

      <section className="review__panel">
        <div className="review__header">
          <Link to="/" className="back-link">← Back to claims</Link>
          <div className="review__title">
            <h1>{claim.filename}</h1>
            <StatusBadge status={claim.status} />
          </div>
          <dl className="meta-row">
            <div><dt>Received</dt><dd>{formatDateTime(claim.created_at)}</dd></div>
            {claim.text_method && <div><dt>Text source</dt><dd>{TEXT_METHOD[claim.text_method as keyof typeof TEXT_METHOD] ?? claim.text_method}{claim.ocr_confidence !== null && ` · ${percent(claim.ocr_confidence)} OCR confidence`}</dd></div>}
            {claim.extractor && <div><dt>Extractor</dt><dd>{claim.extractor}</dd></div>}
          </dl>
        </div>

        {actionError && <div className="alert alert--error" role="alert">{actionError}</div>}

        {processing && (
          <div className="alert alert--info"><span className="spinner" aria-hidden /> Extracting fields and checking the policy…</div>
        )}

        {claim.status === "failed" && (
          <div className="alert alert--error">
            <strong>Processing failed.</strong> {claim.error}
            <div><button type="button" className="btn btn--ghost btn--sm" onClick={() => void reprocess()}>Try again</button></div>
          </div>
        )}

        {!processing && claim.review_reasons.length > 0 && !decided && (
          <div className="alert alert--warn">
            <strong>Why this claim needs review</strong>
            <ul>{claim.review_reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          </div>
        )}

        {claim.fields.length > 0 && (
          <div className="section">
            <div className="section__header">
              <h2>Extracted fields</h2>
              {!readOnly && pending.length > 0 && (
                <button type="button" className="btn btn--ghost btn--sm" onClick={() => void acceptAll(claim)} disabled={busyField !== null}>
                  Accept all remaining ({pending.length})
                </button>
              )}
            </div>
            <div className="fields">
              {claim.fields.map((field) => (
                <FieldCard
                  key={field.name}
                  field={field}
                  claimTypes={claimTypes}
                  readOnly={readOnly}
                  busy={busyField !== null}
                  onAccept={() => void review(field, "accept")}
                  onCorrect={(value) => review(field, "correct", value)}
                />
              ))}
            </div>
            {claim.description && <p className="description"><span className="muted">Incident summary:</span> {claim.description}</p>}
          </div>
        )}

        {!processing && (
          <div className="section">
            <h2>Policy checks</h2>
            <RuleList rules={claim.rules} />
          </div>
        )}

        {!processing && claim.status !== "failed" && (
          <div className="decision">
            {decided ? (
              <p>
                <strong>{claim.status === "approved" ? "Approved" : "Rejected"}</strong> on {formatDateTime(claim.decided_at)}
                {claim.decision_notes && <> — “{claim.decision_notes}”</>}
              </p>
            ) : (
              <>
                <label className="decision__label" htmlFor="notes">Decision notes</label>
                <textarea id="notes" className="input" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Optional — visible in the claim history" />
                <div className="decision__actions">
                  <span className="muted">{pending.length > 0 ? `${pending.length} field${pending.length > 1 ? "s" : ""} still to review` : "All fields reviewed"}</span>
                  <button type="button" className="btn btn--danger" onClick={() => void decide("reject")} disabled={deciding}>Reject</button>
                  <button type="button" className="btn btn--primary" onClick={() => void decide("approve")} disabled={deciding || pending.length > 0} title={pending.length > 0 ? "Review every field first" : undefined}>Approve claim</button>
                </div>
              </>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
