import type {
  EventRecord,
  MemoryStore,
  SkillRegistryState,
  TraceRecord,
  PermissionRequest,
} from "./types";

function rid(prefix: string): string {
  // RFC4122-ish uuid for mock data; not used for security.
  const r = () => Math.floor(Math.random() * 0xffff).toString(16).padStart(4, "0");
  return `${prefix}-${r()}${r()}-${r()}-${r()}-${r()}${r()}${r()}`;
}

function iso(offsetMin: number): string {
  return new Date(Date.now() + offsetMin * 60_000).toISOString();
}

// Pre-baked mock data for the future endpoints that are not yet implemented
// in lifeos/api/server.py. The frontend falls back to this data when the
// backend returns 404 / "not found" for inspection endpoints, and clearly
// labels it as "local preview data" in the UI.

export function mockEvents(): EventRecord[] {
  return [
    {
      id: rid("evt"),
      type: "conversation.completed",
      payload: {
        session_id: "preview",
        user_input: "summary of yesterday's standup",
        result: { response: "(preview)" },
      },
      trace_id: rid("trc"),
      status: "done",
      attempts: 1,
      created_at: iso(-45),
      updated_at: iso(-44),
      error: null,
    },
    {
      id: rid("evt"),
      type: "memory.write.requested",
      payload: { candidate_id: rid("cnd") },
      trace_id: null,
      status: "pending",
      attempts: 0,
      created_at: iso(-12),
      updated_at: iso(-12),
      error: null,
    },
    {
      id: rid("evt"),
      type: "skill.candidate.created",
      payload: {
        candidate: {
          id: rid("skc"),
          name: "candidate_from_conversation",
          description: "Detected repeated workflow from conversation.",
          risk: "low",
          source: "global_agent",
        },
      },
      trace_id: rid("trc"),
      status: "done",
      attempts: 1,
      created_at: iso(-30),
      updated_at: iso(-29),
      error: null,
    },
    {
      id: rid("evt"),
      type: "conversation.completed",
      payload: {
        session_id: "preview",
        user_input: "auto-reply to vendor emails every Friday",
        result: { response: "(preview)" },
      },
      trace_id: rid("trc"),
      status: "failed",
      attempts: 3,
      created_at: iso(-90),
      updated_at: iso(-60),
      error: "global_agent: reflection engine returned empty summary",
    },
  ];
}

export function mockMemory(): MemoryStore {
  return {
    user: [
      {
        id: rid("mem"),
        source: "user_profile",
        content: {
          name: "(preview user)",
          timezone: "Asia/Shanghai",
          preferred_tone: "concise, technical",
        },
        trace_id: null,
        created_at: iso(-60 * 24 * 14),
      },
    ],
    project: [
      {
        id: rid("mem"),
        source: "reflection",
        content: {
          summary: "User iterates on agent runtime architecture each weekend.",
          memory_type: "conversation_reflection",
        },
        trace_id: rid("trc"),
        created_at: iso(-60 * 24 * 3),
        committed_at: iso(-60 * 24 * 3),
      },
    ],
    feedback: [
      {
        id: rid("mem"),
        source: "feedback",
        content: {
          note: "Prefer minimal mock data over fabricated detail in previews.",
        },
        trace_id: null,
        created_at: iso(-60 * 24),
      },
    ],
    candidates: [
      {
        id: rid("cnd"),
        source: "reflection",
        content: {
          summary: "User asked about commit lifecycle.",
          memory_type: "conversation_reflection",
        },
        trace_id: rid("trc"),
        status: "candidate",
        created_at: iso(-7),
      },
      {
        id: rid("cnd"),
        source: "reflection",
        content: {
          summary: "User discussed skill installation review flow.",
          memory_type: "conversation_reflection",
        },
        trace_id: rid("trc"),
        status: "candidate",
        created_at: iso(-3),
      },
    ],
    backups: [
      {
        created_at: iso(-60 * 24 * 2),
        store: { note: "(preview: pre-commit snapshot, full body omitted)" },
      },
    ],
    vector_index: {},
    cache: {},
  };
}

export function mockSkills(): SkillRegistryState {
  return {
    approved: [
      {
        id: rid("skl"),
        name: "summarize_email_thread",
        description:
          "Summarize an email thread and produce a 3-bullet digest with action items.",
        risk: "low",
        source: "manual",
        status: "approved",
      },
    ],
    pending: [
      {
        id: rid("skc"),
        name: "auto_friday_vendor_reply",
        description:
          "Detect recurring Friday vendor email pattern and draft a reply skeleton.",
        risk: "medium",
        source: "global_agent",
        status: "pending",
        review: {
          decision: "requires_confirmation",
          reason: "medium-risk skill candidate",
        },
        created_at: iso(-180),
      },
      {
        id: rid("skc"),
        name: "weekly_memory_compaction",
        description: "Compact low-value feedback memories on a weekly cadence.",
        risk: "low",
        source: "global_agent",
        status: "pending",
        review: { decision: "allow", reason: "low-risk, reversible" },
        created_at: iso(-240),
      },
    ],
  };
}

export function mockTrace(traceId: string): TraceRecord {
  return {
    trace_id: traceId,
    input: "(preview trace input — backend /traces not implemented yet)",
    created: iso(-30),
    events: [
      {
        name: "memory.retrieved",
        created: iso(-29),
        data: {
          chunks: { user: [], project: [], feedback: [] },
        },
      },
      {
        name: "chat.executed",
        created: iso(-28),
        data: { tool_calls: [], tool_results: [] },
      },
      {
        name: "conversation.completed",
        created: iso(-27),
        data: { result: { response: "(preview)" } },
      },
    ],
  };
}

export function mockPermissions(): PermissionRequest[] {
  return [
    {
      id: rid("perm"),
      kind: "tool_execution",
      subject: "write_file",
      decision: "requires_confirmation",
      reason: "write_file is a high-risk action",
      created_at: iso(-4),
      trace_id: rid("trc"),
    },
    {
      id: rid("perm"),
      kind: "skill_installation",
      subject: "auto_friday_vendor_reply",
      decision: "requires_confirmation",
      reason: "medium-risk skill candidate",
      created_at: iso(-180),
      trace_id: null,
    },
  ];
}
