from langgraph.prebuilt import create_react_agent
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

from agent.services.tools import TOOL_REGISTRY
from agent.services.client import AgentClient
from chat.services.files import ChatFileService



class ToolChoice:
    def __init__(self, llm, tools):
        self.free = llm.bind_tools(tools)
        self.forced = llm.bind_tools(tools, tool_choice="required")

    def __call__(self, state, runtime):
        return self.forced if isinstance(state["messages"][-1], HumanMessage) else self.free


class AgentRunner:
    def __init__(self):
        self.client = AgentClient()


    def get_agent_graph(self, agent):
        workflow = agent.workflow
        compiled, config = self.client.get_prompt(workflow.prompt_name)
        tools = [TOOL_REGISTRY[name] for name in workflow.tools if name in TOOL_REGISTRY]
        llm = self.client.get_llm(config)
        if workflow.force_tool_call and tools:
            llm = ToolChoice(llm, tools)
        return create_react_agent(llm, tools=tools, prompt=compiled)

    ROUTER_FILE_LIMIT = 10

    @classmethod
    def router_question(cls, question, chat):
        files = ChatFileService.for_chat(chat)
        if not files:
            return question
        lines = [question]
        latest = chat.messages.visible().filter(role="user").order_by("-id").first()
        if latest is not None and latest.has_source:
            lines.append(f"[This message attaches: {latest.file_label}]")
        names = ", ".join(message.file_label for message in files[-cls.ROUTER_FILE_LIMIT:])
        lines.append(f"[Files and links in this chat: {names}]")
        return "\n".join(lines)

    def pick_agent(self, question, vendor, chat=None):
        agents = list(vendor.agents.filter(is_active=True))
        if not agents:
            return None

        menu = "\n".join(f"- {a.slug} : {a.description}" for a in agents)
        router_prompt = (
            "You are a router. Reply with EXACTLY ONE slug from this list, "
            "no punctuation:\n" + menu + "\n"
            "Lines in square brackets are not written by the user: they list the files attached in this chat."
        )
        reply = self.client.get_llm().invoke([
            SystemMessage(content=router_prompt),
            HumanMessage(content=self.router_question(question, chat)),
        ])
        choice = reply.content.strip().lower()

        by_slug = {a.slug: a for a in agents}
        return by_slug.get(choice) or next((a for a in agents if a.is_default), agents[0])


    HISTORY_LIMIT = 20

    def build_messages(self, question, chat):
        if chat is None:
            return [{"role": "user", "content": question}]
        recent = list(chat.messages.visible().order_by("-created_at")[:self.HISTORY_LIMIT])[::-1]
        return [{"role": m.role, "content": self.with_source(m)} for m in recent]

    @staticmethod
    def with_source(message):
        if not message.has_source:
            return message.text
        kind = "link" if message.url else "file"
        return f"{message.text}\n[attached {kind}: {message.file_label}, file id {message.id}]"

    @staticmethod
    def find_artifact(messages):
        artifacts = [m.artifact for m in messages if isinstance(m, ToolMessage) and m.artifact]
        return artifacts[-1] if artifacts else None

    def run_agent(self, question, vendor, chat=None):
        agent = self.pick_agent(question, vendor, chat)
        if agent is None:
            return "No agent is configured for this vendor.", None, None

        graph = self.get_agent_graph(agent)
        result = graph.invoke(
            {"messages": self.build_messages(question, chat)},
            config={"configurable": {"vendor": vendor, "chat": chat}},
        )
        answer = result["messages"][-1].content
        return answer, agent, self.find_artifact(result["messages"])
