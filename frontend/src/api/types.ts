// Shared TypeScript types for the LifeOS Agent Console.
import type { DelegationPlan } from "./agentTypes";

export type { DelegationPlan };
// These mirror the data shapes documented in docs/api-contract.md and the
// Python runtime in lifeos/event/bus.py, lifeos/memory/, lifeos/skills/.

export type EventStatus = "pending" | "processing" | "done" | "failed";

export interface EventRecord {
  id: string;
  type: string;
  payload: Record<string, unknown>;
  trace_id?: string | null;
  status: EventStatus;
  attempts: number;
  created_at: string;
  updated_at: string;
  error?: string | null;
}

export interface ToolCall {
  name?: string;
  action?: string;
  arguments?: Record<string, unknown>;
}

export interface ToolResult {
  tool_call: ToolCall;
  status: "executed" | "blocked";
  output?: string;
  review?: PermissionReview;
}

export type PlanningDecision = "self_plan" | "agent";
export type AgentRoutingPolicy = "auto" | "force_self_plan" | "force_agent";

export interface ChatResponse {
  trace_id: string;
  response: string;
  tool_calls: ToolCall[];
  tool_results?: ToolResult[];
  delegation?: DelegationPlan;
  decision?: PlanningDecision;
  decision_reason?: string;
  decision_confidence?: number;
  plan_steps?: Array<{ id: number; title: string; detail?: string; time?: string }>;
  agent_enabled?: boolean;
  routing_policy?: AgentRoutingPolicy;
  route_source?: "user_override" | "rules" | "model" | "fallback";
  route_signals?: string[];
  requires_side_effects?: boolean;
}

export interface ChatRequest {
  message: string;
  memory_scope?: MemoryScope;
  routing_policy?: AgentRoutingPolicy;
}

/**
 * User rating for a single assistant response.
 *
 * Mirrors the backend vocabulary in lifeos/reflection/engine.py
 * (RATING_WEIGHTS) so the frontend labels and the backend analysis
 * stay in sync.
 */
export type FeedbackRating =
  | "plan_too_heavy" // 计划太重
  | "just_right" // 刚刚好
  | "helpful" // 很有帮助
  | "not_helpful"; // 没帮上忙

export const FEEDBACK_RATINGS: {
  value: FeedbackRating;
  label: string;
  hint: string;
}[] = [
  { value: "plan_too_heavy", label: "计划太重", hint: "任务太多 / 安排过密" },
  { value: "just_right", label: "刚刚好", hint: "节奏合适" },
  { value: "helpful", label: "很有帮助", hint: "直接解决了问题" },
  { value: "not_helpful", label: "没帮上忙", hint: "没有解决我的问题" },
];

export interface FeedbackPayload {
  rating: FeedbackRating;
  trace_id?: string | null;
  note?: string;
}

export interface MemoryEntry {
  id: string;
  source: string;
  category?: "user" | "project" | "feedback" | "reference";
  source_ref?: MemorySourceRef | null;
  evidence_source_ref?: MemorySourceRef | null;
  scope?: MemoryScope;
  confidence?: number | null;
  confidence_method?: string | null;
  occurred_at?: string | null;
  confirmed_at?: string | null;
  valid_from?: string | null;
  valid_until?: string | null;
  promotion?: MemoryPromotion | null;
  content: Record<string, unknown>;
  trace_id?: string | null;
  status?: "active" | "superseded" | "retracted";
  version_of?: string;
  superseded_by?: string;
  superseded_at?: string;
  retracted_at?: string;
  correction_reason?: string;
  retraction_reason?: string;
  created_at: string;
  committed_at?: string;
}

export type MemoryCandidateStatus = "candidate" | "committed" | "rejected";

export interface MemorySourceRef {
  kind: string;
  record_id: string;
  record_kind?: string;
  revision?: string;
  trace_id?: string | null;
}

export interface MemoryScope {
  kind: "global" | "scenario" | "project" | "unassigned";
  scenario_type?: string | null;
  project_id?: string | null;
  user_id?: string | null;
}

export interface MemoryPromotion {
  source_memory_id: string;
  source_scope: MemoryScope;
  target_scope: MemoryScope;
  reason: string;
  authorized_at: string;
}

export interface MemoryCandidate {
  id: string;
  source: string;
  category?: "user" | "project" | "feedback" | "reference";
  source_ref?: MemorySourceRef | null;
  scope?: MemoryScope;
  confidence?: number | null;
  confidence_method?: string | null;
  occurred_at?: string | null;
  valid_from?: string | null;
  valid_until?: string | null;
  content: Record<string, unknown>;
  trace_id?: string | null;
  status: MemoryCandidateStatus;
  created_at: string;
  committed_at?: string;
}

export interface MemoryBackup {
  created_at: string;
  store: Record<string, unknown>;
}

export interface MemoryStore {
  schema_version?: number;
  user: MemoryEntry[];
  project: MemoryEntry[];
  feedback: MemoryEntry[];
  reference: MemoryEntry[];
  candidates: MemoryCandidate[];
  backups: MemoryBackup[];
  vector_index: Record<string, unknown>;
  cache: Record<string, unknown>;
}

export interface MemoryProfileMemory extends MemoryEntry {
  status: "active";
}

export interface MemoryProfileGroup {
  scope: MemoryScope;
  memory_count: number;
  memories: MemoryProfileMemory[];
}

/** Rebuildable read model; the memory store remains the source of truth. */
export interface MemoryProfileView {
  schema_version: 1;
  version: string;
  generated_at: string;
  core_profiles: MemoryProfileGroup[];
  scenario_profiles: MemoryProfileGroup[];
  project_profiles: MemoryProfileGroup[];
}

export interface MemoryMarkdownResponse {
  markdown: string;
  source?: "backend";
}

export type RiskLevel = "low" | "medium" | "high";
export type SkillCandidateStatus = "pending" | "approved" | "rejected";

export interface PermissionReview {
  decision: "allow" | "requires_confirmation" | "deny";
  reason: string;
}

export interface SkillMetrics {
  frequency: number;
  similarity: number;
  complexity: number;
  success_rate: number;
  score: number;
}

export interface SkillUsage {
  uses: number;
  successes: number;
  failures: number;
  last_used_at?: string | null;
}

export interface SkillCandidate {
  id: string;
  name: string;
  description: string;
  keywords?: string[];
  risk: RiskLevel;
  source: string;
  status?: SkillCandidateStatus;
  review?: PermissionReview;
  metrics?: SkillMetrics;
  usage?: SkillUsage;
  created_at?: string;
}

export interface ApprovedSkill extends SkillCandidate {
  status: "approved";
}

export interface SkillRegistryState {
  approved: ApprovedSkill[];
  pending: SkillCandidate[];
}

export interface TraceEvent {
  name: string;
  created: string;
  data: Record<string, unknown>;
}

export interface TraceRecord {
  trace_id: string;
  input: string;
  created: string;
  events: TraceEvent[];
}

export interface PermissionRequest {
  id: string;
  kind: "tool_execution" | "skill_installation";
  subject: string;
  decision: PermissionReview["decision"];
  reason: string;
  created_at: string;
  trace_id?: string | null;
}

export interface RunOnceResponse {
  processed: string[];
}

export type StructuredEntryKind =
  | "daily_plan"
  | "daily_review"
  | "phase_plan"
  | "phase_review"
  | "diary"
  | "insight"
  | "feedback";

export interface StructuredEntry {
  id: string;
  kind: StructuredEntryKind;
  entry_date: string;
  title: string;
  content: string;
  mood?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export type LifecycleStage =
  | "candidate"
  | "validated"
  | "backed_up"
  | "applied"
  | "vector_upserted"
  | "cache_invalidated";

export const LIFECYCLE_STAGES: LifecycleStage[] = [
  "candidate",
  "validated",
  "backed_up",
  "applied",
  "vector_upserted",
  "cache_invalidated",
];

export type ChatAgentStatus =
  | "idle"
  | "thinking"
  | "tool_calling"
  | "responded"
  | "error";

export type GlobalAgentStatus =
  | "idle"
  | "polling"
  | "reflecting"
  | "writing_memory"
  | "detecting_skills"
  | "reviewing";

export type EventBusStatus = "stable" | "queued" | "processing" | "failed";

export type PipelineStageId =
  | "user_input"
  | "chat_agent"
  | "memory_retrieve"
  | "llm_tool"
  | "response"
  | "event_bus"
  | "global_agent"
  | "reflection"
  | "memory_candidate"
  | "security_review"
  | "commit";

export interface PipelineStage {
  id: PipelineStageId;
  label: string;
  detail: string;
}
