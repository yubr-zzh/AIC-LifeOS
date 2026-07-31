class MCPAdapter:
    def __init__(self, name, tools=None):
        self.name = name
        self.tools = tools or {}

    async def call(self, tool_name, arguments):
        tool = self.tools.get(tool_name)
        if tool is None:
            raise KeyError(f"MCP tool not found: {tool_name}")
        result = tool(arguments)
        if hasattr(result, "__await__"):
            result = await result
        return result

