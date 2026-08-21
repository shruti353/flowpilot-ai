import type { StoredPlan } from "../types/plan";
import { ActionCard } from "./ActionCard";
import { PlanStatusBadge } from "./PlanStatus";

export function PlanPreview({ plan }: { plan: StoredPlan }) {
  const executionPlan = plan.execution_plan;

  return (
    <section className="plan-preview">
      <header className="plan-preview__header">
        <h2>AI Execution Plan</h2>
        <PlanStatusBadge status={plan.status} />
      </header>

      {executionPlan ? (
        <>
          <p className="plan-preview__summary">{executionPlan.summary}</p>

          <h3 className="plan-preview__actions-heading">Actions</h3>
          <ol className="plan-preview__actions">
            {executionPlan.actions.map((action, index) => (
              <ActionCard key={action.action_id} action={action} index={index} />
            ))}
          </ol>
        </>
      ) : (
        <p className="plan-preview__error">
          {plan.errors && plan.errors.length > 0
            ? plan.errors.map((error) => error.message).join(" ")
            : "This request could not be turned into a valid plan."}
        </p>
      )}
    </section>
  );
}
