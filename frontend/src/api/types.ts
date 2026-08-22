// Shared TypeScript types for the LifeOS Agent Console.
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

export interface ChatResponse {
  trace_id: string;
  response: string;
  tool_calls: ToolCall[];
}

export interface MemoryEntry {
  id: string;
  source: string;
  content: Record<string, unknown>;
  trace_id?: string | null;
  created_at: string;
  committed_at?: string;
}

export type MemoryCandidateStatus = "candidate" | "committed" | "rejected";

export interface MemoryCandidate {
  id: string;
  source: string;
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
  user: MemoryEntry[];
  project: MemoryEntry[];
  feedback: MemoryEntry[];
  candidates: MemoryCandidate[];
  backups: MemoryBackup[];
  vector_index: Record<string, unknown>;
  cache: Record<string, unknown>;
}

export type RiskLevel = "low" | "medium" | "high";
export type SkillCandidateStatus = "pending" | "approved" | "rejected";

export interface PermissionReview {
  decision: "allow" | "requires_confirmation" | "deny";
  reason: string;
}

export interface SkillCandidate {
  id: string;
  name: string;
  description: string;
  risk: RiskLevel;
  source: string;
  status?: SkillCandidateStatus;
  review?: PermissionReview;
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
