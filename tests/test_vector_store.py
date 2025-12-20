import sys
import os
import json
from pathlib import Path
from typing import Dict, List, Any

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.memory.vector_store import VectorStoreFactory, Document
from src.utils.logger import get_logger
from src.utils.helpers import load_config
from unittest.mock import MagicMock, patch
from chromadb.api.types import Documents, Embeddings

class MockEmbeddingFunction:
    def __call__(self, input: Documents) -> Embeddings:
        return [[0.1] * 1024 for _ in input]
    
    def embed_documents(self, texts):
        return self(texts)
        
    def embed_query(self, input):
        print(f"DEBUG: embed_query called with input type: {type(input)}, value: {input}")
        if isinstance(input, list):
            return [[0.1] * 1024 for _ in input]
        return [0.1] * 1024
        
    @staticmethod
    def name():
        return "mock_embedding_function"

def main():
    """主函数"""
    # 设置日志
    
    logger = get_logger(__name__)
    print("开始初始化洛天依知识库")
    logger.info("开始初始化洛天依知识库")
    
    # Mock SiliconFlowEmbeddings to avoid API calls and config issues
    with patch('src.memory.vector_store.SiliconFlowEmbeddings', return_value=MockEmbeddingFunction()) as MockEmbeddings:
        
        try:
            # 加载配置
            config_path = project_root / "config" / "config.json"
            config = load_config(str(config_path))
            
            # 初始化向量存储
            vector_config = config.get("memory_manager", {}).get("vector_store", {})
            
            print("Creating vector store...")
            vector_store = VectorStoreFactory.create_vector_store("chroma", vector_config)
        except Exception as e:
            logger.error(f"知识库初始化失败: {e}", exc_info=True)
            print(f"知识库初始化失败: {e}")
            sys.exit(1)

        doc = Document(
            content="我喜欢吃小笼包",
            metadata={"source": "test" }
        )
        print("Adding documents...")
        vector_store.add_documents([doc])
        print("Searching...")
        ret = vector_store.search("小笼包", k=1)
        if ret:
            searched_doc = ret[0][0]
            logger.info(f"检索结果: {searched_doc.get_content()}")
            print(f"检索结果: {searched_doc.get_content()}")
        else:
            logger.info("未找到结果")
            print("未找到结果")

if __name__ == "__main__":
    main()