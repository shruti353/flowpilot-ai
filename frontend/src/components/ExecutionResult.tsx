import type { ActionExecutionResult, StoredPlan, StoredPlanStatus } from "../types/plan";

const TITLES: Partial<Record<StoredPlanStatus, string>> = {
  executing: "STATUS: EXECUTING",
  executed: "STATUS: EXECUTED",
  partially_executed: "STATUS: PARTIALLY EXECUTED",
  execution_failed: "STATUS: EXECUTION FAILED",
};

function ActionLine({ action }: { action: ActionExecutionResult }) {
  const label = `${action.tool}.${action.operation}`;

  if (action.status === "succeeded") {
    const eventId = action.result?.external_event_id;
    const link = action.result?.html_link;
    const startDatetime = action.result?.start_datetime;
    return (
      <li className="execution-result__action execution-result__action--ok">
        <p>✓ Calendar event created successfully</p>
        {typeof startDatetime === "string" && <p className="execution-result__detail">Scheduled: {startDatetime}</p>}
        {typeof eventId === "string" && <p className="execution-result__detail">Event ID: {eventId}</p>}
        {typeof link === "string" && (
          <a href={link} target="_blank" rel="noreferrer">
            Open Calendar
          </a>
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
      ✗ {label} failed{action.error ? `: ${action.error.message}` : ""}
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
