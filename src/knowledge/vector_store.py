"""
向量存储模块

管理洛天依知识库的向量化存储和检索
"""

from typing import Dict, List, Optional, Any, Tuple
from abc import ABC, abstractmethod
import numpy as np
from pathlib import Path
from langchain_core.embeddings import Embeddings
import requests

from ..utils.logger import get_logger


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

from langchain_core.documents import Document

# class Document:
#     """文档类"""
    
#     def __init__(
#         self,
#         content: str,
#         metadata: Optional[Dict[str, Any]] = None,
#         doc_id: Optional[str] = None
#     ):
#         """初始化文档
        
#         Args:
#             content: 文档内容
#             metadata: 文档元数据
#             doc_id: 文档ID
#         """
#         self.content = content
#         self.metadata = metadata or {}
#         self.doc_id = doc_id or self._generate_id()
#         self.embedding: Optional[List[float]] = None
    
#     def _generate_id(self) -> str:
#         """生成文档ID"""
#         import hashlib
#         import time
        
#         content_hash = hashlib.md5(self.content.encode()).hexdigest()[:8]
#         timestamp = str(int(time.time()))[-6:]
#         return f"doc_{content_hash}_{timestamp}"


class VectorStore(ABC):
    """向量存储基类"""
    
    @abstractmethod
    def add_documents(self, documents: List[Document]) -> List[str]:
        """添加文档到向量库"""
        pass
    
    @abstractmethod
    def search(self, query: str, k: int = 5, **kwargs) -> List[Tuple[Document, float]]:
        """搜索相似文档"""
        pass
    
    @abstractmethod
    def delete_documents(self, doc_ids: List[str]) -> bool:
        """删除文档"""
        pass
    
    @abstractmethod
    def update_document(self, doc_id: str, document: Document) -> bool:
        """更新文档"""
        pass


class ChromaVectorStore(VectorStore):
    """Chroma向量数据库实现"""
    
    def __init__(self, config: Dict[str, Any]):
        """初始化Chroma向量存储
        
        Args:
            config: 配置字典
        """
        self.logger = get_logger(__name__)
        self.config = config
        
        # 配置参数
        self.persist_directory = config.get("persist_directory", "./data/embeddings")
        self.collection_name = config.get("collection_name", "luotianyi_knowledge")
        self.embedding_model = config.get("embedding_model", "BAAI/bge-m3")
        self.api_key = config.get("api_key", None)
        
        # 初始化Chroma客户端
        self.client = None
        self.collection = None
        self._init_chroma()
        
        self.logger.info(f"Chroma向量存储初始化完成: {self.collection_name}")
    
    def _init_chroma(self) -> None:
        """初始化Chroma客户端和集合"""
        try:
            embeddings = SiliconFlowEmbeddings(
                model=self.embedding_model,
                base_url="https://api.siliconflow.cn/v1",
                api_key=self.api_key
            )
            # 创建客户端
            import chromadb
            from chromadb.config import Settings
            self.client = chromadb.PersistentClient(
                path=self.persist_directory,
                settings=Settings(anonymized_telemetry=False)
            )
            # 获取或创建集合
            # self.collection = self.client.get_or_create_collection(
            #     name=self.collection_name,
            #     embedding_function=embeddings,
            #     metadata={"description": "洛天依知识库"}
            # )
            from langchain_chroma import Chroma
            self.collection = Chroma(
                collection_name=self.collection_name,
                embedding_function=embeddings,
                persist_directory=self.persist_directory,
                client=self.client
            )
            
        except ImportError:
            self.logger.error("Chroma未安装，请安装: pip install chromadb")
            raise
        except Exception as e:
            self.logger.error(f"Chroma初始化失败: {e}")
            raise
    
    def add_documents(self, documents: List[Document]) -> List[str]:
        """添加文档到向量库
        
        Args:
            documents: 文档列表
            
        Returns:
            添加的文档ID列表
        """
        # TODO: 实现文档添加逻辑
        # - 生成文档嵌入
        # - 添加到Chroma集合
        # - 处理重复文档
        
        try:
            
            # 添加到集合
            doc_ids = self.collection.add_documents(
                documents
            )
            
            self.logger.info(f"成功添加 {len(documents)} 个文档")
            return doc_ids
            
        except Exception as e:
            self.logger.error(f"添加文档失败: {e}")
            raise
    
    def search(self, query: str, k: int = 5, **kwargs) -> List[Tuple[Document, float]]:
        """搜索相似文档
        
        Args:
            query: 查询文本
            k: 返回文档数量
            **kwargs: 额外参数
            
        Returns:
            (文档, 相似度分数) 的列表
        """
        # TODO: 实现文档搜索逻辑
        # - 生成查询嵌入
        # - 执行向量搜索
        # - 过滤和排序结果
        
        try:
            # 执行查询
            results = self.collection.similarity_search_with_score(
                query=query,
                k=k,
                **kwargs
            )
            return results
            # 构建返回结果
            search_results = []
            
            if results["documents"] and results["documents"][0]:
                documents = results["documents"][0]
                metadatas = results["metadatas"][0] if results["metadatas"] else [{}] * len(documents)
                distances = results["distances"][0] if results["distances"] else [0.0] * len(documents)
                ids = results["ids"][0] if results["ids"] else [f"doc_{i}" for i in range(len(documents))]
                
                for i, (content, metadata, distance, doc_id) in enumerate(zip(documents, metadatas, distances, ids)):
                    doc = Document(content=content, metadata=metadata, doc_id=doc_id)
                    similarity_score = 1.0 - distance  # 转换距离为相似度
                    search_results.append((doc, similarity_score))
            
            self.logger.info(f"搜索到 {len(search_results)} 个相关文档")
            return search_results
            
        except Exception as e:
            self.logger.error(f"文档搜索失败: {e}")
            return []
    
    def delete_documents(self, doc_ids: List[str]) -> bool:
        """删除文档
        
        Args:
            doc_ids: 文档ID列表
            
        Returns:
            是否删除成功
        """
        # TODO: 实现文档删除逻辑
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
        elif store_type.lower() == "faiss":
            # TODO: 实现FAISS向量存储
            raise NotImplementedError("FAISS向量存储尚未实现")
        elif store_type.lower() == "pinecone":
            # TODO: 实现Pinecone向量存储
            raise NotImplementedError("Pinecone向量存储尚未实现")
        else:
            raise ValueError(f"不支持的向量存储类型: {store_type}")


class KnowledgeDocument:
    """知识文档类
    
    专门用于洛天依知识库的文档结构
    """
    
    def __init__(
        self,
        content: str,
        category: str,
        title: Optional[str] = None,
        tags: Optional[List[str]] = None,
        source: Optional[str] = None,
        **kwargs
    ):
        """初始化知识文档
        
        Args:
            content: 文档内容
            category: 文档分类 (songs, events, persona, etc.)
            title: 文档标题
            tags: 标签列表
            source: 数据来源
            **kwargs: 其他元数据
        """
        self.content = content
        self.category = category
        self.title = title or ""
        self.tags = tags or ""
        self.source = source or ""
        
        # 构建元数据
        metadata = {
            "category": category,
            "title": self.title,
            "tags": self.tags,
            "source": self.source,
            **kwargs
        }
        
        # 创建底层Document对象
        self.document = Document(page_content=content, metadata=metadata)
    
    def to_document(self) -> Document:
        """转换为Document对象
        
        Returns:
            Document对象
        """
        return self.document
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeDocument":
        """从字典创建知识文档
        
        Args:
            data: 数据字典
            
        Returns:
            知识文档实例
        """
        return cls(
            page_content=data["content"],
            category=data["category"],
            title=data.get("title"),
            tags=data.get("tags"),
            source=data.get("source"),
            **{k: v for k, v in data.items() if k not in ["content", "category", "title", "tags", "source"]}
        )
