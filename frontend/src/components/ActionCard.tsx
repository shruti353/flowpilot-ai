import type { Action, ToolName } from "../types/plan";
import { formatResolvedDate, formatResolvedDatetime, formatResolvedTime } from "../utils/datetime";
import { OPERATION_LABELS } from "../utils/labels";

const TOOL_ICONS: Record<ToolName, string> = {
  calendar: "📅",
  tasks: "✓",
  email: "✉️",
};

// These are raw inputs / derived resolutions the backend uses internally
// (see app/agent/nodes/enrich_datetime.py) - never shown as their own
// generic param row. Only a resolved, friendly summary (computed below) is
// ever displayed, and only for the parts that were actually resolved -
// never a fabricated date or time for a part the user didn't supply.
const RESERVED_DATETIME_KEYS = new Set([
  "date",
  "time",
  "datetime",
  "resolved_date",
  "resolved_time",
  "resolved_datetime",
]);

function formatParamLabel(key: string): string {
  return key.charAt(0).toUpperCase() + key.slice(1).replace(/_/g, " ");
}

function formatParamValue(value: unknown): string {
  return String(value);
}

// The resolved date/time summary shown above the generic param list. Shows
// exactly what has actually been resolved - a full datetime, just a date,
// or just a time - and nothing when neither is resolved yet (never invents
// a placeholder).
function DateTimeSummary({ parameters }: { parameters: Record<string, unknown> }) {
  const resolvedDatetime = parameters.resolved_datetime;
  if (typeof resolvedDatetime === "string" && resolvedDatetime) {
    return (
      <div className="action-card__param">
        <dt>Date &amp; Time</dt>
        <dd>{formatResolvedDatetime(resolvedDatetime)}</dd>
      </div>
    );
  }

  const resolvedDate = parameters.resolved_date;
  const resolvedTime = parameters.resolved_time;
  const hasDate = typeof resolvedDate === "string" && resolvedDate;
  const hasTime = typeof resolvedTime === "string" && resolvedTime;
  if (!hasDate && !hasTime) {
    return null;
  }

  return (
    <>
      {hasDate && (
        <div className="action-card__param">
          <dt>Date</dt>
          <dd>{formatResolvedDate(resolvedDate as string)}</dd>
        </div>
      )}
      {hasTime && (
        <div className="action-card__param">
          <dt>Time</dt>
          <dd>{formatResolvedTime(resolvedTime as string)}</dd>
        </div>
      )}
    </>
  );
}

interface ActionCardProps {
  action: Action;
  index: number;
}

export function ActionCard({ action, index }: ActionCardProps) {
  const paramEntries = Object.entries(action.parameters).filter(
    ([key]) => !RESERVED_DATETIME_KEYS.has(key),
  );
  const hasDateTimeInfo =
    typeof action.parameters.resolved_datetime === "string" ||
    typeof action.parameters.resolved_date === "string" ||
    typeof action.parameters.resolved_time === "string";

  return (
    <li className="action-card">
      <div className="action-card__header">
        <span className="action-card__index">{index + 1}.</span>
        <span className="action-card__icon" aria-hidden="true">
          {TOOL_ICONS[action.tool]}
        </span>
        <span className="action-card__tool">{action.tool}</span>
      </div>
      <div className="action-card__operation">{OPERATION_LABELS[action.operation]}</div>

      {(paramEntries.length > 0 || hasDateTimeInfo) && (
        <dl className="action-card__params">
          <DateTimeSummary parameters={action.parameters} />
          {paramEntries.map(([key, value]) => (
            <div className="action-card__param" key={key}>
              <dt>{formatParamLabel(key)}</dt>
              <dd>{formatParamValue(value)}</dd>
            </div>
          ))}
        </dl>
      )}

      {action.missing_information.length > 0 && (
        <p className="action-card__missing">
          Missing information: {action.missing_information.join(", ")}
        </p>
      )}
    </li>
  );
}
