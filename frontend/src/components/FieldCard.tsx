import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { FIELD_LABELS, formatFieldValue } from "../format";
import type { ClaimField, ClaimTypeOption } from "../types";
import { ConfidenceMeter } from "./Badges";

interface Props {
  field: ClaimField;
  claimTypes: ClaimTypeOption[];
  readOnly: boolean;
  busy: boolean;
  onAccept: () => void;
  onCorrect: (value: string) => Promise<boolean>;
}

const STATUS_TEXT = { pending: "Needs review", accepted: "Accepted", corrected: "Corrected" } as const;

export function FieldCard({ field, claimTypes, readOnly, busy, onAccept, onCorrect }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(field.value ?? "");
  const inputRef = useRef<HTMLInputElement & HTMLSelectElement>(null);
  const typeLabels = Object.fromEntries(claimTypes.map((t) => [t.value, t.label]));

  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  function startEditing() {
    setDraft(field.value ?? "");
    setEditing(true);
  }

  async function save() {
    if (await onCorrect(draft)) setEditing(false);
  }

  function onKeyDown(e: KeyboardEvent) {
    if (e.key === "Enter") void save();
    if (e.key === "Escape") setEditing(false);
  }

  const lowConfidence = field.status === "pending" && field.confidence < 0.8;

  return (
    <article className={`field field--${field.status}${lowConfidence ? " field--attention" : ""}`}>
      <header className="field__header">
        <span className="field__label">{FIELD_LABELS[field.name]}</span>
        <span className={`field__status field__status--${field.status}`}>{STATUS_TEXT[field.status]}</span>
      </header>

      {editing ? (
        <div className="field__editor">
          {field.name === "claim_type" ? (
            <select ref={inputRef} className="input" value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKeyDown}>
              <option value="">Select a claim type…</option>
              {claimTypes.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          ) : (
            <input
              ref={inputRef}
              className="input"
              type={field.name === "incident_date" ? "date" : field.name === "amount" ? "number" : "text"}
              step={field.name === "amount" ? "0.01" : undefined}
              min={field.name === "amount" ? "0" : undefined}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
            />
          )}
          <div className="field__actions">
            <button type="button" className="btn btn--ghost btn--sm" onClick={() => setEditing(false)} disabled={busy}>
              Cancel
            </button>
            <button type="button" className="btn btn--primary btn--sm" onClick={() => void save()} disabled={busy}>
              Save correction
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className={`field__value${field.name === "policy_number" ? " mono" : ""}`}>
            {formatFieldValue(field.name, field.value, typeLabels)}
          </div>
          {field.status === "corrected" && (
            <div className="field__original">
              Extracted: <s>{formatFieldValue(field.name, field.extracted_value, typeLabels)}</s>
            </div>
          )}
          <div className="field__meta">
            <ConfidenceMeter value={field.confidence} />
            {field.evidence ? (
              <q className="field__evidence" title={field.grounded ? "Found in the document" : "Not found verbatim in the document"}>
                {field.evidence}
              </q>
            ) : (
              <span className="field__evidence field__evidence--none">No supporting text found</span>
            )}
            {field.evidence && !field.grounded && <span className="tag tag--warn">Not in document</span>}
          </div>
          {!readOnly && (
            <div className="field__actions">
              <button type="button" className="btn btn--ghost btn--sm" onClick={startEditing} disabled={busy}>
                Correct
              </button>
              <button
                type="button"
                className="btn btn--success btn--sm"
                onClick={onAccept}
                disabled={busy || field.status === "accepted" || field.value === null}
              >
                {field.status === "accepted" ? "Accepted" : "Accept"}
              </button>
            </div>
          )}
        </>
      )}
    </article>
  );
}
