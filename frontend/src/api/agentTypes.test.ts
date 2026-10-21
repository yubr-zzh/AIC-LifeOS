import { describe, expect, it } from "vitest";
import { permissionModeLabel } from "./agentTypes";

describe("permissionModeLabel", () => {
  it("Claude Code 使用官方模式名", () => {
    expect(permissionModeLabel("claude-code", "manual")).toBe("Manual (default)");
    expect(permissionModeLabel("claude-code", "acceptEdits")).toBe("Accept edits");
  });

  it("Codex 使用 sandbox 模式名", () => {
    expect(permissionModeLabel("codex", "manual")).toBe("read-only");
    expect(permissionModeLabel("codex", "acceptEdits")).toBe("workspace-write");
  });
});
