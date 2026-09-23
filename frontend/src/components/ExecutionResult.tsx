import type { ActionExecutionResult, StoredPlan, StoredPlanStatus } from "../types/plan";

const TITLES: Partial<Record<StoredPlanStatus, string>> = {
  executing: "STATUS: EXECUTING",
  executed: "STATUS: EXECUTED",
  partially_executed: "STATUS: PARTIALLY EXECUTED",
  execution_failed: "STATUS: EXECUTION FAILED",
};

// Generic fallback for tools/operations without an adapter-specific result
// shape (calendar's is rendered specially below). Mirrors ActionCard's
// generic param list.
function GenericResultDetails({ result }: { result: Record<string, unknown> }) {
  const entries = Object.entries(result).filter(([, value]) => value !== null && value !== undefined);
  if (entries.length === 0) return null;

  return (
    <dl className="execution-result__generic">
      {entries.map(([key, value]) => (
        <div className="execution-result__generic-row" key={key}>
          <dt>{key.replace(/_/g, " ")}</dt>
          <dd>{String(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function ActionLine({ action }: { action: ActionExecutionResult }) {
  const label = `${action.tool}.${action.operation}`;
  const attemptNote = action.attempt_count > 1 ? ` (attempt ${action.attempt_count})` : "";

  if (action.status === "succeeded") {
    const eventId = action.result?.external_event_id;
    const link = action.result?.html_link;
    const startDatetime = action.result?.start_datetime;
    const isCalendarShape =
      typeof eventId === "string" || typeof link === "string" || typeof startDatetime === "string";

    const recipients = action.result?.recipients;
    const subject = action.result?.subject;
    const isEmailShape = Array.isArray(recipients) || typeof subject === "string";

    return (
      <li className="execution-result__action execution-result__action--ok">
        <p>
          {isCalendarShape
            ? "✓ Calendar event created successfully"
            : isEmailShape
              ? "✓ Email sent successfully"
              : `✓ ${label} completed successfully`}
          {attemptNote}
        </p>
        {isCalendarShape ? (
          <>
            {typeof startDatetime === "string" && <p className="execution-result__detail">Scheduled: {startDatetime}</p>}
            {typeof eventId === "string" && <p className="execution-result__detail">Event ID: {eventId}</p>}
            {typeof link === "string" && (
              <a href={link} target="_blank" rel="noreferrer">
                Open Calendar
              </a>
            )}
          </>
        ) : isEmailShape ? (
          <>
            {Array.isArray(recipients) && recipients.length > 0 && (
              <p className="execution-result__detail">
                Recipients: {recipients.filter((r): r is string => typeof r === "string").join(", ")}
              </p>
            )}
            {typeof subject === "string" && <p className="execution-result__detail">Subject: {subject}</p>}
          </>
        ) : (
          action.result && <GenericResultDetails result={action.result} />
        )}
      </li>
    );
  }

  if (action.status === "unsupported") {
    return (
      <li className="execution-result__action execution-result__action--warn">
        ⚠ {label} is not yet supported for execution
      </li>
    );
  }

  return (
    <li className="execution-result__action execution-result__action--error">
      <p>
        ✗ {label} failed{attemptNote}
        {action.error ? `: ${action.error.message}` : ""}
      </p>
      {action.error && (
        <p className="execution-result__detail">
          Error code: {action.error.code} ({action.error.stage})
        </p>
      )}
    </li>
  );
}

export function ExecutionResult({ plan }: { plan: StoredPlan }) {
  const title = TITLES[plan.status] ?? plan.status;

  return (
    <section className={`execution-result execution-result--${plan.status}`}>
      <p className="execution-result__title">{title}</p>

      {plan.status === "executing" && <p>Executing your plan...</p>}

      {plan.execution && (
        <ul className="execution-result__actions">
          {plan.execution.actions.map((action) => (
            <ActionLine key={action.action_id} action={action} />
          ))}
        </ul>
      )}
    </section>
  );
}
