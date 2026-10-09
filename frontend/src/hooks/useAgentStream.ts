// SSE 生命周期 + 全部上行动作。与 agentStore 配对使用。
//
// 预览判定（11.1 的硬规则）：只有 URL 显式带 ?agentPreview=1 才用假帧源。
// Bridge 离线时**不回落 mock**——回落会让用户以为 Agent 在跑。

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  answerQuestion,
  closeSession,
  createSession,
  decidePermission,
  interruptSession,
  listAgents,
  openAgentStream,
  sendInstructions,
  setPermissionMode,
  type StreamHandle,
} from "../api/agentClient";
import { mockFrameStream } from "../api/agentMock";
import {
  BridgeError,
  MAX_INSTRUCTION_CHARS,
  type AnswerRequest,
  type CreateSessionRequest,
  type DecideRequest,
  type DownFrame,
  type PermissionMode,
} from "../api/agentTypes";
import { duquLayout, type AgentStore } from "../state/agentStore";

export function isPreviewMode(): boolean {
  if (typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).get("agentPreview") === "1";
}

export interface AgentActions {
  preview: boolean;
  busy: string | null;
  act: {
    refreshAgents: () => Promise<void>;
    connect: (a: CreateSessionRequest) => Promise<string>;
    send: (a: string, b: { text?: string; instructions?: string[] }) => Promise<void>;
    decide: (a: string, b: DecideRequest) => Promise<void>;
    answer: (a: string, b: AnswerRequest) => Promise<void>;
    interrupt: (a: string) => Promise<void>;
    close: (a: string) => Promise<void>;
    setMode: (a: string, b: PermissionMode) => Promise<void>;
  };
}

export function useAgentStream(store: AgentStore): AgentActions {
  const { dispatch, lastSeq } = store;
  const [preview] = useState(isPreviewMode);
  const [busy, setBusy] = useState<string | null>(null);
  const handle = useRef<StreamHandle | null>(null);

  // 布局初值从 localStorage 取，之后由 reducer 管。
  useEffect(() => {
    dispatch({ type: "LAYOUT", layout: duquLayout(), manual: false });
  }, [dispatch]);

  useEffect(() => {
    const fake = preview ? mockFrameStream() : undefined;
    handle.current = openAgentStream({
      fake,
      lastSeq,
      onFrame: (frame: DownFrame) => dispatch({ type: "FRAME", frame }),
      onState: (conn, msg) => dispatch({ type: "CONN", conn, msg }),
    });
    return () => {
      handle.current?.close();
      handle.current = null;
    };
  }, [dispatch, lastSeq, preview]);

  const wrap = useCallback(async <T,>(ming: string, fn: () => Promise<T>): Promise<T> => {
    setBusy(ming);
    try {
      return await fn();
    } finally {
      setBusy(null);
    }
  }, []);

  const huo = useCallback(
    (e: unknown): string =>
      e instanceof BridgeError
        ? e.message
        : e instanceof Error
          ? e.message
          : String(e),
    [],
  );

  const act = useMemo(
    () => ({
      refreshAgents: () =>
        wrap("agents", async () => {
          if (preview) return;
          try {
            dispatch({ type: "CATALOG", catalog: await listAgents() });
          } catch (e) {
            dispatch({ type: "CATALOG", catalog: null });
            dispatch({ type: "CONN", conn: "offline", msg: huo(e) });
          }
        }),

      connect: (a: CreateSessionRequest) =>
        wrap("connect", async () => {
          if (preview) {
            dispatch({ type: "CONN", conn: "open", msg: "预览模式，未连接真实 Bridge" });
            return "preview";
          }
          // 幂等键防双击建两个会话——两个 claude 进程会在同一个 cwd 里并行改文件。
          const hui = await createSession({
            ...a,
            clientIdempotencyKey:
              a.clientIdempotencyKey ?? `${a.agentId}:${a.cwd}:${a.permissionMode ?? "manual"}`,
          });
          dispatch({ type: "SESSION", session: hui });
          return hui.sessionId;
        }),

      send: (a: string, b: { text?: string; instructions?: string[] }) =>
        wrap("send", async () => {
          const zhi = b.instructions ?? (b.text ? [b.text] : []);
          if (zhi.length === 0) return;
          const guo = zhi.find((t) => t.length > MAX_INSTRUCTION_CHARS);
          if (guo) throw new Error(`单条指令超过 ${MAX_INSTRUCTION_CHARS} 字符，请先拆短`);
          await sendInstructions(a, { text: b.text, instructions: b.instructions });
        }),

      decide: (a: string, b: DecideRequest) =>
        wrap("decide", async () => {
          await decidePermission(a, b);
        }),

      answer: (a: string, b: AnswerRequest) =>
        wrap("answer", async () => {
          await answerQuestion(a, b);
        }),

      interrupt: (a: string) => wrap("interrupt", async () => void (await interruptSession(a))),

      close: (a: string) => wrap("close", async () => void (await closeSession(a))),

      setMode: (a: string, b: PermissionMode) =>
        wrap("mode", async () => {
          await setPermissionMode(a, b);
        }),
    }),
    [dispatch, huo, preview, wrap],
  );

  return { preview, busy, act };
}
