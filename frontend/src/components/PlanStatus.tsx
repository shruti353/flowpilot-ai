import type { StoredPlanStatus } from "../types/plan";

const STATUS_LABELS: Record<StoredPlanStatus, string> = {
  awaiting_approval: "Awaiting Approval",
  needs_clarification: "Needs Clarification",
  approved: "Approved",
  rejected: "Rejected",
  cancelled: "Cancelled",
  error: "Error",
};

export function PlanStatusBadge({ status }: { status: StoredPlanStatus }) {
  return <span className={`status-badge status-badge--${status}`}>{STATUS_LABELS[status]}</span>;
}
