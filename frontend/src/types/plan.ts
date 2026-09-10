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

export type FieldType = "text" | "date" | "time" | "datetime" | "number" | "select";

export interface MissingFieldSpec {
  field: string;
  label: string;
  type: FieldType;
  required: boolean;
  options: string[] | null;
  // Week 5: why this field is still missing, when a deterministic
  // resolution step (e.g. recipient lookup) attempted and failed - e.g.
  // "No saved team or contact matches 'AI Team'." Null otherwise.
  hint: string | null;
}

export interface Action {
  action_id: string;
  tool: ToolName;
  operation: OperationName;
  parameters: Record<string, unknown>;
  missing_information: string[];
  missing_fields: MissingFieldSpec[];
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
  | "error"
  | "executing"
  | "executed"
  | "partially_executed"
  | "execution_failed";

export interface ValidationErrorDetail {
  loc: string;
  message: string;
}

// --- Week 3: execution ------------------------------------------------

export type ActionExecutionStatus =
  | "pending"
  | "executing"
  | "succeeded"
  | "failed"
  | "skipped"
  | "unsupported";

export type ErrorStage = "validation" | "configuration" | "transport" | "workflow" | "unsupported";

export interface ExecutionErrorDetail {
  code: string;
  message: string;
  stage: ErrorStage;
}

export interface ActionExecutionResult {
  action_id: string;
  tool: ToolName;
  operation: OperationName;
  status: ActionExecutionStatus;
  result: Record<string, unknown> | null;
  error: ExecutionErrorDetail | null;
  attempt_count: number;
}

export interface PlanExecutionResult {
  status: "success" | "partial" | "failed";
  actions: ActionExecutionResult[];
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
  execution: PlanExecutionResult | null;
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

export interface ExecutePlanResponse {
  plan_id: string;
  status: StoredPlanStatus;
  message: string;
  execution: PlanExecutionResult | null;
  plan: StoredPlan;
}

// --- Week 4: interactive missing-field collection ----------------------

export interface ActionFieldValues {
  action_id: string;
  values: Record<string, unknown>;
}

export interface UpdatePlanFieldsResponse {
  plan_id: string;
  status: StoredPlanStatus;
  message: string;
  plan: StoredPlan;
}
