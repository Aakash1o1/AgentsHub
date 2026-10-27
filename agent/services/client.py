import os
from langchain_openai import ChatOpenAI
from langfuse import Langfuse

class AgentClient:
    def __init__(self):
        self.langfuse = Langfuse()

    def get_llm(self, config=None):
        config = config or {}
        return ChatOpenAI(
            model=config.get("model", "deepseek-chat"),
            base_url="https://api.deepseek.com",
            api_key=os.environ["DEEPSEEK_API_KEY"],
        )




    def get_prompt(self, name, **variables):
        prompt = self.langfuse.get_prompt(name)
        return prompt.compile(**variables), prompt.config

