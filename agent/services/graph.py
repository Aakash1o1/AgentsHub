from langgraph.prebuilt import create_react_agent
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

from agent.services.tools import TOOL_REGISTRY
from agent.services.client import AgentClient




class AgentRunner:
    def __init__(self):
        self.client = AgentClient()


    def get_agent_graph(self, agent):
        compiled, config = self.client.get_prompt(agent.prompt_name)
        tools = [TOOL_REGISTRY[name] for name in agent.tools if name in TOOL_REGISTRY]
        return create_react_agent(self.client.get_llm(config), tools=tools, prompt=compiled)
    
    def pick_agent(self, question, vendor):
        agents = list(vendor.agents.filter(is_active=True))
        if not agents:
            return None

        menu = "\n".join(f"- {a.slug} : {a.description}" for a in agents)
        router_prompt = (
            "You are a router. Reply with EXACTLY ONE slug from this list, "
            "no punctuation:\n" + menu
        )
        reply = self.client.get_llm().invoke([
            SystemMessage(content=router_prompt),
            HumanMessage(content=question),
        ])
        choice = reply.content.strip().lower()

        by_slug = {a.slug: a for a in agents}
        return by_slug.get(choice) or next((a for a in agents if a.is_default), agents[0])


    HISTORY_LIMIT = 10

    def build_messages(self, question, chat):
        if chat is None:
            return [{"role": "user", "content": question}]
        recent = list(chat.messages.visible().order_by("-created_at")[:self.HISTORY_LIMIT])[::-1]
        return [{"role": m.role, "content": m.message} for m in recent]

    @staticmethod
    def find_artifact(messages):
        artifacts = [m.artifact for m in messages if isinstance(m, ToolMessage) and m.artifact]
        return artifacts[-1] if artifacts else None

    def run_agent(self, question, vendor, chat=None):
        agent = self.pick_agent(question, vendor)
        if agent is None:
            return "No agent is configured for this vendor.", None, None

        graph = self.get_agent_graph(agent)
        result = graph.invoke(
            {"messages": self.build_messages(question, chat)},
            config={"configurable": {"vendor": vendor, "chat": chat}},
        )
        answer = result["messages"][-1].content
        return answer, agent, self.find_artifact(result["messages"])
