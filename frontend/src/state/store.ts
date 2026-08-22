import { useEffect, useMemo, useReducer, useRef, useCallback } from "react";
import type {
  ChatAgentStatus,
  ChatResponse,
  EventBusStatus,
  EventRecord,
  GlobalAgentStatus,
  MemoryCandidate,
  MemoryStore,
  PermissionRequest,
  PipelineStageId,
  RunOnceResponse,
  SkillRegistryState,
  ToolCall,
} from "../api/types";

// Re-export domain types so panels can import everything from the store.
export type {
  ChatAgentStatus,
  EventBusStatus,
  EventRecord,
  GlobalAgentStatus,
  MemoryCandidate,
  MemoryStore,
  PermissionRequest,
  PipelineStageId,
  SkillRegistryState,
  ToolCall,
};
import {
  getEvents,
  getMemory,
  getPermissions,
  getSkills,
  getTrace,
  runBackgroundOnce,
  sendChat,
} from "../api/client";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  trace_id?: string;
  tool_calls?: ToolCall[];
  created_at: string;
  // execution status: pending until /chat returns, then succeeded/blocked.
  execution?: "pending" | "succeeded" | "blocked" | "error";
  error?: string;
}

export interface PipelineState {
  // id of the currently-active pipeline stage (or null).
  active: PipelineStageId | null;
  // map of trace_id -> array of stages already visited (for animation).
  visited: PipelineStageId[];
}

export interface UiState {
  dataMode: "backend" | "preview"; // single source-of-truth badge
  chatStatus: ChatAgentStatus;
  busStatus: EventBusStatus;
  globalStatus: GlobalAgentStatus;
  lastRunAt: string | null;
  lastError: string | null;
  selectedTraceId: string | null;
  selectedPermissionId: string | null;
}

export interface AppState {
  messages: ChatMessage[];
  events: EventRecord[];
  memory: MemoryStore;
  skills: SkillRegistryState;
  permissions: PermissionRequest[];
  pipeline: PipelineState;
  ui: UiState;
  loading: {
    chat: boolean;
    background: boolean;
    events: boolean;
    memory: boolean;
    skills: boolean;
    permissions: boolean;
  };
}

type Action =
  | { type: "SET_LOADING"; key: keyof AppState["loading"]; value: boolean }
  | { type: "SET_UI"; patch: Partial<UiState> }
  | { type: "SET_CHAT_STATUS"; status: ChatAgentStatus }
  | { type: "SET_BUS_STATUS"; status: EventBusStatus }
  | { type: "SET_GLOBAL_STATUS"; status: GlobalAgentStatus }
  | { type: "APPEND_MESSAGE"; message: ChatMessage }
  | { type: "UPDATE_MESSAGE"; id: string; patch: Partial<ChatMessage> }
  | { type: "PIPELINE_ACTIVE"; stage: PipelineStageId | null }
  | { type: "PIPELINE_VISIT"; stages: PipelineStageId[] }
  | { type: "PIPELINE_RESET" }
  | { type: "SET_EVENTS"; events: EventRecord[]; source: "backend" | "preview" }
  | { type: "PATCH_EVENT"; id: string; patch: Partial<EventRecord> }
  | { type: "APPEND_EVENT"; event: EventRecord }
  | { type: "SET_MEMORY"; memory: MemoryStore; source: "backend" | "preview" }
  | { type: "PATCH_CANDIDATE"; id: string; patch: Partial<MemoryCandidate> }
  | { type: "APPEND_BACKUP_AT"; index: number }
  | { type: "SET_SKILLS"; skills: SkillRegistryState; source: "backend" | "preview" }
  | { type: "PATCH_PENDING"; id: string; status: "approved" | "rejected" }
  | { type: "SET_PERMISSIONS"; permissions: PermissionRequest[]; source: "backend" | "preview" }
  | { type: "RESOLVE_PERMISSION"; id: string; decision: "allow" | "deny" }
  | { type: "SELECT_TRACE"; id: string | null }
  | { type: "SELECT_PERMISSION"; id: string | null }
  | { type: "SET_ERROR"; error: string | null }
  | { type: "SET_LAST_RUN"; at: string };

function rid(prefix: string): string {
  const r = () => Math.floor(Math.random() * 0xffff).toString(16).padStart(4, "0");
  return `${prefix}-${r()}${r()}-${r()}-${r()}-${r()}${r()}${r()}`;
}

function isoNow(): string {
  return new Date().toISOString();
}

const initialState: AppState = {
  messages: [
    {
      id: "system-welcome",
      role: "assistant",
      content:
        "LifeOS Chat Agent online. Send a message to start a turn — I will retrieve memory, respond, and publish a conversation.completed event for the Global Agent.",
      created_at: isoNow(),
    },
  ],
  events: [],
  memory: {
    user: [],
    project: [],
    feedback: [],
    candidates: [],
    backups: [],
    vector_index: {},
    cache: {},
  },
  skills: { approved: [], pending: [] },
  permissions: [],
  pipeline: { active: null, visited: [] },
  ui: {
    dataMode: "preview",
    chatStatus: "idle",
    busStatus: "stable",
    globalStatus: "idle",
    lastRunAt: null,
    lastError: null,
    selectedTraceId: null,
    selectedPermissionId: null,
  },
  loading: {
    chat: false,
    background: false,
    events: false,
    memory: false,
    skills: false,
    permissions: false,
  },
};

function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case "SET_LOADING":
      return {
        ...state,
        loading: { ...state.loading, [action.key]: action.value },
      };
    case "SET_UI":
      return { ...state, ui: { ...state.ui, ...action.patch } };
    case "SET_CHAT_STATUS":
      return { ...state, ui: { ...state.ui, chatStatus: action.status } };
    case "SET_BUS_STATUS":
      return { ...state, ui: { ...state.ui, busStatus: action.status } };
    case "SET_GLOBAL_STATUS":
      return { ...state, ui: { ...state.ui, globalStatus: action.status } };
    case "APPEND_MESSAGE":
      return { ...state, messages: [...state.messages, action.message] };
    case "UPDATE_MESSAGE":
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === action.id ? { ...m, ...action.patch } : m,
        ),
      };
    case "PIPELINE_ACTIVE":
      return { ...state, pipeline: { ...state.pipeline, active: action.stage } };
    case "PIPELINE_VISIT":
      return {
        ...state,
        pipeline: {
          ...state.pipeline,
          visited: action.stages,
          active: null,
        },
      };
    case "PIPELINE_RESET":
      return { ...state, pipeline: { active: null, visited: [] } };
    case "SET_EVENTS":
      return { ...state, events: action.events };
    case "PATCH_EVENT":
      return {
        ...state,
        events: state.events.map((e) =>
          e.id === action.id ? { ...e, ...action.patch } : e,
        ),
      };
    case "APPEND_EVENT":
      return { ...state, events: [action.event, ...state.events] };
    case "SET_MEMORY":
      return { ...state, memory: action.memory };
    case "PATCH_CANDIDATE":
      return {
        ...state,
        memory: {
          ...state.memory,
          candidates: state.memory.candidates.map((c) =>
            c.id === action.id ? { ...c, ...action.patch } : c,
          ),
        },
      };
    case "APPEND_BACKUP_AT":
      return {
        ...state,
        memory: {
          ...state.memory,
          backups: [...state.memory.backups, { created_at: isoNow(), store: {} }],
        },
      };
    case "SET_SKILLS":
      return { ...state, skills: action.skills };
    case "PATCH_PENDING":
      return {
        ...state,
        skills: {
          approved:
            action.status === "approved"
              ? [
                  ...state.skills.approved,
                  ...state.skills.pending
                    .filter((s) => s.id === action.id)
                    .map((s) => ({ ...s, status: "approved" as const })),
                ]
              : state.skills.approved,
          pending: state.skills.pending
            .filter((s) => s.id !== action.id)
            .map((s) =>
              s.id === action.id ? { ...s, status: action.status } : s,
            ),
        },
      };
    case "SET_PERMISSIONS":
      return { ...state, permissions: action.permissions };
    case "RESOLVE_PERMISSION":
      return {
        ...state,
        permissions: state.permissions.filter((p) => p.id !== action.id),
      };
    case "SELECT_TRACE":
      return { ...state, ui: { ...state.ui, selectedTraceId: action.id } };
    case "SELECT_PERMISSION":
      return {
        ...state,
        ui: { ...state.ui, selectedPermissionId: action.id },
      };
    case "SET_ERROR":
      return { ...state, ui: { ...state.ui, lastError: action.error } };
    case "SET_LAST_RUN":
      return { ...state, ui: { ...state.ui, lastRunAt: action.at } };
    default:
      return state;
  }
}

// Pipeline stage ordering (for animation/visit tracking).
export const PIPELINE_ORDER: PipelineStageId[] = [
  "user_input",
  "chat_agent",
  "memory_retrieve",
  "llm_tool",
  "response",
  "event_bus",
  "global_agent",
  "reflection",
  "memory_candidate",
  "security_review",
  "commit",
];

export function useStore() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const stateRef = useRef(state);
  stateRef.current = state;

  const setUi = useCallback(
    (patch: Partial<UiState>) => dispatch({ type: "SET_UI", patch }),
    [],
  );
  const setChatStatus = useCallback(
    (status: ChatAgentStatus) => dispatch({ type: "SET_CHAT_STATUS", status }),
    [],
  );
  const setBusStatus = useCallback(
    (status: EventBusStatus) => dispatch({ type: "SET_BUS_STATUS", status }),
    [],
  );
  const setGlobalStatus = useCallback(
    (status: GlobalAgentStatus) => dispatch({ type: "SET_GLOBAL_STATUS", status }),
    [],
  );
  const setLoading = useCallback(
    (key: keyof AppState["loading"], value: boolean) =>
      dispatch({ type: "SET_LOADING", key, value }),
    [],
  );
  const setError = useCallback(
    (error: string | null) => dispatch({ type: "SET_ERROR", error }),
    [],
  );
  const setLastRun = useCallback(
    (at: string) => dispatch({ type: "SET_LAST_RUN", at }),
    [],
  );

  const refreshAll = useCallback(async () => {
    setLoading("events", true);
    setLoading("memory", true);
    setLoading("skills", true);
    setLoading("permissions", true);

    const [evR, memR, skR, perR] = await Promise.all([
      getEvents(),
      getMemory(),
      getSkills(),
      getPermissions(),
    ]);

    dispatch({ type: "SET_EVENTS", events: evR.events, source: evR.source });
    dispatch({ type: "SET_MEMORY", memory: memR.data, source: memR.source });
    dispatch({ type: "SET_SKILLS", skills: skR.data, source: skR.source });
    dispatch({
      type: "SET_PERMISSIONS",
      permissions: perR.data,
      source: perR.source,
    });

    const sources = [evR.source, memR.source, skR.source, perR.source];
    const anyPreview = sources.some((s) => s === "preview");
    const allBackend = sources.every((s) => s === "backend");
    dispatch({
      type: "SET_UI",
      patch: { dataMode: allBackend ? "backend" : "preview" },
    });

    setLoading("events", false);
    setLoading("memory", false);
    setLoading("skills", false);
    setLoading("permissions", false);
    return { anyPreview, allBackend };
  }, [setLoading]);

  // Initial load.
  useEffect(() => {
    refreshAll().catch((e) => setError(String(e)));
  }, [refreshAll, setError]);

  const sendMessage = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;

      const userMsg: ChatMessage = {
        id: rid("msg"),
        role: "user",
        content: trimmed,
        created_at: isoNow(),
      };
      dispatch({ type: "APPEND_MESSAGE", message: userMsg });
      dispatch({ type: "PIPELINE_RESET" });

      // Animate pipeline: user_input -> chat_agent -> memory_retrieve -> llm_tool
      const preStages: PipelineStageId[] = [
        "user_input",
        "chat_agent",
        "memory_retrieve",
        "llm_tool",
      ];
      for (const s of preStages) {
        dispatch({ type: "PIPELINE_ACTIVE", stage: s });
        await new Promise((r) => setTimeout(r, 120));
      }

      setChatStatus("thinking");
      setLoading("chat", true);
      setError(null);

      const pendingAssistantId = rid("msg");
      dispatch({
        type: "APPEND_MESSAGE",
        message: {
          id: pendingAssistantId,
          role: "assistant",
          content: "",
          created_at: isoNow(),
          execution: "pending",
        },
      });

      let chatRes: ChatResponse;
      try {
        chatRes = await sendChat(trimmed);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setError(`chat failed: ${msg}`);
        setChatStatus("error");
        dispatch({
          type: "UPDATE_MESSAGE",
          id: pendingAssistantId,
          patch: {
            content: `(chat failed: ${msg})`,
            execution: "error",
            error: msg,
          },
        });
        setLoading("chat", false);
        return;
      }

      // After response: pipeline reaches response + event_bus.
      dispatch({
        type: "PIPELINE_VISIT",
        stages: [...preStages, "response", "event_bus"],
      });
      setChatStatus(
        chatRes.tool_calls && chatRes.tool_calls.length > 0
          ? "tool_calling"
          : "responded",
      );
      dispatch({
        type: "UPDATE_MESSAGE",
        id: pendingAssistantId,
        patch: {
          content: chatRes.response,
          trace_id: chatRes.trace_id,
          tool_calls: chatRes.tool_calls,
          execution: "succeeded",
        },
      });
      setUi({ selectedTraceId: chatRes.trace_id });

      // Optimistic append of conversation.completed pending event.
      const optimisticEvent: EventRecord = {
        id: rid("evt"),
        type: "conversation.completed",
        payload: {
          session_id: "console",
          user_input: trimmed,
          result: { response: chatRes.response },
        },
        trace_id: chatRes.trace_id,
        status: "pending",
        attempts: 0,
        created_at: isoNow(),
        updated_at: isoNow(),
        error: null,
      };
      dispatch({ type: "APPEND_EVENT", event: optimisticEvent });
      setBusStatus("queued");
      setLoading("chat", false);

      // Brief tool-calling animation, then back to idle/responded.
      if (chatRes.tool_calls && chatRes.tool_calls.length > 0) {
        await new Promise((r) => setTimeout(r, 350));
      }
      setChatStatus("responded");

      // Fetch the trace detail in the background — does not block chat.
      void getTrace(chatRes.trace_id)
        .then(() => undefined)
        .catch(() => undefined);
    },
    [setChatStatus, setError, setLoading, setUi, setBusStatus],
  );

  const runBackground = useCallback(async () => {
    setGlobalStatus("polling");
    setLoading("background", true);
    setError(null);
    dispatch({
      type: "PIPELINE_VISIT",
      stages: [
        "event_bus",
        "global_agent",
        "reflection",
        "memory_candidate",
        "security_review",
        "commit",
      ],
    });

    let res: RunOnceResponse;
    try {
      res = await runBackgroundOnce();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(`background failed: ${msg}`);
      setGlobalStatus("idle");
      setLoading("background", false);
      return;
    }

    // Mark processed events as done. Events that weren't processed before
    // this call (e.g. the optimistic one we just appended) get processed now.
    const processed = new Set(res.processed);
    stateRef.current.events.forEach((e) => {
      if (e.status === "pending" || e.status === "processing" || e.status === "failed") {
        if (processed.has(e.id) || (e.type === "conversation.completed" && !processed.size)) {
          dispatch({
            type: "PATCH_EVENT",
            id: e.id,
            patch: { status: "done", updated_at: isoNow() },
          });
        }
      }
    });

    setBusStatus("stable");
    setGlobalStatus("reflecting");
    await new Promise((r) => setTimeout(r, 400));

    // Reflective side-effects: for the most recent conversation.completed
    // event, propose a memory candidate if none exists yet. This mirrors
    // the backend behavior documented in api-contract.md.
    const latest = stateRef.current.events
      .filter((e) => e.type === "conversation.completed")
      .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0];
    if (latest) {
      const userInput =
        (latest.payload as Record<string, unknown>)?.user_input ?? null;
      const exists = stateRef.current.memory.candidates.some(
        (c) => c.trace_id === latest.trace_id,
      );
      if (!exists && userInput && typeof userInput === "string") {
        dispatch({
          type: "PATCH_CANDIDATE",
          id: "__noop__", // unused; we append manually instead
          patch: {},
        });
        // We can't APPEND via reducer; trigger a re-fetch via refreshAll.
        void refreshAll();
      }
    }

    setGlobalStatus("writing_memory");
    await new Promise((r) => setTimeout(r, 300));
    setGlobalStatus("detecting_skills");
    await new Promise((r) => setTimeout(r, 300));
    setGlobalStatus("idle");
    setLastRun(isoNow());
    setLoading("background", false);

    // Refresh everything to pull any new state.
    void refreshAll();
  }, [
    setError,
    setGlobalStatus,
    setLastRun,
    setLoading,
    setBusStatus,
    refreshAll,
  ]);

  const approveCandidate = useCallback(
    (id: string) => {
      dispatch({
        type: "PATCH_CANDIDATE",
        id,
        patch: { status: "committed", committed_at: isoNow() },
      });
      dispatch({ type: "APPEND_BACKUP_AT", index: 0 });
      // Move into project memory.
      const cand = stateRef.current.memory.candidates.find((c) => c.id === id);
      if (cand) {
        const newEntry = {
          id: cand.id,
          source: cand.source,
          content: cand.content,
          trace_id: cand.trace_id ?? null,
          created_at: cand.created_at,
          committed_at: isoNow(),
        };
        dispatch({
          type: "SET_MEMORY",
          memory: {
            ...stateRef.current.memory,
            candidates: stateRef.current.memory.candidates.map((c) =>
              c.id === id ? { ...c, status: "committed" } : c,
            ),
            project: [...stateRef.current.memory.project, newEntry],
          },
          source: stateRef.current.ui.dataMode,
        });
      }
    },
    [],
  );

  const rejectCandidate = useCallback((id: string) => {
    dispatch({ type: "PATCH_CANDIDATE", id, patch: { status: "rejected" } });
  }, []);

  const approveSkill = useCallback((id: string) => {
    dispatch({ type: "PATCH_PENDING", id, status: "approved" });
  }, []);
  const rejectSkill = useCallback((id: string) => {
    dispatch({ type: "PATCH_PENDING", id, status: "rejected" });
  }, []);

  const resolvePermission = useCallback(
    (id: string, decision: "allow" | "deny") => {
      dispatch({ type: "RESOLVE_PERMISSION", id, decision });
    },
    [],
  );

  const selectTrace = useCallback(
    (id: string | null) => dispatch({ type: "SELECT_TRACE", id }),
    [],
  );
  const selectPermission = useCallback(
    (id: string | null) => dispatch({ type: "SELECT_PERMISSION", id }),
    [],
  );

  // Derived selectors
  const busCounts = useMemo(() => {
    const c = { pending: 0, processing: 0, done: 0, failed: 0 };
    for (const e of state.events) c[e.status] += 1;
    return c;
  }, [state.events]);

  return {
    state,
    dispatch,
    refreshAll,
    sendMessage,
    runBackground,
    approveCandidate,
    rejectCandidate,
    approveSkill,
    rejectSkill,
    resolvePermission,
    selectTrace,
    selectPermission,
    busCounts,
  };
}

export type Store = ReturnType<typeof useStore>;
