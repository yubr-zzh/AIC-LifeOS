import { useEffect, useMemo, useReducer, useRef, useCallback } from "react";
import type {
  AgentRoutingPolicy,
  ChatAgentStatus,
  ChatResponse,
  EventBusStatus,
  EventRecord,
  GlobalAgentStatus,
  MemoryCandidate,
  MemoryStore,
  MemoryScope,
  ModelCatalog,
  ModelProfile,
  ModelProfileInput,
  ModelTestResult,
  PermissionRequest,
  PipelineStageId,
  PlanStep,
  PlanningDecision,
  SkillRegistryState,
  ToolCall,
  ToolResult,
} from "../api/types";

// Re-export domain types so panels can import everything from the store.
export type {
  AgentRoutingPolicy,
  ChatAgentStatus,
  EventBusStatus,
  EventRecord,
  GlobalAgentStatus,
  MemoryCandidate,
  MemoryStore,
  ModelCatalog,
  ModelProfile,
  PermissionRequest,
  PipelineStageId,
  PlanStep,
  PlanningDecision,
  SkillRegistryState,
  ToolCall,
  ToolResult,
};
import {
  activateModelProfile as activateModelProfileApi,
  approvePendingSkill,
  commitMemoryCandidate,
  deleteModelProfile as deleteModelProfileApi,
  getEvents,
  getMemory,
  getModels,
  getPermissions,
  getSkills,
  getTrace,
  runBackgroundOnce,
  rejectMemoryCandidate,
  rejectPendingSkill,
  saveModelProfile as saveModelProfileApi,
  sendChat,
  submitFeedback,
  testModelProfile as testModelProfileApi,
} from "../api/client";
import type { FeedbackRating } from "../api/types";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  decision?: PlanningDecision;
  decision_reason?: string;
  decision_confidence?: number;
  plan_steps?: PlanStep[];
  agent_enabled?: boolean;
  routing_policy?: AgentRoutingPolicy;
  route_source?: "user_override" | "rules" | "external_plugin" | "model" | "fallback";
  route_signals?: string[];
  requires_side_effects?: boolean;
  trace_id?: string;
  tool_calls?: ToolCall[];
  tool_results?: ToolResult[];
  provider?: string | null;
  model?: string | null;
  created_at: string;
  // execution status: pending until /chat returns, then succeeded/blocked.
  execution?: "pending" | "succeeded" | "blocked" | "error";
  error?: string;
  // user rating for this response, set after submitRating().
  feedback?: FeedbackRating | null;
  // true while a rating submission is in flight.
  feedbackSending?: boolean;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  pinned?: boolean;
  messages: ChatMessage[];
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
  conversations: Conversation[];
  activeConversationId: string;
  events: EventRecord[];
  memory: MemoryStore;
  skills: SkillRegistryState;
  permissions: PermissionRequest[];
  modelCatalog: ModelCatalog;
  pipeline: PipelineState;
  ui: UiState;
  loading: {
    chat: boolean;
    background: boolean;
    events: boolean;
    memory: boolean;
    skills: boolean;
    permissions: boolean;
    models: boolean;
  };
}

type Action =
  | { type: "SET_LOADING"; key: keyof AppState["loading"]; value: boolean }
  | { type: "SET_UI"; patch: Partial<UiState> }
  | { type: "SET_CHAT_STATUS"; status: ChatAgentStatus }
  | { type: "SET_BUS_STATUS"; status: EventBusStatus }
  | { type: "SET_GLOBAL_STATUS"; status: GlobalAgentStatus }
  | { type: "APPEND_MESSAGE"; message: ChatMessage; conversationId?: string }
  | { type: "UPDATE_MESSAGE"; id: string; patch: Partial<ChatMessage> }
  | { type: "CREATE_CONVERSATION"; conversation: Conversation }
  | { type: "SELECT_CONVERSATION"; id: string }
  | { type: "PIPELINE_ACTIVE"; stage: PipelineStageId | null }
  | { type: "PIPELINE_VISIT"; stages: PipelineStageId[] }
  | { type: "PIPELINE_RESET" }
  | { type: "SET_EVENTS"; events: EventRecord[]; source: "backend" | "preview" }
  | { type: "SET_MEMORY"; memory: MemoryStore; source: "backend" | "preview" }
  | { type: "SET_SKILLS"; skills: SkillRegistryState; source: "backend" | "preview" }
  | { type: "SET_PERMISSIONS"; permissions: PermissionRequest[]; source: "backend" | "preview" }
  | { type: "SET_MODELS"; catalog: ModelCatalog; source: "backend" | "preview" }
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

const INITIAL_CONVERSATION_ID = "conversation-main";

function newConversation(id = rid("conv")): Conversation {
  const now = isoNow();
  return {
    id,
    title: "新的对话",
    created_at: now,
    updated_at: now,
    messages: [],
  };
}

function loadInitialChatState(): { conversations: Conversation[]; activeConversationId: string } {
  if (typeof window !== "undefined") {
    try {
      const raw = window.localStorage.getItem("lifeos-chat-history");
      if (raw) {
        const parsed = JSON.parse(raw) as { conversations?: Conversation[]; activeConversationId?: string };
        if (Array.isArray(parsed.conversations) && parsed.conversations.length > 0) {
          const conversations = parsed.conversations.filter((item) => item && typeof item.id === "string" && Array.isArray(item.messages));
          if (conversations.length > 0) {
            const activeConversationId = conversations.some((item) => item.id === parsed.activeConversationId)
              ? String(parsed.activeConversationId)
              : conversations[0].id;
            return { conversations, activeConversationId };
          }
        }
      }
    } catch {
      // Corrupt local history should never prevent the console from loading.
    }
  }
  const conversation = newConversation(INITIAL_CONVERSATION_ID);
  return { conversations: [conversation], activeConversationId: conversation.id };
}

const initialChatState = loadInitialChatState();

const initialState: AppState = {
  conversations: initialChatState.conversations,
  activeConversationId: initialChatState.activeConversationId,
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
  modelCatalog: {
    active_profile_id: "mock",
    profiles: [],
    presets: [],
  },
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
    models: false,
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
    case "APPEND_MESSAGE": {
      const conversationId = action.conversationId ?? state.activeConversationId;
      const autoTitle =
        action.message.role === "user"
          ? action.message.content.trim().replace(/\s+/g, " ").slice(0, 28) || "新的对话"
          : null;
      return {
        ...state,
        conversations: state.conversations.map((conversation) =>
          conversation.id === conversationId
            ? {
                ...conversation,
                title:
                  conversation.title === "新的对话" && autoTitle
                    ? autoTitle
                    : conversation.title,
                updated_at: action.message.created_at,
                messages: [...conversation.messages, action.message],
              }
            : conversation,
        ),
      };
    }
    case "UPDATE_MESSAGE":
      return {
        ...state,
        conversations: state.conversations.map((conversation) => ({
          ...conversation,
          messages: conversation.messages.map((message) =>
            message.id === action.id ? { ...message, ...action.patch } : message,
          ),
        })),
      };
    case "CREATE_CONVERSATION":
      return {
        ...state,
        conversations: [action.conversation, ...state.conversations],
        activeConversationId: action.conversation.id,
      };
    case "SELECT_CONVERSATION":
      return { ...state, activeConversationId: action.id };
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
    case "SET_MODELS":
      return { ...state, modelCatalog: action.catalog };
    case "SET_FEEDBACK":
      return {
        ...state,
        conversations: state.conversations.map((conversation) => ({
          ...conversation,
          messages: conversation.messages.map((message) =>
            message.id === action.messageId
              ? {
                  ...message,
                  feedback: action.rating,
                  feedbackSending: action.sending ?? false,
                }
              : message,
          ),
        })),
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
    setLoading("models", true);

    const [evR, memR, skR, perR, modelR] = await Promise.all([
      getEvents(),
      getMemory(),
      getSkills(),
      getPermissions(),
      getModels(),
    ]);

    dispatch({ type: "SET_EVENTS", events: evR.events, source: evR.source });
    dispatch({ type: "SET_MEMORY", memory: memR.data, source: memR.source });
    dispatch({ type: "SET_SKILLS", skills: skR.data, source: skR.source });
    dispatch({
      type: "SET_PERMISSIONS",
      permissions: perR.data,
      source: perR.source,
    });
    dispatch({ type: "SET_MODELS", catalog: modelR.data, source: modelR.source });

    const sources = [evR.source, memR.source, skR.source, perR.source, modelR.source];
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
    setLoading("models", false);
    return { anyPreview, allBackend, events: evR.events };
  }, [setLoading]);

  const refreshModels = useCallback(async () => {
    setLoading("models", true);
    try {
      const result = await getModels();
      dispatch({ type: "SET_MODELS", catalog: result.data, source: result.source });
      return result.data;
    } finally {
      setLoading("models", false);
    }
  }, [setLoading]);

  // Initial load.
  useEffect(() => {
    refreshAll().catch((e) => setError(String(e)));
  }, [refreshAll, setError]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(
        "lifeos-chat-history",
        JSON.stringify({
          conversations: state.conversations,
          activeConversationId: state.activeConversationId,
        }),
      );
    } catch {
      // Local history is a convenience; backend chat still works without it.
    }
  }, [state.conversations, state.activeConversationId]);

  const activeConversation = useMemo(
    () =>
      state.conversations.find((conversation) => conversation.id === state.activeConversationId) ??
      state.conversations[0],
    [state.activeConversationId, state.conversations],
  );

  const createConversation = useCallback(() => {
    const conversation = newConversation();
    dispatch({ type: "CREATE_CONVERSATION", conversation });
    return conversation.id;
  }, []);

  const selectConversation = useCallback(
    (id: string) => dispatch({ type: "SELECT_CONVERSATION", id }),
    [],
  );

  const sendMessage = useCallback(
    async (
      text: string,
      routingPolicy: AgentRoutingPolicy = "auto",
      memoryScope?: MemoryScope,
    ) => {
      const trimmed = text.trim();
      if (!trimmed) return;

      const userMsg: ChatMessage = {
        id: rid("msg"),
        role: "user",
        content: trimmed,
        created_at: isoNow(),
      };
      dispatch({
        type: "APPEND_MESSAGE",
        message: userMsg,
        conversationId: stateRef.current.activeConversationId,
      });
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
        conversationId: stateRef.current.activeConversationId,
      });

      let chatRes: ChatResponse;
      try {
        chatRes = await sendChat(
          trimmed,
          stateRef.current.modelCatalog.active_profile_id,
          routingPolicy,
          undefined,
          memoryScope,
        );
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
          provider: chatRes.provider,
          model: chatRes.model,
          decision: chatRes.decision,
          decision_reason: chatRes.decision_reason,
          decision_confidence: chatRes.decision_confidence,
          plan_steps: chatRes.plan_steps,
          agent_enabled: chatRes.agent_enabled,
          routing_policy: chatRes.routing_policy,
          route_source: chatRes.route_source,
          route_signals: chatRes.route_signals,
          requires_side_effects: chatRes.requires_side_effects,
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
      const msg = stateRef.current.conversations.flatMap((conversation) => conversation.messages).find((message) => message.id === messageId);
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

  const createModel = useCallback(async (profile: ModelProfileInput) => {
    const saved = await saveModelProfileApi(profile);
    await refreshModels();
    return saved;
  }, [refreshModels]);

  const updateModel = useCallback(async (profileId: string, profile: ModelProfileInput) => {
    const saved = await saveModelProfileApi(profile, profileId);
    await refreshModels();
    return saved;
  }, [refreshModels]);

  const activateModel = useCallback(async (profileId: string) => {
    const active = await activateModelProfileApi(profileId);
    await refreshModels();
    return active;
  }, [refreshModels]);

  const deleteModel = useCallback(async (profileId: string) => {
    await deleteModelProfileApi(profileId);
    await refreshModels();
  }, [refreshModels]);

  const testModel = useCallback(
    (profile: ModelProfileInput | string): Promise<ModelTestResult> =>
      testModelProfileApi(profile),
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
    activeConversation,
    createConversation,
    selectConversation,
    refreshAll,
    sendMessage,
    runBackground,
    submitRating,
    approveCandidate,
    rejectCandidate,
    approveSkill,
    rejectSkill,
    createModel,
    updateModel,
    activateModel,
    deleteModel,
    testModel,
    refreshModels,
    selectTrace,
    selectPermission,
    busCounts,
  };
}

export type Store = ReturnType<typeof useStore>;
