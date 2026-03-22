export type InputType = "ticket" | "email" | "log";

export type RunStatus =
  | "pending"
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "dead_letter"
  | "needs_review";

export type StepStatus = "pending" | "running" | "completed" | "failed" | "skipped";

export interface WorkflowRun {
  run_id: string;
  status: RunStatus;
  input_type: InputType;
  priority: number;
  created_at: string;
  updated_at: string;
  final_output: string | null;
}

export interface WorkflowStep {
  step_id: string;
  step_name: string;
  step_order: number;
  status: StepStatus;
  input_data: Record<string, unknown> | null;
  output_data: Record<string, unknown> | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface WorkflowStepsResponse {
  run_id: string;
  steps: WorkflowStep[];
}

export interface Metrics {
  total_runs: number;
  completed_runs: number;
  failed_runs: number;
  success_rate: number;
  avg_latency_ms: number;
  total_tokens_in: number;
  total_tokens_out: number;
  total_cost_usd: number;
}

export interface SubmitPayload {
  input_type: InputType;
  raw_input: string;
  priority: number;
}
