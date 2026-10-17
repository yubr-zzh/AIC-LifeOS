import { describe, expect, it } from "vitest";
import { extractPlanItems } from "./planItems";

describe("extractPlanItems", () => {
  it("优先把 Markdown 列表提取成复盘检查项", () => {
    expect(extractPlanItems("## 今天\n- 完成课程阅读\n1. 整理项目反馈\n普通说明")).toEqual([
      "完成课程阅读",
      "整理项目反馈",
    ]);
  });

  it("没有列表时按非空行提取", () => {
    expect(extractPlanItems("完成课程阅读\n\n整理项目反馈")).toEqual(["完成课程阅读", "整理项目反馈"]);
  });
});