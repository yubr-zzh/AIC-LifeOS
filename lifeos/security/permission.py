class PermissionManager:
    HIGH_RISK_ACTIONS = {"write_file", "delete_file", "send_email", "install_skill"}

    async def review_tool_execution(self, tool_call):
        action = tool_call.get("name") or tool_call.get("action")
        if action in self.HIGH_RISK_ACTIONS:
            return {
                "decision": "requires_confirmation",
                "reason": f"{action} is a high-risk action",
            }
        return {"decision": "allow", "reason": "low-risk action"}

    async def review_skill_installation(self, candidate):
        risk = candidate.get("risk", "low")
        if risk == "high":
            return {
                "decision": "requires_confirmation",
                "reason": "high-risk skill candidate",
            }
        return {"decision": "allow", "reason": "candidate can enter pending registry"}

