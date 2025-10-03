
from langchain_core.embeddings import Embeddings
import requests

class SiliconFlowEmbeddings(Embeddings):
    def __init__(self, model="BAAI/bge-m3", api_key=None, base_url="https://api.siliconflow.cn/v1"):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url

    def embed_documents(self, texts):
        return [self._embed(text) for text in texts]

    def embed_query(self, text):
        return self._embed(text)

    def _embed(self, text):
        url = f"{self.base_url}/embeddings"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {"model": self.model, "input": text}
        resp = requests.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]
    
    @staticmethod
    def name() -> str:
        return "default"