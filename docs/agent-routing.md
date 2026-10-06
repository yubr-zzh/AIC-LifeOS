# Agent Routing

LifeOS decides whether a request should use an execution Agent before the
foreground executor is called.

## Route decisions

| Decision | Meaning |
| --- | --- |
| `self_plan` | Return structured planning steps to the user. The executor is skipped. |
| `agent` | Continue into the execution layer. Tool calls still pass through permission review. |

## Policies

`POST /chat` accepts an optional `routing_policy`:

| Policy | Behavior |
| --- | --- |
| `auto` | Rules, optional plugin, and model routing are combined. |
| `force_self_plan` | Never enters the Agent executor. |
| `force_agent` | Enters the Agent executor regardless of the automatic route. |

## Routing order

1. Explicit user override.
2. Deterministic file / command / external-side-effect guardrails.
3. Optional external router plugin.
4. Active model assessment for ambiguous requests.
5. Conservative `self_plan` fallback.

A high-confidence side-effect guardrail wins over a conflicting model result.

## External router plugin contract

The planner discovers Python entry points in the
`lifeos.agent_routers` group. A router can also be supplied explicitly:

```bash
LIFEOS_AGENT_ROUTER_PLUGIN=my_package.router:MyRouter
```

A plugin exposes either a callable or a `classify(payload)` method. It may be
synchronous or asynchronous and returns:

```json
{
  "decision": "agent",
  "confidence": 0.94,
  "reason": "需要运行命令并修改文件",
  "requires_side_effects": true,
  "signals": ["filesystem", "command"],
  "steps": [
    {
      "title": "检查项目",
      "detail": "读取构建配置",
      "time": "今天"
    }
  ]
}
```

The payload contains `user_input`, retrieved `memory`, and `routing_policy`.

## Evaluated packages

- `semantic-router` is a semantic utterance router. It can be adapted through
  the plugin hook, but it does not encode Agent side-effect policy.
- `RouteLLM` selects between language models. It does not decide whether an
  executor should run.
- `LangGraph` is an orchestration framework. It could build a router, but it is
  not itself a drop-in Agent-necessity classifier.

No third-party routing package is installed by default. This keeps the core
runtime lightweight and avoids adding a model/ML dependency that does not
directly model execution side effects.

## Repeatable evaluation

Run the routing matrix against the original local frontend domain:

```bash
python tools/evaluate_agent_routing.py --rounds 3
```

The command reports the expected route, actual route, routing source,
confidence, and latency for every experiment.
