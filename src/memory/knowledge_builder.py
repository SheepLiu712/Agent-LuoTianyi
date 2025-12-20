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
from .graph_retriever import GraphRetriever, KnowledgeGraph
from ..utils.logger import get_logger
from .memory_type import Entity, Relation, GraphEntityType, GraphRelationType, entity_name_back_dict, relation_name_back_dict, point_to_entity_type

class KnowledgeBuilder:
    """知识库构建器
    
    负责从各种数据源构建洛天依知识库
    """
    
    def __init__(
        self,
        vector_store: VectorStore = None,
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
        self.graph_retriever: GraphRetriever = graph_retriever
        self.config = config or {}
        
        # 数据分类
        self.knowledge_categories = {}
        
        # 加载实体别名映射
        self.entity_aliases = self._load_entity_aliases()
        
        self.logger.info("知识库构建器初始化完成")
    
    def _load_entity_aliases(self) -> Dict[str, str]:
        """加载实体别名映射"""
        try:
            # 尝试查找配置文件
            paths_to_try = [
                Path("config/entity_aliases.json"),
                Path(__file__).parent.parent.parent / "config" / "entity_aliases.json"
            ]
            
            for alias_path in paths_to_try:
                if alias_path.exists():
                    self.logger.info(f"加载实体别名映射: {alias_path}")
                    with open(alias_path, 'r', encoding='utf-8') as f:
                        return json.load(f)
            
            return {}
        except Exception as e:
            self.logger.warning(f"加载实体别名映射失败: {e}")
            return {}

    def _resolve_entity_name(self, name: str) -> str:
        """解析实体名称，处理别名"""
        if not name:
            return name
        return self.entity_aliases.get(name, name)

    
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
                # break
        
        self.graph_retriever.save_graph_data()
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
            else:
                self.logger.debug(f"跳过不支持的文件: {file_path}")
                
        except Exception as e:
            self.logger.error(f"处理文件失败 {file_path}: {e}")
    
    def _process_json_file(self, file_path: Path) -> None:
        """处理JSON文件
        
        Args:
            file_path: JSON文件路径
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 1. 优先尝试 VCPedia 格式 (高效建图)
            # 单个条目
            if isinstance(data, dict):
                self._build_from_vcpedia_item(data)
                return
            # 条目列表
            elif isinstance(data, list):
                is_vcpedia_list = False
                for item in data:
                    if isinstance(item, dict) and "infobox" in item and "title" in item:
                        self._build_from_vcpedia_item(item)
                        is_vcpedia_list = True
                if is_vcpedia_list:
                    return
            
        except Exception as e:
            self.logger.error(f"解析JSON文件失败 {file_path}: {e}")

    def _build_from_vcpedia_item(self, item: Dict[str, Any]) -> None:
        """
        高效建图核心逻辑：基于VCPedia Infobox构建图谱
        
        策略：
        1. 实体创建：以词条名(title)作为核心实体。
        2. 属性存储：将'summary'(简介)直接作为实体的文本属性，解决"只查简介"的需求。
        3. 关系抽取：仅从infobox中提取强关系（如P主、演唱者），忽略非结构化文本。
        """
        if not self.graph_retriever:
            return

        # 1. 创建核心实体
        main_entity_name = self._resolve_entity_name(item.get("name"))
        if not main_entity_name:
            return

        # 将简介作为属性存入，这样检索实体时可以直接获取简介，无需再次爬取
        properties = {
            "summary": item.get("description", ""),
        }
        
        # 将Infobox中的其他简单键值对也作为属性（如发布时间、BPM等）
        attributes: Dict[str, Any] = item.get("attributes", {})
        for k, v in attributes.items():
            if isinstance(v, str) and len(v) < 100: # 简单属性
                properties[k] = v

        main_entity = Entity(
            id=main_entity_name, # 简单起见使用名称作为ID
            name=main_entity_name,
            entity_type=entity_name_back_dict.get(item.get("type", "song").lower(), GraphEntityType.SONG),
            properties=properties
        )
        
        # 添加到图谱（内存或数据库）
        if hasattr(self.graph_retriever, "knowledge_graph"):
            self.graph_retriever.knowledge_graph.add_entity(main_entity)
        
        # 2. 关系抽取 (基于Infobox的规则)

        for key, value in attributes.items():
            # 清洗Key（去掉冒号等）
            clean_key = key.replace(":", "").strip()

            if clean_key in ["是否为传说曲", "是否为殿堂曲", "是否为神话曲"]:
                if value == "True":
                    target = clean_key[-3:] # 传说曲、殿堂曲、神话曲
                    relation_type = GraphRelationType.WIN_AWARD
                    target_type = GraphEntityType.GLORY
                    if not self.graph_retriever.knowledge_graph.has_entity(target):
                        target_entity = Entity(
                            id=target,
                            name=target,
                            entity_type=target_type,
                            properties={}
                        )
                        self.graph_retriever.knowledge_graph.add_entity(target_entity)
                    relation = Relation(
                        id=f"{main_entity.id}_{relation_type.value}_{target}",
                        source_id=main_entity.id,
                        target_id=target,
                        relation_type=relation_type,
                        properties={},
                        weight=1.0
                    )
                    self.graph_retriever.knowledge_graph.add_relation(relation)
            
            if clean_key == "发布时间":
                if isinstance(value,list):
                    value = value[0]
                target = str(value).strip()[:4] # 只取年份
                relation_type = GraphRelationType.RELEASED_IN
                target_type = GraphEntityType.YEAR
                if not self.graph_retriever.knowledge_graph.has_entity(target):
                    target_entity = Entity(
                        id=target,
                        name=target,
                        entity_type=target_type,
                        properties={}
                    )
                    self.graph_retriever.knowledge_graph.add_entity(target_entity)
                relation = Relation(
                    id=f"{main_entity.id}_{relation_type.value}_{target}",
                    source_id=main_entity.id,
                    target_id=target,
                    relation_type=relation_type,
                    properties={},
                    weight=1.0
                )
            
            if clean_key in relation_name_back_dict:
                if value == "" or value is None:
                    continue
                relation_type: GraphRelationType = relation_name_back_dict[clean_key]
                target_type: GraphEntityType = point_to_entity_type.get(relation_type, GraphEntityType.PERSON)
                targets = []
                if isinstance(value, list):
                    targets = value
                elif isinstance(value, str):
                    # 简单分割，实际可能需要更复杂的清洗
                    targets = value.replace("、", ",").split(",")
                
                for target in targets:
                    target_name = target.strip()
                    target_name = target_name.replace("《", "").replace("》", "").strip()
                    target_name = self._resolve_entity_name(target_name)
                    if not target_name:
                        continue
                    if not self.graph_retriever.knowledge_graph.has_entity(target_name):
                        target_entity = Entity(
                            id=target_name,
                            name=target_name,
                            entity_type=target_type,
                            properties={}
                        )
                        self.graph_retriever.knowledge_graph.add_entity(target_entity)
                    relation = Relation(
                        id=f"{main_entity.id}_{relation_type.value}_{target_name}",
                        source_id=main_entity.id,
                        target_id=target_name,
                        relation_type=relation_type,
                        properties={},
                        weight=1.0
                    )
                    self.graph_retriever.knowledge_graph.add_relation(relation)
    
    
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
