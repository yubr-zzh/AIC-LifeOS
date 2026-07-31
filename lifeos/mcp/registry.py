class MCPRegistry:
    def __init__(self):
        self.servers = {}

    def register(self, name, adapter):
        self.servers[name] = adapter

    def get(self, name):
        return self.servers.get(name)

