import requests
import os


class OllamaClient:
    def __init__(self, base_url="http://localhost:11434", model="nomic-embed-text"):
        self.base_url = base_url
        self.model = model

    def embed(self, text):
        response = requests.post(
            f"{self.base_url}/api/embeddings",
            json={"model": self.model, "prompt": text},
            timeout=600,
        )
        response.raise_for_status()
        return response.json()["embedding"]


class DeepseekClient:
    def __init__(self, base_url="https://api.deepseek.com", model="deepseek-chat"):
        self.base_url = base_url
        self.model = model
        self.api_key = os.environ.get("DEEPSEEK_API_KEY")


    def ask_deepseek(self, message):
        system_msg = {
            "role": "system",
            "content": (
                message
            ),
        }
        messages = [system_msg]

        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "messages": messages},
            timeout=120,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
