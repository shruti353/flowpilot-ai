import { useState } from "react";
import { ApiError, approvePlan, executePlan, generatePlan, rejectPlan } from "./services/api";
import type { StoredPlan } from "./types/plan";
import { RequestInput } from "./components/RequestInput";
import { PlanPreview } from "./components/PlanPreview";
import { ApprovalControls } from "./components/ApprovalControls";

function App() {
  const [plan, setPlan] = useState<StoredPlan | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isDeciding, setIsDeciding] = useState(false);
  const [isExecuting, setIsExecuting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleGenerate = async (text: string) => {
    setIsGenerating(true);
    setError(null);
    setPlan(null);

    try {
      const response = await generatePlan(text);
      setPlan({
        plan_id: response.plan_id ?? "",
        status: response.status,
        execution_plan: response.execution_plan,
        errors: response.errors,
        rejection_reason: null,
        execution: null,
        created_at: new Date(0).toISOString(),
        updated_at: new Date(0).toISOString(),
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setIsGenerating(false);
    }
  };

  const handleApprove = async () => {
    if (!plan) return;
    setIsDeciding(true);
    setError(null);
    try {
      const response = await approvePlan(plan.plan_id);
      setPlan(response.plan);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not approve the plan.");
    } finally {
      setIsDeciding(false);
    }
  };

  const handleReject = async (reason?: string) => {
    if (!plan) return;
    setIsDeciding(true);
    setError(null);
    try {
      const response = await rejectPlan(plan.plan_id, reason);
      setPlan(response.plan);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reject the plan.");
    } finally {
      setIsDeciding(false);
    }
  };

  const handleExecute = async () => {
    if (!plan || isExecuting) return;
    setIsExecuting(true);
    setError(null);
    try {
      const response = await executePlan(plan.plan_id);
      setPlan(response.plan);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not execute the plan.");
    } finally {
      setIsExecuting(false);
    }
  };

  return (
    <main className="app">
      <header className="app__header">
        <h1>FlowPilot AI</h1>
        <p className="app__subtitle">
          Describe what you want to do. FlowPilot plans it - nothing runs until you approve it.
        </p>
      </header>

      <RequestInput onSubmit={handleGenerate} isLoading={isGenerating} />

      {error && (
        <p className="app__error" role="alert">
          {error}
        </p>
      )}

      {isGenerating && <p className="app__loading">Generating your plan...</p>}

      {!isGenerating && !plan && !error && (
        <p className="app__empty">Your generated plan will appear here.</p>
      )}

      {plan && !isGenerating && (
        <>
          <PlanPreview plan={plan} />
          <ApprovalControls
            plan={plan}
            onApprove={handleApprove}
            onReject={handleReject}
            onExecute={handleExecute}
            isSubmitting={isDeciding}
            isExecuting={isExecuting}
          />
        </>
      )}
    </main>
  );
}

export default App;
