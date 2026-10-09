import { describe, expect, it } from "vitest";
import { sendChat } from "./client";

describe("sendChat", () => {
  it("parses route metadata from the chat response", async () => {
    const fetchImpl = (async () => new Response(JSON.stringify({
      trace_id: "trace-2", response: "done", decision: "agent", decision_reason: "tool use needed",
      decision_confidence: 0.9, agent_enabled: true, route_source: "rules", route_signals: ["shell"],
      requires_side_effects: true, routing_policy: "auto", plan_steps: [{ id: 1, title: "Inspect" }],
    }), { status: 200, headers: { "content-type": "application/json" } })) as typeof fetch;

    const result = await sendChat("run tests", { fetchImpl });
    expect(result.decision).toBe("agent");
    expect(result.decision_confidence).toBe(0.9);
    expect(result.route_signals).toEqual(["shell"]);
    expect(result.plan_steps).toEqual([{ id: 1, title: "Inspect" }]);
  });

  it("sends the selected Agent session and project scope to LifeOS", async () => {
    let payload: unknown;
    const fetchImpl = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      payload = JSON.parse(String(init?.body));
      return new Response(JSON.stringify({ trace_id: "trace-1", response: "ok" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }) as typeof fetch;

    await sendChat("继续", { baseUrl: "http://localhost:8765", fetchImpl },
      { kind: "project", project_id: "lifeos" }, "agent-session-1");

    expect(payload).toEqual({
      message: "继续",
      memory_scope: { kind: "project", project_id: "lifeos" },
      session_id: "agent-session-1",
      routing_policy: "auto",
    });
  });
});
