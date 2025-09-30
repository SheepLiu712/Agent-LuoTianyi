"""
知识库构建模块

负责构建和维护洛天依知识库
"""

from typing import Dict, List, Optional, Any, Union
import json
import os
from pathlib import Path
import pandas as pd

from .vector_store import VectorStore, KnowledgeDocument
from .graph_retriever import GraphRetriever, Entity, Relation, KnowledgeGraph
from ..utils.logger import get_logger


class KnowledgeBuilder:
    """知识库构建器
    
    负责从各种数据源构建洛天依知识库
    """
    
    def __init__(
        self,
        vector_store: VectorStore,
        graph_retriever: Optional[GraphRetriever] = None,
        config: Optional[Dict[str, Any]] = None
    ):
        """初始化知识库构建器
        
        Args:
            vector_store: 向量存储实例
            graph_retriever: 图检索器实例
            config: 配置字典
        """
        self.logger = get_logger(__name__)
        self.vector_store = vector_store
        self.graph_retriever = graph_retriever
        self.config = config or {}
        
        # 数据分类
        self.knowledge_categories = {
            "persona": "人设信息",
            "songs": "歌曲信息", 
            "events": "活动演出",
            "collaborations": "合作信息",
            "social": "社交媒体",
            "fanart": "粉丝创作",
            "interviews": "访谈资料"
        }
        
        self.logger.info("知识库构建器初始化完成")
    
    def build_from_directory(self, data_dir: str) -> None:
        """从目录构建知识库
        
        Args:
            data_dir: 数据目录路径
        """
        data_path = Path(data_dir)
        if not data_path.exists():
            self.logger.error(f"数据目录不存在: {data_dir}")
            return
        
        self.logger.info(f"开始从目录构建知识库: {data_dir}")
        
        # 处理各种文件类型
        for file_path in data_path.rglob("*"):
            if file_path.is_file():
                self._process_file(file_path)
        
        self.logger.info("知识库构建完成")
    
    def _process_file(self, file_path: Path) -> None:
        """处理单个文件
        
        Args:
            file_path: 文件路径
        """
        try:
            suffix = file_path.suffix.lower()
            
            if suffix == ".json":
                self._process_json_file(file_path)
            elif suffix == ".csv":
                self._process_csv_file(file_path)
            elif suffix == ".txt" or suffix == ".md":
                self._process_text_file(file_path)
            else:
                self.logger.debug(f"跳过不支持的文件: {file_path}")
                
        except Exception as e:
            self.logger.error(f"处理文件失败 {file_path}: {e}")
    
    def _process_json_file(self, file_path: Path) -> None:
        """处理JSON文件
        
        Args:
            file_path: JSON文件路径
        """
        # TODO: 实现JSON文件处理逻辑
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            assert isinstance(data,dict), "data should be a dict"
            for category, content in data.items():
                assert isinstance(content,(list,dict)), "content should be a list or dict"
                if isinstance(content, list):
                    # 处理文档列表
                    for item in content:
                        if isinstance(item, list):
                            item = {
                                "content": " ".join(item),
                                "subject": item[0],
                                'relation': item[1],
                                "object": item[2]
                            }
                        self._add_knowledge_item(item, category, str(file_path))
                
        except Exception as e:
            self.logger.error(f"处理JSON文件失败 {file_path}: {e}")
    
    # YAML文件处理已移除，仅支持JSON/CSV/TXT/MD
    
    def _process_csv_file(self, file_path: Path) -> None:
        """处理CSV文件
        
        Args:
            file_path: CSV文件路径
        """
        # TODO: 实现CSV文件处理逻辑
        try:
            df = pd.read_csv(file_path, encoding='utf-8')
            category = self._infer_category(file_path, {})
            
            for _, row in df.iterrows():
                item_data = row.to_dict()
                self._add_knowledge_item(item_data, category, str(file_path))
                
        except Exception as e:
            self.logger.error(f"处理CSV文件失败 {file_path}: {e}")
    
    def _process_text_file(self, file_path: Path) -> None:
        """处理文本文件
        
        Args:
            file_path: 文本文件路径
        """
        # TODO: 实现文本文件处理逻辑
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            category = self._infer_category(file_path, {"content": content})
            
            # 将整个文本作为一个知识项
            item_data = {
                "content": content,
                "title": file_path.stem,
                "source": str(file_path)
            }
            
            self._add_knowledge_item(item_data, category, str(file_path))
            
        except Exception as e:
            self.logger.error(f"处理文本文件失败 {file_path}: {e}")
    
    def _infer_category(self, file_path: Path, data: Dict[str, Any]) -> str:
        """推断知识类别
        
        Args:
            file_path: 文件路径
            data: 数据内容
            
        Returns:
            知识类别
        """
        # TODO: 实现智能类别推断
        
        # 基于文件名推断
        file_name = file_path.name.lower()
        
        if "song" in file_name or "music" in file_name:
            return "songs"
        elif "event" in file_name or "concert" in file_name:
            return "events"
        elif "persona" in file_name or "character" in file_name:
            return "persona"
        elif "collab" in file_name:
            return "collaborations"
        elif "social" in file_name or "weibo" in file_name:
            return "social"
        elif "interview" in file_name:
            return "interviews"
        
        # 基于内容推断
        if isinstance(data, dict):
            content = str(data).lower()
            if "歌曲" in content or "音乐" in content:
                return "songs"
            elif "演出" in content or "演唱会" in content:
                return "events"
            elif "性格" in content or "设定" in content:
                return "persona"
        
        # 默认类别
        return "general"
    
    def _add_knowledge_item(self, item_data: Dict[str, Any], category: str, source: str) -> None:
        """添加知识项到存储系统
        
        Args:
            item_data: 知识项数据
            category: 知识类别
            source: 数据来源
        """
        try:
            # 提取内容
            content = self._extract_content(item_data)
            if not content:
                return
            
            # 创建知识文档
            knowledge_doc = KnowledgeDocument(
                content=content,
                category=category,
                title=item_data.get("title", ""),
                tags=item_data.get("tags", []),
                source=source,
                **{k: v for k, v in item_data.items() if k not in ["content", "title", "tags"]}
            )
            
            # 添加到向量存储
            self.vector_store.add_documents([knowledge_doc.to_document()])
            
            # 添加到图存储（如果配置了）
            if self.graph_retriever:
                self._add_to_graph(knowledge_doc, item_data)
            
            self.logger.debug(f"添加知识项: {category} - {knowledge_doc.title}")
            
        except Exception as e:
            self.logger.error(f"添加知识项失败: {e}")
    
    def _extract_content(self, item_data: Dict[str, Any]) -> str:
        """提取文本内容
        
        Args:
            item_data: 项目数据
            
        Returns:
            提取的文本内容
        """
        # TODO: 实现智能内容提取
        
        # 优先级顺序的字段名
        content_fields = [
            "content", "text", "description", "lyrics", 
            "summary", "abstract", "body", "message"
        ]
        
        for field in content_fields:
            if field in item_data and item_data[field]:
                return str(item_data[field])
        
        # 如果没有明确的内容字段，合并所有文本字段
        text_parts = []
        for key, value in item_data.items():
            if isinstance(value, str) and value.strip():
                text_parts.append(f"{key}: {value}")
        
        return "\n".join(text_parts)
    
    def _add_to_graph(self, knowledge_doc: KnowledgeDocument, item_data: Dict[str, Any]) -> None:
        """添加到知识图谱
        
        Args:
            knowledge_doc: 知识文档
            item_data: 原始数据
        """
        # TODO: 实现图结构构建
        # - 提取实体和关系
        # - 创建图节点和边
        # - 添加到图数据库
        pass
    
    def add_song_knowledge(self, song_data: Dict[str, Any]) -> None:
        """添加歌曲知识
        
        Args:
            song_data: 歌曲数据
        """
        # TODO: 实现专门的歌曲知识添加逻辑
        
        required_fields = ["title", "content"]
        if not all(field in song_data for field in required_fields):
            self.logger.warning(f"歌曲数据缺少必需字段: {required_fields}")
            return
        
        # 构建歌曲文档
        content = f"歌曲: {song_data['title']}\n"
        if "lyrics" in song_data:
            content += f"歌词: {song_data['lyrics']}\n"
        if "album" in song_data:
            content += f"专辑: {song_data['album']}\n"
        if "release_date" in song_data:
            content += f"发行日期: {song_data['release_date']}\n"
        
        knowledge_doc = KnowledgeDocument(
            content=content,
            category="songs",
            title=song_data["title"],
            tags=song_data.get("tags", []),
            source="manual_input",
            **song_data
        )
        
        self.vector_store.add_documents([knowledge_doc.to_document()])
        self.logger.info(f"添加歌曲知识: {song_data['title']}")
    
    def add_event_knowledge(self, event_data: Dict[str, Any]) -> None:
        """添加活动知识
        
        Args:
            event_data: 活动数据
        """
        # TODO: 实现专门的活动知识添加逻辑
        
        required_fields = ["title", "content"]
        if not all(field in event_data for field in required_fields):
            self.logger.warning(f"活动数据缺少必需字段: {required_fields}")
            return
        
        # 构建活动文档
        content = f"活动: {event_data['title']}\n"
        if "date" in event_data:
            content += f"日期: {event_data['date']}\n"
        if "location" in event_data:
            content += f"地点: {event_data['location']}\n"
        if "description" in event_data:
            content += f"描述: {event_data['description']}\n"
        
        knowledge_doc = KnowledgeDocument(
            content=content,
            category="events",
            title=event_data["title"],
            tags=event_data.get("tags", []),
            source="manual_input",
            **event_data
        )
        
        self.vector_store.add_documents([knowledge_doc.to_document()])
        self.logger.info(f"添加活动知识: {event_data['title']}")
    
    def update_knowledge(self, doc_id: str, updated_data: Dict[str, Any]) -> bool:
        """更新知识条目
        
        Args:
            doc_id: 文档ID
            updated_data: 更新数据
            
        Returns:
            更新是否成功
        """
        # TODO: 实现知识更新逻辑
        try:
            # 更新向量存储
            # TODO: 实现具体的更新逻辑
            
            self.logger.info(f"更新知识条目: {doc_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"更新知识失败: {e}")
            return False
    
    def delete_knowledge(self, doc_id: str) -> bool:
        """删除知识条目
        
        Args:
            doc_id: 文档ID
            
        Returns:
            删除是否成功
        """
        # TODO: 实现知识删除逻辑
        try:
            # 从向量存储删除
            success = self.vector_store.delete_documents([doc_id])
            
            if success:
                self.logger.info(f"删除知识条目: {doc_id}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"删除知识失败: {e}")
            return False
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取知识库统计信息
        
        Returns:
            统计信息字典
        """
        # TODO: 实现统计信息收集
        stats = {
            "total_documents": 0,
            "categories": {},
            "vector_store_info": {},
            "graph_info": {}
        }
        
        # 获取向量存储统计
        if hasattr(self.vector_store, 'get_collection_info'):
            stats["vector_store_info"] = self.vector_store.get_collection_info()
        
        return stats
