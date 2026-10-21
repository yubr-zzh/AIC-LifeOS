import { useEffect, useMemo, useReducer, useRef, useCallback } from "react";
import type {
  ChatAgentStatus,
  ChatResponse,
  AgentRoutingPolicy,
  EventBusStatus,
  EventRecord,
  GlobalAgentStatus,
  MemoryCandidate,
  MemoryStore,
  PermissionRequest,
  PipelineStageId,
  SkillRegistryState,
  ToolCall,
  ToolResult,
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
  ToolResult,
};
import {
  approvePendingSkill,
  commitMemoryCandidate,
  getEvents,
  getMemory,
  getPermissions,
  getSkills,
  getTrace,
  runBackgroundOnce,
  rejectMemoryCandidate,
  rejectPendingSkill,
  sendChat,
  submitFeedback,
} from "../api/client";
import type { FeedbackRating, MemoryScope } from "../api/types";
import type { DelegationPlan } from "../api/agentTypes";

export interface ChatAttachment {
  id: string;
  name: string;
  size: number;
  content: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  attachments?: ChatAttachment[];
  trace_id?: string;
  tool_calls?: ToolCall[];
  tool_results?: ToolResult[];
  // 委派计划属于产生它的那条消息，不属于全局状态。
  delegation?: DelegationPlan;
  decision?: ChatResponse["decision"];
  decision_reason?: string;
  decision_confidence?: number;
  agent_enabled?: boolean;
  plan_steps?: ChatResponse["plan_steps"];
  created_at: string;
  // execution status: pending until /chat returns, then succeeded/blocked.
  execution?: "pending" | "succeeded" | "blocked" | "error";
  error?: string;
  // user rating for this response, set after submitRating().
  feedback?: FeedbackRating | null;
  // true while a rating submission is in flight.
  feedbackSending?: boolean;
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
  | { type: "REPLACE_MESSAGES"; messages: ChatMessage[] }
  | { type: "APPEND_AGENT_SUMMARY"; text: string; traceId?: string | null }
  | { type: "UPDATE_MESSAGE"; id: string; patch: Partial<ChatMessage> }
  | { type: "PATCH_DELEGATION"; traceId: string; plan: DelegationPlan }
  | { type: "PIPELINE_ACTIVE"; stage: PipelineStageId | null }
  | { type: "PIPELINE_VISIT"; stages: PipelineStageId[] }
  | { type: "PIPELINE_RESET" }
  | { type: "SET_EVENTS"; events: EventRecord[]; source: "backend" | "preview" }
  | { type: "SET_MEMORY"; memory: MemoryStore; source: "backend" | "preview" }
  | { type: "SET_SKILLS"; skills: SkillRegistryState; source: "backend" | "preview" }
  | { type: "SET_PERMISSIONS"; permissions: PermissionRequest[]; source: "backend" | "preview" }
  | {
      type: "SET_FEEDBACK";
      messageId: string;
      rating: FeedbackRating | null;
      sending?: boolean;
    }
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
        "LifeOS 已就绪。发来一条消息，我会结合你的记忆回答，并把值得沉淀的内容交给后台整理。",
      created_at: isoNow(),
    },
  ],
  events: [],
  memory: {
    user: [],
    project: [],
    feedback: [],
    reference: [],
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
    case "REPLACE_MESSAGES":
      return { ...state, messages: action.messages };
    // 7.7.1 决策回路的前端落点：Agent 每条指令的结果以独立一条消息回到左侧对话。
    // 单向依赖——agentStore 写这里，主 store 不认识 Agent 域。
    case "APPEND_AGENT_SUMMARY":
      return {
        ...state,
        messages: [
          ...state.messages,
          {
            id: rid("agt"),
            role: "assistant",
            content: action.text,
            trace_id: action.traceId ?? undefined,
            created_at: isoNow(),
            execution: "succeeded",
          },
        ],
      };
    // 委派计划的勾选与编辑就地改在那条消息上，计划的归属不能漂。
    case "PATCH_DELEGATION":
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.trace_id === action.traceId ? { ...m, delegation: action.plan } : m,
        ),
      };
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
    case "SET_MEMORY":
      return { ...state, memory: action.memory };
    case "SET_SKILLS":
      return { ...state, skills: action.skills };
    case "SET_PERMISSIONS":
      return { ...state, permissions: action.permissions };
    case "SET_FEEDBACK":
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === action.messageId
            ? {
                ...m,
                feedback: action.rating,
                feedbackSending: action.sending ?? false,
              }
            : m,
        ),
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
    return { anyPreview, allBackend, events: evR.events };
  }, [setLoading]);

  // Initial load.
  useEffect(() => {
    refreshAll().catch((e) => setError(String(e)));
  }, [refreshAll, setError]);

  const sendMessage = useCallback(
    async (text: string, memoryScope?: MemoryScope, sessionId?: string,
      routingPolicy: AgentRoutingPolicy = "auto", attachments: ChatAttachment[] = []) => {
      const trimmed = text.trim();
      if (!trimmed && attachments.length === 0) return;

      const userMsg: ChatMessage = {
        id: rid("msg"),
        role: "user",
        content: trimmed,
        attachments,
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
        const attachmentContext = attachments.length
          ? `\n\n附件内容：\n${attachments.map((file) => `--- ${file.name} ---\n${file.content}`).join("\n\n")}`
          : "";
        chatRes = await sendChat(`${trimmed}${attachmentContext}`.trim(), undefined, memoryScope, sessionId, routingPolicy);
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
          tool_results: chatRes.tool_results,
          delegation: chatRes.delegation,
          decision: chatRes.decision,
          decision_reason: chatRes.decision_reason,
          decision_confidence: chatRes.decision_confidence,
          agent_enabled: chatRes.agent_enabled,
          plan_steps: chatRes.plan_steps,
          execution: chatRes.tool_results?.some((result) => result.status === "blocked") ? "blocked" : "succeeded",
        },
      });
      setUi({ selectedTraceId: chatRes.trace_id });

      const eventSnapshot = await getEvents();
      dispatch({ type: "SET_EVENTS", events: eventSnapshot.events, source: eventSnapshot.source });
      setBusStatus(eventSnapshot.events.some((event) => event.status === "failed") ? "failed" : "queued");
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
      stages: ["event_bus", "global_agent"],
    });

    let processedCount = 0;
    try {
      const result = await runBackgroundOnce();
      processedCount = result.processed.length;
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(`background failed: ${msg}`);
      setGlobalStatus("idle");
      setLoading("background", false);
      return;
    }

    const snapshot = await refreshAll();
    setBusStatus(snapshot.events.some((event) => event.status === "failed") ? "failed" :
      snapshot.events.some((event) => event.status === "pending") ? "queued" : "stable");
    if (processedCount > 0) {
      setGlobalStatus("reflecting");
      await new Promise((r) => setTimeout(r, 400));
    }
    setGlobalStatus("idle");
    setLastRun(isoNow());
    setLoading("background", false);

  }, [
    setError,
    setGlobalStatus,
    setLastRun,
    setLoading,
    setBusStatus,
    refreshAll,
  ]);

  const submitRating = useCallback(
    async (messageId: string, rating: FeedbackRating) => {
      const msg = stateRef.current.messages.find((m) => m.id === messageId);
      if (!msg || msg.role !== "assistant") return;
      if (msg.feedback === rating) {
        return;
      }
      dispatch({ type: "SET_FEEDBACK", messageId, rating, sending: true });
      try {
        await submitFeedback({
          rating,
          trace_id: msg.trace_id ?? null,
          note: "",
        });
        dispatch({ type: "SET_FEEDBACK", messageId, rating });
      } catch (err) {
        const m = err instanceof Error ? err.message : String(err);
        setError(`feedback failed: ${m}`);
        dispatch({ type: "SET_FEEDBACK", messageId, rating: null });
      }
    },
    [setError],
  );

  const performAction = useCallback(async (action: () => Promise<unknown>) => {
    try {
      setError(null);
      await action();
      await refreshAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [refreshAll, setError]);

  const approveCandidate = useCallback((id: string) =>
    performAction(() => commitMemoryCandidate(id)), [performAction]);
  const rejectCandidate = useCallback((id: string) =>
    performAction(() => rejectMemoryCandidate(id)), [performAction]);
  const approveSkill = useCallback((id: string) =>
    performAction(() => approvePendingSkill(id)), [performAction]);
  const rejectSkill = useCallback((id: string) =>
    performAction(() => rejectPendingSkill(id)), [performAction]);

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
    submitRating,
    approveCandidate,
    rejectCandidate,
    approveSkill,
    rejectSkill,
    selectTrace,
    selectPermission,
    busCounts,
  };
}

export type Store = ReturnType<typeof useStore>;
