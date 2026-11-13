class AgentWorkflow:
    START = "start"
    STEP = "step"
    START_ID = "start-1"
    STEP_ID = "step-1"
    EDGE_ID = "edge-1"
    START_POSITION = {"x": 40, "y": 120}
    STEP_POSITION = {"x": 320, "y": 120}

    def __init__(self, data):
        self.data = data if isinstance(data, dict) else {}

    @classmethod
    def single(cls, prompt_name="", tools=(), force_tool_call=False, start_position=None, step_position=None):
        return {
            "nodes": [
                {
                    "id": cls.START_ID,
                    "type": cls.START,
                    "position": dict(start_position or cls.START_POSITION),
                    "data": {},
                },
                {
                    "id": cls.STEP_ID,
                    "type": cls.STEP,
                    "position": dict(step_position or cls.STEP_POSITION),
                    "data": {"name": prompt_name, "tools": list(tools), "force_tool_call": force_tool_call},
                },
            ],
            "edges": [{"id": cls.EDGE_ID, "source": cls.START_ID, "target": cls.STEP_ID, "data": {}}],
        }

    def nodes(self):
        nodes = self.data.get("nodes")
        return nodes if isinstance(nodes, list) else []

    def edges(self):
        edges = self.data.get("edges")
        return edges if isinstance(edges, list) else []

    def node(self, node_type):
        return next((node for node in self.nodes() if isinstance(node, dict) and node.get("type") == node_type), {})

    def start(self):
        return self.node(self.START)

    def step(self):
        return self.node(self.STEP)

    def step_data(self):
        data = self.step().get("data")
        return data if isinstance(data, dict) else {}

    @property
    def prompt_name(self):
        name = self.step_data().get("name")
        return name.strip() if isinstance(name, str) else ""

    @property
    def tools(self):
        tools = self.step_data().get("tools")
        return [name for name in tools if isinstance(name, str)] if isinstance(tools, list) else []

    @property
    def force_tool_call(self):
        return self.step_data().get("force_tool_call") is True

    @staticmethod
    def position(node, fallback):
        position = node.get("position")
        if not isinstance(position, dict):
            return dict(fallback)
        return {
            axis: position.get(axis) if isinstance(position.get(axis), (int, float)) else fallback[axis]
            for axis in ("x", "y")
        }

    def links_start_to_step(self, edge):
        return (
            isinstance(edge, dict)
            and edge.get("source") == self.start().get("id")
            and edge.get("target") == self.step().get("id")
        )

    def error(self, known_tools):
        if not isinstance(self.data.get("nodes"), list) or not isinstance(self.data.get("edges"), list):
            return "The workflow needs a list of nodes and a list of edges."
        if len(self.nodes()) != 2 or not self.start() or not self.step():
            return "The workflow needs exactly one start node and one step node."
        if len(self.edges()) != 1 or not self.links_start_to_step(self.edges()[0]):
            return "The workflow needs exactly one edge, from the start node to the step."
        if not self.prompt_name:
            return "The step needs a prompt name."
        unknown = [name for name in self.tools if name not in known_tools]
        if unknown:
            return f"Unknown tools: {', '.join(unknown)}."
        return ""

    def clean(self):
        return self.single(
            self.prompt_name,
            list(dict.fromkeys(self.tools)),
            self.force_tool_call,
            self.position(self.start(), self.START_POSITION),
            self.position(self.step(), self.STEP_POSITION),
        )
