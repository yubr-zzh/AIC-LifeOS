import { describe, expect, it } from "vitest";
import { lianDai } from "./DelegationCard";
import type { DelegationItem } from "../api/agentTypes";

const tiao = (a: Partial<DelegationItem> & { itemId: string }): DelegationItem => ({
  order: 1, title: "", instruction: "", dependsOn: [], editable: true, enabled: true,
  status: "pending", ...a,
});

describe("R-V3 依赖闭包", () => {
  it("取消一条会连带取消直接依赖它的", () => {
    const a = [tiao({ itemId: "i-1" }), tiao({ itemId: "i-2", dependsOn: ["i-1"] })];
    lianDai(a, "i-1");
    expect(a[1].enabled).toBe(false);
    expect(a[1].note).toContain("i-1");
  });

  it("传递依赖也一起取消，不只走一层", () => {
    const a = [
      tiao({ itemId: "i-1" }),
      tiao({ itemId: "i-2", dependsOn: ["i-1"] }),
      tiao({ itemId: "i-3", dependsOn: ["i-2"] }),
      tiao({ itemId: "i-4", dependsOn: ["i-9"] }),
    ];
    lianDai(a, "i-1");
    expect(a[1].enabled).toBe(false);
    expect(a[2].enabled).toBe(false);
    expect(a[3].enabled).toBe(true); // 与被取消的无关，不该动
  });

  it("环状依赖不会死循环（a 依赖 b、b 依赖 a 时也能收敛）", () => {
    const a = [tiao({ itemId: "i-1" }), tiao({ itemId: "i-2", dependsOn: ["i-1"] })];
    a[0].dependsOn = ["i-2"];
    lianDai(a, "i-1");
    expect(a[1].enabled).toBe(false);
  });
});
