"""
图结构检索模块

基于知识图谱的多跳推理检索系统
"""

from typing import Dict, List, Optional, Any, Tuple, Set, Union
from abc import ABC, abstractmethod
from ..types.memory_type import Entity, Relation, GraphEntityType, GraphRelationType
import random

from ..utils.logger import get_logger
from ..database.knowledge_graph import KnowledgeGraph

class GraphRetriever(ABC):
    """图检索器基类"""

    @abstractmethod
    def retrieve(self, graph: KnowledgeGraph, query: str, entities: List[str], **kwargs) -> List[Dict[str, Any]]:
        """检索相关知识"""
        pass

    @abstractmethod
    def multi_hop_retrieve(self, graph: KnowledgeGraph, start_entities: List[str], max_hops: int = 2) -> List[Dict[str, Any]]:
        """多跳检索"""
        pass

    @abstractmethod
    def retrieve_one_entity(self, graph: KnowledgeGraph, entity_name: str) -> Optional[Entity]:
        """检索单个实体"""
        pass

    @abstractmethod
    def get_entities_by_type(self, graph: KnowledgeGraph, entity_type: Union[str, GraphEntityType]) -> List[Entity]:
        """获取指定类型的实体名称列表"""
        pass

    @abstractmethod
    def retrieve_relation_between_entities(self, graph: KnowledgeGraph, entity_a: str, entity_b: str) -> List[Relation]:
        """检索两个实体之间的关系"""
        pass

    @abstractmethod
    def get_neighbors(
        self,
        graph: KnowledgeGraph,
        entity_name: str,
        direction: str = "both",
        relation_type: Optional[Union[str, GraphRelationType]] = None,
        neighbor_type: Optional[Union[str, GraphEntityType]] = None,
        needed_neighbors: int = -1,
    ) -> List[Tuple[Entity, str]]:
        """获取实体的邻居"""
        pass

    @abstractmethod
    def get_shared_neighbors(
        self,
        graph: KnowledgeGraph,
        entity_a: str,
        entity_b: str,
        direction: str = "both",
        neighbor_type: Optional[Union[str, GraphEntityType]] = None,
        needed_neighbors: int = -1,
    ) -> List[Entity]:
        """获取两个实体的共同邻居"""
        pass

    @abstractmethod
    def find_connections(self, graph: KnowledgeGraph, entity_a: str, entity_b: str, needed_path_num: int = -1) -> List[str]:
        """查找两个实体之间的关联 (LLM工具接口)"""
        pass


class InMemoryGraphRetriever(GraphRetriever):
    """内存图检索器

    用于小规模知识图谱的内存检索
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """初始化内存图检索器

        Args:
            config: 配置字典
        """
        self.logger = get_logger(__name__)
        self.config = config or {}
        # 注意: 这里不再持有 KnowledgeGraph 实例，也不负责加载数据

    def retrieve(self, graph: KnowledgeGraph, query: str, entities: List[str], **kwargs) -> List[Dict[str, Any]]:
        """检索相关知识

        Args:
            graph: 知识图谱实例
            query: 查询文本
            entities: 相关实体列表
            **kwargs: 额外参数

        Returns:
            检索结果列表
        """
        results = []

        for entity_name in entities:
            # 查找实体
            entity = self._find_entity_by_name(graph, entity_name)
            if not entity:
                continue

            # 获取邻居实体和关系
            neighbors = graph.get_neighbors(entity.id)

            for neighbor, relation_type in neighbors:
                result = {
                    "source_entity": entity.name,
                    "target_entity": neighbor.name,
                    "relation": relation_type,
                    "properties": neighbor.properties,
                }
                results.append(result)

        return results

    def multi_hop_retrieve(self, graph: KnowledgeGraph, start_entities: List[str], max_hops: int = 2) -> List[Dict[str, Any]]:
        """多跳检索

        Args:
            graph: 知识图谱实例
            start_entities: 起始实体列表
            max_hops: 最大跳数

        Returns:
            多跳检索结果
        """
        results = []

        for entity_name in start_entities:
            entity = self._find_entity_by_name(graph, entity_name)
            if not entity:
                continue

            neighbors = graph.get_neighbors(entity.id)
            for neighbor, r_type in neighbors:
                results.append(
                    {"start_entity": entity.name, "path": [entity.id, neighbor.id], "hop_count": 1, "relation": r_type}
                )

        return results

    def _find_entity_by_name(self, graph: KnowledgeGraph, name: str) -> Optional[Entity]:
        """根据名称查找实体"""
        for entity in graph.entities.values():
            if entity.name == name:
                return entity
        return None

    def retrieve_one_entity(self, graph: KnowledgeGraph, entity_name: str) -> Optional[Entity]:
        """检索单个实体"""
        aliased_name = graph.get_aliased_name(entity_name)
        return graph.entities.get(aliased_name)

    def get_entities_by_type(self, graph: KnowledgeGraph, entity_type: Union[str, GraphEntityType]) -> List[Entity]:
        """获取指定类型的实体名称列表"""
        entities = graph.get_entities_by_type(entity_type)
        return entities

    def retrieve_relation_between_entities(self, graph: KnowledgeGraph, entity_a: str, entity_b: str) -> List[Relation]:
        """检索两个实体之间的关系"""
        relations = []
        if entity_a not in graph.entities or entity_b not in graph.entities:
            return relations

        # 检查从 A 到 B 的关系
        if graph.graph.has_edge(entity_a, entity_b):
            edge_data = graph.graph.get_edge_data(entity_a, entity_b)
            relation = Relation(
                id=edge_data.get("id", f"{entity_a}_{entity_b}"),
                source_id=entity_a,
                target_id=entity_b,
                relation_type=GraphRelationType(edge_data.get("type")),
                properties={k: v for k, v in edge_data.items() if k not in ["type", "id"]},
            )
            relations.append(relation)

        # 检查从 B 到 A 的关系
        if graph.graph.has_edge(entity_b, entity_a):
            edge_data = graph.graph.get_edge_data(entity_b, entity_a)
            relation = Relation(
                id=edge_data.get("id", f"{entity_b}_{entity_a}"),
                source_id=entity_b,
                target_id=entity_a,
                relation_type=GraphRelationType(edge_data.get("type")),
                properties={k: v for k, v in edge_data.items() if k not in ["type", "id"]},
            )
            relations.append(relation)

        return relations

    def get_neighbors(
        self,
        graph: KnowledgeGraph,
        entity_name: str,
        direction="both",
        relation_type: Optional[Union[str, GraphRelationType]] = None,
        neighbor_type: Optional[Union[str, GraphEntityType]] = None,
        needed_neighbors: int = -1,
    ):
        """获取实体的邻居"""
        neighbors = graph.get_neighbors(entity_name, direction, relation_type, neighbor_type)
        if needed_neighbors > 0:
            random.shuffle(neighbors)
            neighbors = neighbors[:needed_neighbors]
        return neighbors

    def get_shared_neighbors(
        self,
        graph: KnowledgeGraph,
        entity_a: str,
        entity_b: str,
        direction="both",
        neighbor_type: Optional[Union[str, GraphEntityType]] = None,
        needed_neighbors=-1,
    ) -> List[Entity]:
        neighbors_a = graph.get_neighbors(entity_a, direction, neighbor_type=neighbor_type)
        neighbors_b = graph.get_neighbors(entity_b, direction, neighbor_type=neighbor_type)
        set_a: Set[str] = set([n.id for n, _ in neighbors_a])
        set_b: Set[str] = set([n.id for n, _ in neighbors_b])
        shared_ids = set_a.intersection(set_b)
        shared_neighbors = []
        for n_id in shared_ids:
            neighbor_entity = graph.entities[n_id]
            shared_neighbors.append(neighbor_entity)
        if needed_neighbors > 0:
            random.shuffle(shared_neighbors)
            shared_neighbors = shared_neighbors[:needed_neighbors]
        return shared_neighbors

    def find_connections(self, graph: KnowledgeGraph, entity_a: str, entity_b: str, needed_path_num: int = -1) -> List[str]:
        """查找两个实体之间的关联路径"""
        # 使用无向搜索以忽略方向
        paths = graph.find_path(entity_a, entity_b, max_depth=3, undirected=True)
        readable_paths = []
        for path in paths:
            # 将ID路径转换为可读描述
            desc = []
            for i in range(len(path) - 1):
                u, v = path[i], path[i + 1]

                # 尝试获取正向边
                edge_data = graph.graph.get_edge_data(u, v)
                if edge_data:
                    r_type = edge_data.get("type", "RELATED_TO")
                    desc.append(f"{u} --[{r_type}]--> {v}")
                else:
                    # 尝试获取反向边
                    edge_data = graph.graph.get_edge_data(v, u)
                    if edge_data:
                        r_type = edge_data.get("type", "RELATED_TO")
                        desc.append(f"{u} <--[{r_type}]-- {v}")
                    else:
                        desc.append(f"{u} --[UNKNOWN]--> {v}")

            path_length = len(desc)
            final_desc = " , ".join(desc)
            readable_paths.append((final_desc, path_length))

        # 按路径长度排序
        readable_paths.sort(key=lambda x: x[1])
        readable_paths = [p[0] for p in readable_paths]
        if needed_path_num > 0:
            random.shuffle(readable_paths)
            readable_paths = readable_paths[:needed_path_num]
        return readable_paths


class GraphRetrieverFactory:
    """图检索器工厂"""

    @staticmethod
    def create_retriever(retriever_type: str, config: Dict[str, Any]) -> GraphRetriever:
        """创建图检索器

        Args:
            retriever_type: 检索器类型
            config: 配置字典

        Returns:
            图检索器实例
        """
        if retriever_type.lower() == "neo4j":
            raise NotImplementedError("Neo4j 图检索器尚未实现")
        elif retriever_type.lower() == "memory":
            return InMemoryGraphRetriever(config)
        else:
            raise ValueError(f"不支持的图检索器类型: {retriever_type}")
