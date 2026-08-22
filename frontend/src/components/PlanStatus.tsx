import type { StoredPlanStatus } from "../types/plan";

const STATUS_LABELS: Record<StoredPlanStatus, string> = {
  awaiting_approval: "Awaiting Approval",
  needs_clarification: "Needs Clarification",
  approved: "Approved",
  rejected: "Rejected",
  cancelled: "Cancelled",
  error: "Error",
  executing: "Executing",
  executed: "Executed",
  partially_executed: "Partially Executed",
  execution_failed: "Execution Failed",
};

export function PlanStatusBadge({ status }: { status: StoredPlanStatus }) {
  return <span className={`status-badge status-badge--${status}`}>{STATUS_LABELS[status]}</span>;
}
