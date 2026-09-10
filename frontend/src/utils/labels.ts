import type { OperationName } from "../types/plan";

export const OPERATION_LABELS: Record<OperationName, string> = {
  create_event: "Create Event",
  get_event: "Get Event",
  create_task: "Create Task",
  get_task: "Get Task",
  draft_email: "Draft Email",
  send_email: "Send Email",
  search_email: "Search Email",
};
