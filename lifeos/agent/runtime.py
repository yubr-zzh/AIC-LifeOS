from lifeos.agent.chat.runtime import ChatRuntime
from lifeos.agent.executor.executor import Executor
from lifeos.agent.planner.planner import Planner
from lifeos.event.bus import ReliableEventBus
from lifeos.memory.manager import MemoryManager
from lifeos.reflection.engine import ReflectionEngine
from lifeos.security.permission import PermissionManager
from lifeos.skills.detector import SkillDetector
from lifeos.skills.registry import SkillRegistry
from lifeos.trace.system import TraceSystem


class LifeOSAgent:
    """Top-level composition root for foreground and background agents."""

    def __init__(self, llm, storage_dir=".lifeos"):
        self.llm = llm
        self.memory = MemoryManager(storage_dir=storage_dir)
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
        self.chat = ChatRuntime(
            llm=llm,
            memory=self.memory,
            executor=self.executor,
            event_bus=self.event_bus,
            trace=self.trace,
        )
        self.global_agent = GlobalAgentRuntime(
            event_bus=self.event_bus,
            memory=self.memory,
            reflection=ReflectionEngine(llm),
            skill_detector=SkillDetector(llm),
            skill_registry=self.skills,
            permission=self.permission,
            trace=self.trace,
        )

    async def run(self, user_input: str):
        return await self.chat.handle_message(user_input)

    async def run_background_once(self, limit=10):
        return await self.global_agent.process_once(limit=limit)


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
        )
        candidates = await self.skill_detector.detect(event.payload)
        for candidate in candidates:
            await self.event_bus.publish(
                "skill.candidate.created",
                {"candidate": candidate},
                trace_id=event.trace_id,
            )

    async def _handle_memory_write_requested(self, event):
        await self.memory.commit_candidate(event.payload["candidate_id"])

    async def _handle_skill_candidate_created(self, event):
        candidate = event.payload["candidate"]
        review = await self.permission.review_skill_installation(candidate)
        if review["decision"] == "allow":
            await self.skill_registry.add_pending(candidate, review=review)

