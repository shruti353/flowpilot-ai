import { useState } from "react";
import type { StoredPlan } from "../types/plan";
import { ExecutionResult } from "./ExecutionResult";

interface ApprovalControlsProps {
  plan: StoredPlan;
  onApprove: () => void;
  onReject: (reason?: string) => void;
  onExecute: () => void;
  isSubmitting: boolean;
  isExecuting: boolean;
}

const EXECUTION_STATUSES = new Set(["executing", "executed", "partially_executed", "execution_failed"]);

export function ApprovalControls({
  plan,
  onApprove,
  onReject,
  onExecute,
  isSubmitting,
  isExecuting,
}: ApprovalControlsProps) {
  const [reason, setReason] = useState("");
  const [isRejecting, setIsRejecting] = useState(false);

  if (EXECUTION_STATUSES.has(plan.status)) {
    return <ExecutionResult plan={plan} />;
  }

  if (plan.status === "approved") {
    return (
      <div className="decision-result decision-result--approved">
        <p className="decision-result__title">STATUS: APPROVED</p>
        <p>Plan approved. Ready for execution.</p>
        <p>No actions have been executed yet.</p>
        <button
          type="button"
          className="btn btn--primary"
          disabled={isExecuting}
          onClick={onExecute}
        >
          {isExecuting ? "Executing..." : "Execute Plan"}
        </button>
      </div>
    );
  }

  if (plan.status === "rejected") {
    return (
      <div className="decision-result decision-result--rejected">
        <p className="decision-result__title">STATUS: REJECTED</p>
        {plan.rejection_reason && <p>Reason: {plan.rejection_reason}</p>}
      </div>
    );
  }

  if (plan.status === "cancelled") {
    return (
      <div className="decision-result">
        <p className="decision-result__title">STATUS: CANCELLED</p>
      </div>
    );
  }

  if (plan.status === "needs_clarification") {
    return (
      <div className="decision-result decision-result--warning">
        This plan is missing required information and cannot be approved yet.
        Try rephrasing your request with more detail (a title, a specific time, etc.).
      </div>
    );
  }

  if (plan.status === "error") {
    return (
      <div className="decision-result decision-result--error">
        This request could not be turned into a valid plan, so there is nothing to approve.
      </div>
    );
  }

  // awaiting_approval
  return (
    <div className="approval-controls">
      {isRejecting && (
        <input
          type="text"
          className="approval-controls__reason"
          placeholder="Optional reason for rejecting..."
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          disabled={isSubmitting}
          autoFocus
        />
      )}
      <div className="approval-controls__buttons">
        <button
          type="button"
          className="btn btn--secondary"
          disabled={isSubmitting}
          onClick={() => {
            if (isRejecting) {
              onReject(reason.trim() || undefined);
            } else {
              setIsRejecting(true);
            }
          }}
        >
          {isRejecting ? "Confirm Reject" : "Reject"}
        </button>
        <button type="button" className="btn btn--primary" disabled={isSubmitting} onClick={onApprove}>
          Approve Plan
        </button>
      </div>
    </div>
  );
}
