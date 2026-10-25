import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../api/agentClient", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/agentClient")>();
  return {
    ...actual,
    sendInstructions: vi.fn(),
    openAgentStream: vi.fn(() => ({ close: vi.fn() })),
  };
});

import { sendInstructions } from "../api/agentClient";
import { useAgentStream } from "./useAgentStream";
import type { AgentStore } from "../state/agentStore";

describe("useAgentStream 发送后的即时对话", () => {
  it("HTTP 已入队后立刻写入一条用户消息，不等下一次快照", async () => {
    vi.mocked(sendInstructions).mockResolvedValue({ messageId: "m-user-1", seq: 7 });
    const dispatch = vi.fn();
    const store = {
      dispatch,
      lastSeq: () => 0,
    } as unknown as AgentStore;
    const { result } = renderHook(() => useAgentStream(store));

    await act(async () => {
      await result.current.act.send("s-1", { text: "我现在能看到这句话" });
    });

    expect(dispatch).toHaveBeenCalledWith({
      type: "FRAME",
      frame: expect.objectContaining({
        type: "message",
        sessionId: "s-1",
        message: expect.objectContaining({
          messageId: "m-user-1",
          seq: 7,
          role: "user",
          kind: "text",
          text: "我现在能看到这句话",
        }),
      }),
    });
  });
});
