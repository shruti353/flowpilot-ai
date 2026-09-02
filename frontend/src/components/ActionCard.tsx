import type { Action, OperationName, ToolName } from "../types/plan";
import { formatResolvedDatetime } from "../utils/datetime";

const TOOL_ICONS: Record<ToolName, string> = {
  calendar: "📅",
  tasks: "✓",
  email: "✉️",
};

const OPERATION_LABELS: Record<OperationName, string> = {
  create_event: "Create Event",
  get_event: "Get Event",
  create_task: "Create Task",
  get_task: "Get Task",
  draft_email: "Draft Email",
  send_email: "Send Email",
  search_email: "Search Email",
};

function formatParamLabel(key: string): string {
  return key.charAt(0).toUpperCase() + key.slice(1).replace(/_/g, " ");
}

// The resolved datetime is shown as the "Datetime" row's value (in place
// of the raw expression); it never gets its own separate row.
function formatParamValue(key: string, value: unknown, parameters: Record<string, unknown>): string {
  if (key === "datetime") {
    const resolved = parameters.resolved_datetime;
    if (typeof resolved === "string" && resolved) {
      return formatResolvedDatetime(resolved);
    }
  }
  return String(value);
}

interface ActionCardProps {
  action: Action;
  index: number;
}

export function ActionCard({ action, index }: ActionCardProps) {
  const paramEntries = Object.entries(action.parameters).filter(([key]) => key !== "resolved_datetime");

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

      {paramEntries.length > 0 && (
        <dl className="action-card__params">
          {paramEntries.map(([key, value]) => (
            <div className="action-card__param" key={key}>
              <dt>{formatParamLabel(key)}</dt>
              <dd>{formatParamValue(key, value, action.parameters)}</dd>
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
