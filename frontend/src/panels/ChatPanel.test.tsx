import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { Store } from "../state/store";
import { ChatPanel } from "./ChatPanel";

const message = (id: string, content: string) => ({
  id, role: "user" as const, content, created_at: new Date().toISOString(),
});

function dummyStore(): Store {
  return {
    state: {
      messages: [],
      loading: { chat: false },
      ui: { dataMode: "preview" },
    },
    dispatch: vi.fn(),
    sendMessage: vi.fn(),
    refreshAll: vi.fn(),
    submitRating: vi.fn(),
  } as unknown as Store;
}

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("ChatPanel 会话删除", () => {
  it("每个历史会话都有删除按钮，删除后从列表消失", async () => {
    localStorage.setItem("lifeos.chat.history.v1", JSON.stringify([
      { id: "c-1", title: "第一次对话", updatedAt: new Date().toISOString(), messages: [message("m1", "一")] },
      { id: "c-2", title: "第二次对话", updatedAt: new Date().toISOString(), messages: [message("m2", "二")] },
    ]));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<ChatPanel store={dummyStore()} />);

    await waitFor(() => expect(screen.getByText("第二次对话")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "删除对话：第二次对话" }));
    expect(screen.queryByText("第二次对话")).toBeNull();
  });
});