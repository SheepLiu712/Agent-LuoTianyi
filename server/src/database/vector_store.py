"""
向量存储模块

管理洛天依知识库的向量化存储和检索
"""

import numpy as np
from pathlib import Path
from ..llm.embedding import SiliconFlowEmbeddings
from ..utils.logger import get_logger
import os


from typing import Dict, List, Optional, Any, Tuple
from abc import ABC, abstractmethod

class BaseDocument(ABC):
    """文档基类"""
    def __init__(self):
        self.content: str = ""
        self.id: Optional[str] = None
        self.timestamp: Optional[str] = None
        self.metadata: Dict[str, Any] = {}
    
    @abstractmethod
    def get_content(self) -> str:
        """获取文档内容"""
        pass
    
    @abstractmethod
    def get_metadata(self) -> Dict[str, Any]:
        """获取文档元数据"""
        pass

class Document(BaseDocument):
    def __init__(self, content: str,metadata: Dict, id: Optional[str] = None):
        self.content = content
        self.metadata = metadata
        if "user_id" not in self.metadata:
            raise ValueError("文档的metadata中必须包含'user_id'字段")
        self.id = id
    
    def get_content(self) -> str:
        return self.content
    
    def get_metadata(self) -> Dict[str, Any]:
        return self.metadata


class VectorStore(ABC):
    """向量存储基类"""
    
    @abstractmethod
    def add_documents(self, documents: List[BaseDocument]) -> List[str]:
        """添加文档到向量库"""
        pass
    
    @abstractmethod
    async def search(self, user_id:str, query: str, k: int = 5, **kwargs) -> List[Tuple[BaseDocument, float]]:
        """搜索相似文档"""
        pass
    
    @abstractmethod
    def delete_documents(self, doc_ids: List[str]) -> bool:
        """删除文档"""
        pass
    
    @abstractmethod
    def update_document(self, doc_id: str, document: BaseDocument) -> bool:
        """更新文档"""
        pass

    @abstractmethod
    def get_document_by_id(self, doc_ids: List[str]) -> List[BaseDocument]:
        """通过ID获取文档"""
        pass



import uuid
import chromadb
from chromadb.config import Settings
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

import asyncio

class ChromaVectorStore(VectorStore):
    """Chroma向量数据库实现 (Native Client)"""
    
    def __init__(self, config: Dict[str, Any]):
        """初始化Chroma向量存储
        
        Args:
            config: 配置字典
        """
        self.logger = get_logger(__name__)
        self.config = config
        
        # 配置参数
        self.persist_directory = config.get("vector_store_path", "./data/vector_store")
        if not os.path.exists(self.persist_directory):
            os.makedirs(self.persist_directory, exist_ok=True)
        self.collection_name = config.get("collection_name", "luotianyi_memory")
        self.embedding_model_config = config.get("embedding_model", {})
        self.embedding_model_name = self.embedding_model_config.get("model", "BAAI/bge-large-zh-v1.5")
        self.api_key = self.embedding_model_config.get("api_key", None)
        
        # 初始化Chroma客户端
        self.client = None
        self.collection = None
        self._init_chroma()
        
        self.logger.info(f"Chroma向量存储初始化完成: {self.collection_name}")
    
    def _init_chroma(self) -> None:
        """初始化Chroma客户端和集合"""
        try:
            # 初始化 Embedding 模型
            embedding_function = SiliconFlowEmbeddings(
                model=self.embedding_model_name,
                base_url="https://api.siliconflow.cn/v1",
                api_key=self.api_key
            )
            
            # 创建客户端
            self.client = chromadb.PersistentClient(
                path=self.persist_directory,
                settings=Settings(anonymized_telemetry=False)
            )
            
            # 获取或创建集合
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=embedding_function,
                metadata={"description": "LuoTianyi Knowledge Base"}
            )
            
        except Exception as e:
            self.logger.error(f"Chroma初始化失败: {e}")
            raise

    def add_documents(self,  documents: List[BaseDocument]) -> List[str]:
        """
        添加文档到向量库
        要求documents的metadata中包含"user_id"字段
        """
        try:
            for doc in documents:
                if "user_id" not in doc.get_metadata():
                    raise ValueError("文档的metadata中必须包含'user_id'字段")
            ids = [str(uuid.uuid4()) for _ in documents]
            contents = [doc.get_content() for doc in documents]
            metadatas = [doc.get_metadata() for doc in documents]
            
            self.collection.add(
                documents=contents,
                metadatas=metadatas,
                ids=ids
            )
            
            self.logger.info(f"成功添加 {len(documents)} 个文档")
            return ids
            
        except Exception as e:
            self.logger.error(f"添加文档失败: {e}")
            raise

    async def search(self, user_id: str, query: str, k: int = 5, **kwargs) -> List[Tuple[BaseDocument, float]]:
        """搜索相似文档 (异步)"""
        try:
            # 执行查询
            # self.collection.query 内部会调用 embedding_function 进行 embedding，
            # 而 SiliconFlowEmbeddings._embed 使用了 requests.post 是同步阻塞的。
            # 所以我们需要用 run_in_executor 或 to_thread 将整个 query 过程放入线程池执行
            
            def _do_query():
                return self.collection.query(
                    query_texts=[query],
                    n_results=k,
                    where={"user_id": user_id} if "where" not in kwargs else kwargs.get("where")
                )

            results = await asyncio.to_thread(_do_query)
            
            search_results = []
            
            if results["ids"]:
                # Chroma 返回的是列表的列表 (因为可以批量查询)
                ids = results["ids"][0]
                documents = results["documents"][0]
                metadatas = results["metadatas"][0]
                distances = results["distances"][0]
                
                for i in range(len(ids)):
                    # 构造 Document 对象 (这里假设使用 LangChain Document 或自定义 BaseDocument 子类)
                    # 为了兼容性，我们返回一个简单的对象或字典，或者复用 BaseDocument 的实现
                    # 这里我们动态创建一个简单的对象

                    doc = Document(documents[i], metadatas[i], id=ids[i])
                    
                    # Chroma 默认返回距离 (L2, Cosine 等)，需要根据 distance metric 转换
                    # 默认是 L2 (Squared L2)，越小越相似。
                    # 如果是 Cosine distance，也是越小越相似 (1 - cosine_similarity)。
                    # 这里直接返回 distance，由上层处理，或者简单转换为 score
                    score = 1.0 / (1.0 + distances[i]) # 简单的转换示例
                    
                    search_results.append((doc, score))
            
            self.logger.info(f"搜索到 {len(search_results)} 个相关文档")
            return search_results
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.logger.error(f"文档搜索失败: {e}")
            return []
    
    def delete_documents(self, doc_ids: List[str]) -> bool:
        """删除文档"""
        try:
            self.collection.delete(ids=doc_ids)
            self.logger.info(f"成功删除 {len(doc_ids)} 个文档")
            return True
        except Exception as e:
            self.logger.error(f"删除文档失败: {e}")
            return False
    
    def update_document(self, doc_id: str, document: Document) -> bool:
        """更新文档
        
        Args:
            doc_id: 文档ID
            document: 新文档对象
            
        Returns:
            是否更新成功
        """
        # TODO: 实现文档更新逻辑
        try:
            self.collection.update(
                ids=[doc_id],
                documents=[document.content],
                metadatas=[document.metadata]
            )
            self.logger.info(f"成功更新文档: {doc_id}")
            return True
        except Exception as e:
            self.logger.error(f"更新文档失败: {e}")
            return False
    
    def get_collection_info(self) -> Dict[str, Any]:
        """获取集合信息
        
        Returns:
            集合信息字典
        """
        # TODO: 返回集合统计信息
        try:
            count = self.collection.count()
            return {
                "name": self.collection_name,
                "document_count": count,
                "persist_directory": self.persist_directory
            }
        except Exception as e:
            self.logger.error(f"获取集合信息失败: {e}")
            return {}
        
    def get_document_by_id(self, doc_ids: List[str]) -> List[BaseDocument]:
        """通过ID获取文档"""
        try:
            docs = []
            for doc_id in doc_ids:
                if not isinstance(doc_id, str):
                    continue
                results = self.collection.get(ids=[doc_id])
                if results:
                    documents = results["documents"]
                    metadatas = results["metadatas"]
                    docs.append(Document(documents[0], metadatas[0], id=doc_id))
            return docs
        except Exception as e:
            self.logger.error(f"获取文档失败: {e}")
            return []

class VectorStoreFactory:
    """向量存储工厂类"""
    
    @staticmethod
    def create_vector_store(store_type: str, config: Dict[str, Any]) -> VectorStore:
        """创建向量存储实例
        
        Args:
            store_type: 存储类型
            config: 配置字典
            
        Returns:
            向量存储实例
        """
        if store_type.lower() == "chroma":
            return ChromaVectorStore(config)
        else:
            raise ValueError(f"不支持的向量存储类型: {store_type}")


vector_store: Optional[VectorStore] = None

def init_vector_store(config: Dict[str, Any]) -> None:
    """初始化向量存储"""
    global vector_store
    store_type = config.get("vector_store_type", "chroma")
    vector_store = VectorStoreFactory.create_vector_store(store_type, config)


def get_vector_store() -> VectorStore:
    """获取向量存储实例"""
    global vector_store
    if vector_store is None:
        raise ValueError("向量存储未初始化，请先调用 init_vector_store()")
    return vector_store
