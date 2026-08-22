// Thin fetch wrapper around the FlowPilot backend. Every plan/approval
// action funnels through here so components never construct a request URL
// or parse an error body themselves.

import type {
  AgentPlanResponse,
  ApprovePlanResponse,
  CancelPlanResponse,
  ExecutePlanResponse,
  RejectPlanResponse,
  StoredPlan,
  ValidationErrorDetail,
} from "../types/plan";

const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000";
const API_V1_URL = `${API_BASE_URL}/api/v1`;

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function extractErrorMessage(status: number, body: unknown): string {
  if (body && typeof body === "object") {
    const detail = (body as Record<string, unknown>).detail;
    if (detail && typeof detail === "object" && "message" in detail) {
      return String((detail as Record<string, unknown>).message);
    }
    if (typeof detail === "string") {
      return detail;
    }
    const errors = (body as Record<string, unknown>).errors;
    if (Array.isArray(errors) && errors.length > 0) {
      return (errors as ValidationErrorDetail[]).map((e) => e.message).join(" ");
    }
  }
  return `Request failed with status ${status}.`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_V1_URL}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new ApiError(
      "Could not reach the FlowPilot backend. Is it running on " + API_BASE_URL + "?",
      0,
    );
  }

  const body = await response.json().catch(() => null);

  if (!response.ok) {
    throw new ApiError(extractErrorMessage(response.status, body), response.status);
  }

  return body as T;
}

export function generatePlan(text: string): Promise<AgentPlanResponse> {
  return request<AgentPlanResponse>("/agent/plan", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

export function getPlan(planId: string): Promise<StoredPlan> {
  return request<StoredPlan>(`/plans/${planId}`);
}

export function approvePlan(planId: string): Promise<ApprovePlanResponse> {
  return request<ApprovePlanResponse>(`/plans/${planId}/approve`, { method: "POST" });
}

export function rejectPlan(planId: string, reason?: string): Promise<RejectPlanResponse> {
  return request<RejectPlanResponse>(`/plans/${planId}/reject`, {
    method: "POST",
    body: JSON.stringify(reason ? { reason } : {}),
  });
}

export function cancelPlan(planId: string): Promise<CancelPlanResponse> {
  return request<CancelPlanResponse>(`/plans/${planId}/cancel`, { method: "POST" });
}

export function executePlan(planId: string): Promise<ExecutePlanResponse> {
  return request<ExecutePlanResponse>(`/plans/${planId}/execute`, { method: "POST" });
}
