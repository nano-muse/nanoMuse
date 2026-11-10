import { Eye } from "lucide-react";
import { useT } from "../i18n";
import type { AuditEntry } from "../types";
import { timeShort } from "../util";

export function SentinelReviewRow({ entry }: { entry: AuditEntry }) {
  const t = useT();
  const decision = (value: string) => {
    switch (value) {
      case "allow": return t("Allow");
      case "ask": return t("Ask for approval");
      case "deny": return t("Deny");
      default: return t("Unavailable");
    }
  };
  const outcome = () => {
    switch (entry.status) {
      case "ok": return entry.recommendation ? t("Model suggestion: {decision}", { decision: decision(entry.recommendation) }) : t("No review result");
      case "timeout": return t("Review timed out");
      case "invalid_response": return t("The model did not return a valid suggestion");
      case "cancelled": return t("Review cancelled");
      case "disabled": return entry.reason === "configuration_changed"
        ? t("Review skipped because the configuration changed before it started")
        : t("Review skipped because observation was turned off");
      case "busy": return t("Review skipped because other reviews were running");
      case "input_limit": return t("Review skipped because the operation exceeded the input limit");
      case "snapshot_error": return t("The operation could not be prepared for review");
      case "error": return t("Review unavailable");
      default: return t("No review result");
    }
  };
  return (
    <li className="flex items-start gap-2.5 rounded-2xl bg-surface-2/60 px-3 py-2">
      <Eye size={15} className="mt-0.5 shrink-0 text-muted" />
      <div className="min-w-0 flex-1">
        <div className="text-[13.5px] font-medium">{t("Model review (observe only)")}</div>
        {entry.tool && <div className="text-[12.5px] break-words">{entry.tool}</div>}
        <div className="mt-0.5 text-[12.5px]">{outcome()}</div>
        {entry.actual_decision && <div className="text-[12.5px]">{t("Permission decision: {decision}", { decision: decision(entry.actual_decision) })}</div>}
        <div className="mt-0.5 flex flex-wrap gap-x-2 text-[11.5px] text-muted">
          <span>{timeShort(entry.ts)}</span>
          {entry.model && <span className="break-all">{[entry.provider, entry.model].filter(Boolean).join(" / ")}</span>}
        </div>
        {entry.reason === "incomplete_input" && <p className="mt-0.5 text-[12px] text-muted">{t("Some operation or task details were missing from this review.")}</p>}
        <p className="mt-0.5 text-[12px] text-muted">{t("Observation only. The permission decision was not changed.")}</p>
      </div>
    </li>
  );
}
