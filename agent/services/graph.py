from langgraph.prebuilt import create_react_agent
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from agent.services.tools import TOOL_REGISTRY
from agent.services.client import AgentClient
from chat.services.files import ChatFileService




class AgentRunner:
    def __init__(self):
        self.client = AgentClient()


    def get_agent_graph(self, agent):
        compiled, config = self.client.get_prompt(agent.prompt_name)
        tools = [TOOL_REGISTRY[name] for name in agent.tools if name in TOOL_REGISTRY]
        tools += [self.sub_agent_tool(sub) for sub in agent.sub_agents.filter(is_active=True)]
        return create_react_agent(self.client.get_llm(config), tools=tools, prompt=compiled)

    def sub_agent_tool(self, sub):
        description = (
            f"Ask the {sub.label} agent to do a task and get its answer back. {sub.description} "
            "It cannot see this conversation, so put every detail it needs in the task, including any file ids."
        )

        @tool(f"ask_{sub.slug}", description=description, response_format="content_and_artifact")
        def ask(task: str, config: RunnableConfig) -> tuple[str, dict]:
            configurable = config["configurable"]
            try:
                result = self.get_agent_graph(sub).invoke(
                    {"messages": [{"role": "user", "content": task}]},
                    config={"configurable": {"vendor": configurable["vendor"], "chat": configurable.get("chat")}},
                )
            except Exception as error:
                return f"Error: the {sub.label} agent failed: {error}", None
            return result["messages"][-1].content, self.find_artifact(result["messages"])

        return ask

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
