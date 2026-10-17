import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import * as client from "../api/client";
import { AgentMemoryCapture } from "./AgentMemoryCapture";

describe("AgentMemoryCapture", () => {
  it("点击叉号会关闭记忆面板", async () => {
    vi.spyOn(client, "listAgentEvidence").mockResolvedValue([]);
    const onClose = vi.fn();
    render(<AgentMemoryCapture sessionId="s-1" onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "关闭记忆面板" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});