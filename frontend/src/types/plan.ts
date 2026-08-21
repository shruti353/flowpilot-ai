// Mirrors the backend Pydantic schemas (backend/app/models). Keep in sync
// with app/models/action.py, execution_plan.py, and stored_plan.py.

export type ToolName = "calendar" | "tasks" | "email";

export type OperationName =
  | "create_event"
  | "get_event"
  | "create_task"
  | "get_task"
  | "draft_email"
  | "send_email"
  | "search_email";

export interface Action {
  action_id: string;
  tool: ToolName;
  operation: OperationName;
  parameters: Record<string, unknown>;
  missing_information: string[];
  requires_approval: boolean;
}

export type ExecutionPlanStatus = "ready" | "needs_clarification";

export interface ExecutionPlan {
  plan_id: string;
  intent: string;
  summary: string;
  actions: Action[];
  status: ExecutionPlanStatus;
}

export type StoredPlanStatus =
  | "awaiting_approval"
  | "needs_clarification"
  | "approved"
  | "rejected"
  | "cancelled"
  | "error";

export interface ValidationErrorDetail {
  loc: string;
  message: string;
}

// Response body of POST /api/v1/agent/plan.
export interface AgentPlanResponse {
  request_id: string;
  plan_id: string | null;
  status: StoredPlanStatus;
  execution_plan: ExecutionPlan | null;
  errors: ValidationErrorDetail[] | null;
}

// Body of GET /api/v1/plans/{plan_id}, and nested in the decision responses.
export interface StoredPlan {
  plan_id: string;
  status: StoredPlanStatus;
  execution_plan: ExecutionPlan | null;
  errors: ValidationErrorDetail[] | null;
  rejection_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface ApprovePlanResponse {
  plan_id: string;
  status: StoredPlanStatus;
  message: string;
  plan: StoredPlan;
}

export interface RejectPlanResponse {
  plan_id: string;
  status: StoredPlanStatus;
  message: string;
  rejection_reason: string | null;
  plan: StoredPlan;
}

export interface CancelPlanResponse {
  plan_id: string;
  status: StoredPlanStatus;
  message: string;
  plan: StoredPlan;
}
