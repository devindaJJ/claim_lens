import { RULE_LABELS } from "../format";
import type { RuleOutcome } from "../types";

export function RuleList({ rules }: { rules: RuleOutcome[] }) {
  if (rules.length === 0) return <p className="muted">No policy checks have run yet.</p>;
  const ordered = [...rules].sort((a, b) => Number(a.passed) - Number(b.passed));
  return (
    <ul className="rules">
      {ordered.map((rule) => (
        <li key={rule.code} className={`rule rule--${rule.passed ? "pass" : "fail"}`}>
          <span className="rule__icon" aria-label={rule.passed ? "Passed" : "Failed"}>
            {rule.passed ? "✓" : "!"}
          </span>
          <div className="rule__body">
            <div className="rule__title">{RULE_LABELS[rule.code] ?? rule.code}</div>
            <div className="rule__message">{rule.message}</div>
            {rule.evidence.length > 0 && (
              <details className="rule__evidence">
                <summary>
                  Policy clause{rule.evidence.length > 1 ? "s" : ""}: {rule.evidence.map((e) => e.section).join(", ")}
                </summary>
                {rule.evidence.map((e) => (
                  <blockquote key={e.chunk_id}>
                    <strong>{e.section}</strong> {e.excerpt}
                  </blockquote>
                ))}
              </details>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
