from lifeos.agent.chat.runtime import ChatRuntime
from lifeos.agent.context import AgentContextStore
from lifeos.agent.executor.executor import Executor
from lifeos.agent.planner.planner import Planner
from lifeos.event.bus import ReliableEventBus
from lifeos.memory.manager import MemoryManager
from lifeos.memory.agent_evidence import AgentEvidenceStore
from lifeos.memory.providers.tencentdb import TencentDBConfig, TencentDBMemoryAdapter
from lifeos.reflection.engine import ReflectionEngine
from lifeos.security.permission import PermissionManager
from lifeos.skills.detector import SkillDetector
from lifeos.skills.registry import SkillRegistry
from lifeos.trace.system import TraceSystem


class LifeOSAgent:
    """Top-level composition root for foreground and background agents."""

    def __init__(self, llm, storage_dir=".lifeos", delegation_enabled=True, external_memory=None):
        self.llm = llm
        self.memory = MemoryManager(storage_dir=storage_dir)
        self.agent_evidence = AgentEvidenceStore(storage_dir=storage_dir)
        if external_memory is None:
            config = TencentDBConfig.from_env()
            external_memory = TencentDBMemoryAdapter(config) if config else None
        self.external_memory = external_memory
        self.trace = TraceSystem()
        self.event_bus = ReliableEventBus(f"{storage_dir}/events.json")
        self.skills = SkillRegistry(f"{storage_dir}/skills.json")
        self.permission = PermissionManager()
        self.planner = Planner(llm)
        self.executor = Executor(
            llm,
            skill_registry=self.skills,
            permission_manager=self.permission,
            trace=self.trace,
        )
        # 7.7.1 决策回路的上下文存储。Bridge 回调 /api/agent-events 时往里追加，
        # /chat 时取出来进大模型上下文。
        self.agent_context = AgentContextStore()
        self.chat = ChatRuntime(
            llm=llm,
            memory=self.memory,
            executor=self.executor,
            event_bus=self.event_bus,
            trace=self.trace,
            external_memory=self.external_memory,
            agent_context=self.agent_context,
            # 之前 planner 在这里被实例化却没人用。接上之后它才不是死代码。
            planner=self.planner,
            delegation_enabled=delegation_enabled,
        )
        self.global_agent = GlobalAgentRuntime(
            event_bus=self.event_bus,
            memory=self.memory,
            reflection=ReflectionEngine(llm),
            skill_detector=SkillDetector(
                llm,
                event_bus=self.event_bus,
                memory=self.memory,
            ),
            skill_registry=self.skills,
            permission=self.permission,
            trace=self.trace,
        )

    async def run(self, user_input: str, session_id: str | None = None, memory_scope=None):
        return await self.chat.handle_message(
            user_input, session_id=session_id, memory_scope=memory_scope
        )

    def agent_event(self, kind: str, session_id: str | None, detail: dict,
                    event_id: str | None = None, owner_id: str | None = None) -> str:
        """接收 Bridge 回调的决策回路事件（7.7.1）。

        **只往上下文里追加文本**，绝不产生指向 Bridge 的出站调用。
        返回写进上下文的那句话，方便端点回给 Bridge 做日志。
        """
        summary = self.agent_context.tian_jia(session_id or "default", kind, detail or {})
        if kind == "agent.result" and event_id and owner_id and session_id and summary:
            self.agent_evidence.record(
                event_id=event_id, owner_id=owner_id, session_id=session_id,
                summary=summary,
            )
        return summary

    async def run_background_once(self, limit=10):
        return await self.global_agent.process_once(limit=limit)

    async def submit_feedback(self, rating, trace_id=None, note=""):
        """Record a user rating for an assistant response.

        Writes the feedback into the durable event bus (so the Global
        Agent can reflect on it) and straight into the feedback memory
        category (so it is immediately visible in the Memory panel).
        """
        payload = {
            "rating": rating,
            "note": note,
            "trace_id": trace_id,
        }
        event = await self.event_bus.publish("feedback.submitted", payload, trace_id=trace_id)
        await self.memory.propose_update(
            source="user_feedback",
            content=payload,
            trace_id=trace_id,
            source_event_id=event.id,
        )
        return {"ok": True, "rating": rating, "trace_id": trace_id}


class GlobalAgentRuntime:
    """Background maintainer that consumes reliable events by type."""

    def __init__(
        self,
        event_bus,
        memory,
        reflection,
        skill_detector,
        skill_registry,
        permission,
        trace,
    ):
        self.event_bus = event_bus
        self.memory = memory
        self.reflection = reflection
        self.skill_detector = skill_detector
        self.skill_registry = skill_registry
        self.permission = permission
        self.trace = trace
        self.handlers = {
            "conversation.completed": self._handle_conversation_completed,
            "memory.write.requested": self._handle_memory_write_requested,
            "skill.candidate.created": self._handle_skill_candidate_created,
            "feedback.submitted": self._handle_feedback_submitted,
        }

    async def process_once(self, limit=10):
        processed = []
        for event in await self.event_bus.poll(limit=limit):
            await self.event_bus.mark_processing(event.id)
            try:
                handler = self.handlers.get(event.type)
                if handler is None:
                    raise ValueError(f"no handler for event type: {event.type}")
                await handler(event)
                await self.event_bus.mark_done(event.id)
                processed.append(event.id)
            except Exception as exc:
                await self.event_bus.mark_failed(event.id, str(exc))
        return processed

    async def _handle_conversation_completed(self, event):
        reflection = await self.reflection.reflect(event.payload)
        await self.memory.propose_update(
            source="reflection",
            content=reflection,
            trace_id=event.trace_id,
            source_event_id=event.id,
        )
        candidates = await self.skill_detector.detect(event.payload)
        for candidate in candidates:
            if any(
                existing.type == "skill.candidate.created"
                and existing.payload.get("source_event_id") == event.id
                and existing.payload.get("candidate", {}).get("name") == candidate.get("name")
                for existing in self.event_bus.all_events()
            ):
                continue
            await self.event_bus.publish(
                "skill.candidate.created",
                {"candidate": candidate, "source_event_id": event.id},
                trace_id=event.trace_id,
            )

    async def _handle_memory_write_requested(self, event):
        await self.memory.commit_candidate(event.payload["candidate_id"])

    async def _handle_skill_candidate_created(self, event):
        candidate = event.payload["candidate"]
        # Skip if the same skill is already pending or approved.
        existing = await self.skill_registry.find_any(candidate.get("name"))
        if existing is not None:
            return
        review = await self.permission.review_skill_installation(candidate)
        if review["decision"] != "deny":
            await self.skill_registry.add_pending(candidate, review=review)

    async def _handle_feedback_submitted(self, event):
        """Run feedback analysis over recent feedback memory entries.

        Combines committed feedback entries with uncommitted
        user_feedback candidates so the analysis reflects the latest
        ratings even before the user approves the memory candidates.
        """
        await self.memory.propose_update(
            source="user_feedback",
            content=event.payload,
            trace_id=event.trace_id,
            source_event_id=event.id,
        )
        store = self.memory._read()
        feedback_entries = list(store.get("feedback", []))
        for candidate in store.get("candidates", []):
            if candidate.get("source") == "user_feedback" and candidate.get("status") == "candidate":
                feedback_entries.append(
                    {
                        "content": candidate.get("content", {}),
                        "created_at": candidate.get("created_at"),
                    }
                )
        analysis = await self.reflection.analyze_feedback(feedback_entries)
        # Persist the aggregated analysis as a memory candidate so it is
        # auditable in the Memory panel and can be committed by the user.
        await self.memory.propose_update(
            source="feedback_analysis",
            content=analysis,
            trace_id=event.trace_id,
            source_event_id=event.id,
        )
