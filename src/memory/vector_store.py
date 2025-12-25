"""
向量存储模块

管理洛天依知识库的向量化存储和检索
"""

import numpy as np
from pathlib import Path
from .embedding import SiliconFlowEmbeddings
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
    def __init__(self, content: str, metadata: Dict, id: Optional[str] = None):
        self.content = content
        self.metadata = metadata
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
    def search(self, query: str, k: int = 5, **kwargs) -> List[Tuple[BaseDocument, float]]:
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

    def add_documents(self, documents: List[BaseDocument]) -> List[str]:
        """添加文档到向量库"""
        try:
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

    def search(self, query: str, k: int = 5, **kwargs) -> List[Tuple[BaseDocument, float]]:
        """搜索相似文档"""
        try:
            # 执行查询
            results = self.collection.query(
                query_texts=[query],
                n_results=k,
                where=kwargs.get("where", None) # 支持元数据过滤
            )
            
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


################################################################
#                                                              #
#                                                              #
#  自定义向量存储实现                                            #
#                                                              #
#                                                              #
################################################################

class ThemeTag:
    def __init__(self, tag: str, tag_id: int):
        self.tag = tag
        self.tag_id: int = tag_id
        self.content_with_tags: List[int] = [] #包含该标签的三元组
    
    def add_content(self, content_id: int) -> None:
        if content_id not in self.content_with_tags:
            self.content_with_tags.append(content_id)
    
    def remove_content(self, content_id: int) -> None:
        if content_id in self.content_with_tags:
            self.content_with_tags.remove(content_id)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "tag": self.tag,
            "tag_id": self.tag_id,
            "content_with_tags": self.content_with_tags
        }

class ThreeTupleDocument():
    def __init__(self, subject  : str, relation: str, object: str, category: str = None, metadata: Optional[Dict[str, Any]] = None):
        self._subject = subject
        self._relation = relation
        self._object = object
        self._category = category
        self._content : str = f"{subject}{relation}{object}"
        self._metadata: Dict[str, Any] = metadata if metadata else {}
        self._metadata.update({"subject": subject, "relation": relation, "object": object, "category": category})
        self.page_content = self._content

    def get_content(self) -> str:
        return self._content

    def get_metadata(self) -> Dict[str, Any]:
        return self._metadata
    
    def to_document(self) -> Document:
        # 兼容 langchain Document
        return Document(page_content=self._content, metadata=self._metadata)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ThreeTupleDocument':
        return cls(
            subject=data.get("subject", ""),
            relation=data.get("relation", ""),
            object=data.get("object", ""),
            category=data.get("category", None),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return self._metadata

class CustomVectorStore(VectorStore):
    """自定义向量存储实现"""
    
    def __init__(self, config: Dict[str, Any]):
        """初始化自定义向量存储
        
        Args:
            config: 配置字典
        """
        self.logger = get_logger(__name__)
        self.config = config
        self.embedding_model = config.get("embedding_model", "BAAI/bge-m3")
        self.vector_store_path = config.get("persist_directory", "./data/custom_vector_store")
        self.vector_store_name = config.get("collection_name", "luotianyi_knowledge")
        self.api_key = config["api_key"]

        self.documents: Dict[str, ThreeTupleDocument] = {}
        self.tags: Dict[str, ThemeTag] = {}
        self.content_embeddings: Dict[str, np.ndarray] = {}
        self.tag_embeddings: Dict[str, np.ndarray] = {}
        self.store_stats: Dict[str, Any] = {}
        self.content_embed_matrix = None # 用于存储内容嵌入的矩阵，方便与查询直接计算
        self.tag_embed_matrix = None # 用于存储标签嵌入的矩阵，方便与查询直接计算
        self.doc_count_ever: int = 0 #用于生成唯一的文档ID，避免删除后ID重复
        self._init_vector_store()
        
        # 初始化嵌入模型
        self.embedding_client = SiliconFlowEmbeddings(
            model=self.embedding_model,
            base_url="https://api.siliconflow.cn/v1",
            api_key=self.api_key
        )

        self.logger.info("自定义向量存储初始化完成")
    
    def _init_vector_store(self) -> None:
        """尝试读取现有的向量存储文件，如果不存在则创建新的存储结构"""
        path = os.path.join(self.vector_store_path, self.vector_store_name)
        os.makedirs(path, exist_ok=True)


        # 读取向量库统计信息
        stats_path = os.path.join(path, "stats.json")
        if os.path.exists(stats_path):
            try:
                import json
                with open(stats_path, "r", encoding="utf-8") as f:
                    self.store_stats = json.load(f)
                    self.doc_count_ever = self.store_stats.get("doc_count_ever", 0)
                self.logger.info(f"向量库统计信息: {self.store_stats}")
            except Exception as e:
                self.logger.error(f"加载统计信息失败: {e}")
        else:
            self.logger.info("未找到现有统计信息文件，初始化为空存储")
            return

        # 读取documents文件
        documents_path = os.path.join(path, "documents.json")
        if os.path.exists(documents_path):
            try:
                import json
                with open(documents_path, "r", encoding="utf-8") as f:
                    docs_data = json.load(f)
                    for doc_id, doc_dict in docs_data.items():
                        doc = ThreeTupleDocument.from_dict(doc_dict)
                        self.documents[doc_id] = doc
                self.logger.info(f"加载了 {len(self.documents)} 个文档")
            except Exception as e:
                self.logger.error(f"加载文档失败: {e}")
        else:
            self.logger.info("未找到现有文档文件，初始化为空存储")
        
        # 读取content_embeddings文件
        embeddings_path = os.path.join(path, "content_embeddings.npz")
        if os.path.exists(embeddings_path):
            try:
                data = np.load(embeddings_path, allow_pickle=True)
                self.content_embeddings = {doc_id: data[doc_id] for doc_id in data.files}
                self.logger.info(f"加载了 {len(self.content_embeddings)} 个内容嵌入向量")
            except Exception as e:
                self.logger.error(f"加载嵌入向量失败: {e}")
        else:
            self.logger.info("未找到现有嵌入文件，初始化为空存储")

        # 读取tag文件
        tag_path = os.path.join(path, "tags.json")
        if os.path.exists(tag_path):
            try:
                import json
                with open(tag_path, "r", encoding="utf-8") as f:
                    tags_data = json.load(f)
                    for tag, tag_dict in tags_data.items():
                        tag_id = tag_dict.get("tag_id")
                        theme_tag = ThemeTag(tag=tag, tag_id=tag_id)
                        theme_tag.content_with_tags = tag_dict.get("content_with_tags", [])
                        self.tags[tag] = theme_tag
                self.logger.info(f"加载了 {len(self.tags)} 个标签")
            except Exception as e:
                self.logger.error(f"加载标签失败: {e}")
        else:
            self.logger.info("未找到现有标签文件，初始化为空存储")

        # 读取tag_embeddings文件
        tag_embeddings_path = os.path.join(path, "tag_embeddings.npz")
        if os.path.exists(tag_embeddings_path):
            try:
                data = np.load(tag_embeddings_path, allow_pickle=True)
                self.tag_embeddings = {doc_id: data[doc_id] for doc_id in data.files}
                self.logger.info(f"加载了 {len(self.tag_embeddings)} 个标签嵌入向量")
            except Exception as e:
                self.logger.error(f"加载标签嵌入向量失败: {e}")
        else:
            self.logger.info("未找到现有标签嵌入文件，初始化为空存储")
        
        # # 读取content_embed_matrix
        # content_embed_matrix_path = os.path.join(path, "content_embed_matrix.npy")
        # if os.path.exists(content_embed_matrix_path):
        #     try:
        #         self.content_embed_matrix = np.load(content_embed_matrix_path, allow_pickle=True)
        #         self.logger.info(f"加载了内容嵌入矩阵，形状: {self.content_embed_matrix.shape}")
        #     except Exception as e:
        #         self.logger.error(f"加载内容嵌入矩阵失败: {e}")
        # else:
        #     self.logger.info("未找到现有内容嵌入矩阵文件，初始化为空")

        # # 读取tag_embed_matrix
        # tag_embed_matrix_path = os.path.join(path, "tag_embed_matrix.npy")
        # if os.path.exists(tag_embed_matrix_path):
        #     try:
        #         self.tag_embed_matrix = np.load(tag_embed_matrix_path, allow_pickle=True)
        #         self.logger.info(f"加载了标签嵌入矩阵，形状: {self.tag_embed_matrix.shape}")
        #     except Exception as e:
        #         self.logger.error(f"加载标签嵌入矩阵失败: {e}")
        # else:
        #     self.logger.info("未找到现有标签嵌入矩阵文件，初始化为空")
        
    
    def add_documents(self, documents: List[ThreeTupleDocument]) -> List[str]:
        """添加文档到向量库
        
        Args:
            documents: 文档列表
            
        Returns:
            添加的文档ID列表
        """
        try:
            doc_ids = []
            new_tag_num = 0
            for doc in documents:
                content = doc.get_content()
                subject = doc._subject
                object = doc._object
                metadata = doc.get_metadata()
                doc_id =  f"doc_{self.doc_count_ever+1}"
                
                # 生成内容嵌入
                content_embedding = self.embedding_client.embed_query(content)
                
                # 存储文档和嵌入
                self.documents[doc_id] = doc
                self.content_embeddings[doc_id] = np.array(content_embedding)
                doc._metadata["doc_id"] = doc_id
                doc_ids.append(doc_id)
                self.doc_count_ever += 1

                # 将三元组的主语和宾语作为标签生成嵌入
                if subject not in self.tags:   
                    subject_embedding = self.embedding_client.embed_query(subject)
                    new_tag = ThemeTag(tag=subject, tag_id=len(self.tags)+1)
                    self.tags[subject] = new_tag
                    self.logger.info(f"为标签 '{subject}' 生成了嵌入")
                    self.tag_embeddings[subject] = np.array(subject_embedding)
                    new_tag_num += 1

                if object not in self.tags:
                    object_embedding = self.embedding_client.embed_query(object)
                    new_tag = ThemeTag(tag=object, tag_id=len(self.tags)+1)
                    self.tags[object] = new_tag
                    self.logger.info(f"为标签 '{object}' 生成了嵌入")
                    self.tag_embeddings[object] = np.array(object_embedding)
                    new_tag_num += 1
                
                self.tags[subject].add_content(doc_id)
                self.tags[object].add_content(doc_id)
            
            self.logger.info(f"成功添加 {len(documents)} 个文档， 包含 {new_tag_num} 个新标签")
            return doc_ids
            
        except Exception as e:
            self.logger.error(f"添加文档失败: {e}")
            raise
    
    def delete_documents(self, doc_ids):
        pass

    def update_document(self, doc_id: str, document: ThreeTupleDocument) -> bool:
        pass

    def save_vector_store(self) -> None:
        """保存当前向量存储到文件"""
        path = os.path.join(self.vector_store_path, self.vector_store_name)
        os.makedirs(path, exist_ok=True)
        
        # 保存统计信息
        stats_path = os.path.join(path, "stats.json")
        try:
            import json
            stats = {
                "document_count": len(self.documents),
                "content_embedding_count": len(self.content_embeddings),
                "tag_embedding_count": len(self.tag_embeddings),
                "doc_count_ever": self.doc_count_ever
            }
            with open(stats_path, "w", encoding="utf-8") as f:
                json.dump(stats, f, ensure_ascii=False, indent=4)
            self.logger.info(f"保存统计信息: {stats}")
        except Exception as e:
            self.logger.error(f"保存统计信息失败: {e}")
        
        # 保存documents文件
        documents_path = os.path.join(path, "documents.json")
        try:
            import json
            docs_data = {doc_id: doc.to_dict() for doc_id, doc in self.documents.items()}
            with open(documents_path, "w", encoding="utf-8") as f:
                json.dump(docs_data, f, ensure_ascii=False, indent=4)
            self.logger.info(f"保存了 {len(self.documents)} 个文档")
        except Exception as e:
            self.logger.error(f"保存文档失败: {e}")
        
        # 保存tags文件
        tag_path = os.path.join(path, "tags.json")
        try:
            import json
            tags_data = {tag: tag_obj.to_dict() for tag, tag_obj in self.tags.items()}
            with open(tag_path, "w", encoding="utf-8") as f:
                json.dump(tags_data, f, ensure_ascii=False, indent=4)
            self.logger.info(f"保存了 {len(self.tags)} 个标签")
        except Exception as e:
            self.logger.error(f"保存标签失败: {e}")
        
        # 保存content_embeddings文件
        embeddings_path = os.path.join(path, "content_embeddings.npz")
        try:
            np.savez(embeddings_path, **self.content_embeddings)
            self.logger.info(f"保存了 {len(self.content_embeddings)} 个内容嵌入向量")
        except Exception as e:
            self.logger.error(f"保存嵌入向量失败: {e}")
        
        # 保存tag_embeddings文件
        tag_embeddings_path = os.path.join(path, "tag_embeddings.npz")
        try:
            np.savez(tag_embeddings_path, **self.tag_embeddings)
            self.logger.info(f"保存了 {len(self.tag_embeddings)} 个标签嵌入向量")
        except Exception as e:
            self.logger.error(f"保存标签嵌入向量失败: {e}")

    def search(self, query: str, k: int = 5, iterations: int = 2, start_tag: str = "", **kwargs) -> List[Tuple[ThreeTupleDocument, float]]:
        """搜索相似文档
        
        Args:
            query: 查询文本
            k: 返回文档数量
            iterations: 联想次数
            **kwargs: 额外参数
            
        Returns:
            (文档, 相似度分数) 的列表
        """
        try:
            if not self.content_embeddings:
                self.logger.warning("内容嵌入为空，无法执行搜索")
                return []
            
            theme_tags = [start_tag]
            results = []
            searched_doc_ids = []
            searched_tags = []
            # 生成查询嵌入
            query_embedding = np.array(self.embedding_client.embed_query(query))

            all_doc_ids = list(self.content_embeddings.keys())
            # 构建doc_id 到 index 的映射，方便后续索引查找
            doc_id_to_index = {doc_id: idx for idx, doc_id in enumerate(all_doc_ids)}
            all_content_embeddings = np.array(list(self.content_embeddings.values()))

            all_tag_ids = list(self.tag_embeddings.keys())
            all_tag_embeddings = np.array(list(self.tag_embeddings.values()))

            for _ in range(iterations):
                iter_docs = []
                iter_scores = []
                new_theme_tags = []
                for theme_tag in theme_tags:
                    interest_content_indices = self._tag_search(theme_tag, all_tag_ids, all_tag_embeddings, doc_id_to_index, top_n=2)
                    interest_content_embeddings = all_content_embeddings[interest_content_indices]
                    interest_doc_ids = [all_doc_ids[idx] for idx in interest_content_indices]

            
                    # 计算余弦相似度
                    from sklearn.metrics.pairwise import cosine_similarity
                    similarities = cosine_similarity([query_embedding], interest_content_embeddings)[0]
                    
                    # 获取前k个最相似的文档
                    top_k_indices = np.argsort(similarities)[-k:][::-1]
                
                    for idx in top_k_indices:
                        doc_id = interest_doc_ids[idx]
                        doc = self.documents.get(doc_id)
                        score = similarities[idx]
                        if doc_id not in searched_doc_ids and doc_id not in iter_docs:
                            iter_docs.append(doc_id)
                            iter_scores.append(score)

                    searched_tags.append(theme_tag)

                top_k_indices = np.argsort(iter_scores)[-k:][::-1]
                for idx in top_k_indices:
                    doc_id = iter_docs[idx]
                    doc = self.documents.get(doc_id)
                    results.append((doc, iter_scores[idx]))
                    searched_doc_ids.append(doc_id)
                    if doc._subject not in searched_tags and doc._subject not in new_theme_tags:
                        new_theme_tags.append(doc._subject)
                    if doc._object not in searched_tags and doc._object not in new_theme_tags:
                        new_theme_tags.append(doc._object)
                theme_tags = new_theme_tags

            return results

        except Exception as e:
            self.logger.error(f"文档搜索失败: {e}")
            return []

    def _tag_search(self, theme_tag: str, all_tag_ids: List[str], all_tag_embeddings: np.ndarray, doc_id_to_index: Dict[str, int], top_n: int = 2) -> np.ndarray:
        """基于标签的搜索，返回与主题标签最相关的标签索引
        
        Args:
            theme_tag: 主题标签
            all_tag_ids: 所有标签ID列表
            all_tag_embeddings: 所有标签嵌入矩阵
            top_n: 返回的相关标签数量
            
        Returns:
            相关标签的索引数组
        """
        if theme_tag not in self.tag_embeddings:
            if theme_tag:
                self.logger.warning(f"主题标签 '{theme_tag}' 不在标签嵌入中，跳过标签搜索")
            return np.arange(len(self.documents))  # 返回所有文档索引
        

        theme_embedding = self.tag_embeddings[theme_tag].reshape(1, -1)
        
        from sklearn.metrics.pairwise import cosine_similarity
        similarities = cosine_similarity(theme_embedding, all_tag_embeddings)[0]
        
        # 获取前top_n个最相似的标签
        top_n_indices = np.argsort(similarities)[-top_n:][::-1]
        
        # 将主语或宾语为这些标签的文档索引收集起来
        related_doc_indices = []
        for idx in top_n_indices:
            tag = all_tag_ids[idx]
            for doc_id in self.tags[tag].content_with_tags:
                if doc_id in doc_id_to_index:
                    related_doc_indices.append(doc_id_to_index[doc_id])

        return np.array(related_doc_indices)

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
        elif store_type.lower() == "custom":
            return CustomVectorStore(config)
        elif store_type.lower() == "faiss":
            raise NotImplementedError("FAISS向量存储尚未实现")
        elif store_type.lower() == "pinecone":
            raise NotImplementedError("Pinecone向量存储尚未实现")
        else:
            raise ValueError(f"不支持的向量存储类型: {store_type}")



