import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CopyTextButton } from "./CopyTextButton";

describe("CopyTextButton", () => {
  it("复制文本并给出已复制反馈", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    render(<CopyTextButton text="需要复制的内容" />);

    fireEvent.click(screen.getByRole("button", { name: "复制" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("需要复制的内容"));
    expect(screen.getByRole("button", { name: "已复制" })).toBeTruthy();
  });
});
