
import requests
from typing import List, Union
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings


class SiliconFlowEmbeddings(EmbeddingFunction):
    def __init__(self, model="BAAI/bge-m3", api_key=None, base_url="https://api.siliconflow.cn/v1"):
        self.model = model
        self.api_key = api_key
        if self.api_key is None:
            raise ValueError("API key for SiliconFlowEmbeddings cannot be None.")
        self.base_url = base_url

    def __call__(self, input: Documents) -> Embeddings:
        return self.embed_documents(input)

    def embed_documents(self, texts):
        return [self._embed(text) for text in texts]

    def embed_query(self, *args, **kwargs):
        input_val = kwargs.get('input')
        if input_val is None and args:
            input_val = args[0]
            
        if isinstance(input_val, list):
             return [self._embed(single_input) for single_input in input_val]
        return self._embed(input_val)

    def _embed(self, text):
        url = f"{self.base_url}/embeddings"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {"model": self.model, "input": text}
        resp = requests.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]
    
    @staticmethod
    def name() -> str:
        return "SiliconFlowEmbeddings"
    
    # def is_legacy(self) -> bool:
    #     return False