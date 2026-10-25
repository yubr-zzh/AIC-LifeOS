import { afterEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ResizableChatSplit } from "./ResizableChatSplit";

afterEach(() => localStorage.clear());

describe("ResizableChatSplit", () => {
  it("通过键盘调整两侧宽度并保存比例", () => {
    render(<ResizableChatSplit chat={<div>LifeOS 对话</div>} agent={<div>Agent 对话</div>} />);
    const separator = screen.getByRole("separator", { name: "调整对话与 Agent 面板宽度" });
    expect(separator.getAttribute("aria-valuenow")).toBe("68");
    fireEvent.keyDown(separator, { key: "ArrowLeft" });
    expect(separator.getAttribute("aria-valuenow")).toBe("66");
    expect(localStorage.getItem("lifeos.chat.splitRatio.v1")).toBe("0.66");
  });

  it("双击恢复默认宽度", () => {
    render(<ResizableChatSplit chat={<div>对话</div>} agent={<div>Agent</div>} />);
    const separator = screen.getByRole("separator");
    fireEvent.keyDown(separator, { key: "End" });
    expect(separator.getAttribute("aria-valuenow")).toBe("78");
    fireEvent.doubleClick(separator);
    expect(separator.getAttribute("aria-valuenow")).toBe("68");
  });
});