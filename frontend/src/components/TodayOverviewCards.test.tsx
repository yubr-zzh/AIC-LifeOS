import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { TodayOverviewCards } from "./TodayOverviewCards";

describe("TodayOverviewCards", () => {
  beforeEach(() => localStorage.clear());
  afterEach(cleanup);

  it("allows checking tasks and updates the progress card", () => {
    render(<TodayOverviewCards onViewPlan={() => undefined} />);

    const task = screen.getByRole("checkbox", { name: /整理项目反馈/ }) as HTMLInputElement;
    expect(task.checked).toBe(false);

    fireEvent.click(task);

    expect(task.checked).toBe(true);
    expect(screen.getByText("已完成 3 项，还有 1 项等待你的注意。")).toBeTruthy();
  });

  it("restores today's checked tasks after remounting", () => {
    const first = render(<TodayOverviewCards onViewPlan={() => undefined} />);
    fireEvent.click(screen.getByRole("checkbox", { name: /整理项目反馈/ }));
    first.unmount();

    render(<TodayOverviewCards onViewPlan={() => undefined} />);

    const restored = screen.getByRole("checkbox", { name: /整理项目反馈/ }) as HTMLInputElement;
    expect(restored.checked).toBe(true);
    expect(screen.getByText("已完成 3 项，还有 1 项等待你的注意。")).toBeTruthy();
  });
});