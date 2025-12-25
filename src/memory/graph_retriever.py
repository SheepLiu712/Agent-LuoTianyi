"""
图结构检索模块

基于知识图谱的多跳推理检索系统
"""

from typing import Dict, List, Optional, Any, Tuple, Set, Union
from abc import ABC, abstractmethod
from .memory_type import Entity, Relation
import json
import networkx as nx
from .memory_type import GraphEntityType, GraphRelationType

from ..utils.logger import get_logger


class KnowledgeGraph:
    """知识图谱类 (基于 NetworkX 实现)"""

    def __init__(self):
        """初始化知识图谱"""
        self.graph = nx.DiGraph()
        self.entities: Dict[str, Entity] = {}
        self.relations: Dict[str, Relation] = {}
        self.alias_map: Dict[str, str] = {}

    def add_entity(self, entity: Entity) -> None:
        """添加实体"""
        if entity.id in self.entities:
            print(f"实体已存在: {entity.id}")
            return
        self.entities[entity.id] = entity
        self.graph.add_node(entity.id, **entity.properties, type=entity.entity_type, name=entity.name)

    def update_entity(self, entity: Entity) -> None:
        """更新实体"""
        if entity.id not in self.entities:
            print(f"实体不存在: {entity.id}")
            return
        self.entities[entity.id] = entity
        self.graph.nodes[entity.id].update(entity.properties)
        self.graph.nodes[entity.id]["type"] = entity.entity_type
        self.graph.nodes[entity.id]["name"] = entity.name

    def add_relation(self, relation: Relation) -> None:
        """添加关系"""
        if relation.id in self.relations:
            print(f"关系已存在: {relation.id}")
            return
        self.relations[relation.id] = relation
        self.graph.add_edge(
            relation.source_id, relation.target_id, id=relation.id, type=relation.relation_type, **relation.properties
        )

    def has_entity(self, entity_id: str) -> bool:
        """检查实体是否存在"""
        return entity_id in self.entities

    def get_neighbors(
        self,
        entity_id: str,
        direction: str = "outgoing",
        relation_type: Optional[Union[str, GraphRelationType]] = None,
        neighbor_type: Optional[Union[str, GraphEntityType]] = None,
    ) -> List[Tuple[Entity, str]]:
        """获取实体的邻居

        Args:
            entity_id: 实体ID
            direction: 方向 "outgoing", "incoming", "both"
            relation_type: 关系类型过滤

        Returns:
            (邻居实体, 关系类型) 的列表
        """
        if relation_type and hasattr(relation_type, "value"):
            relation_type = relation_type.value
        if neighbor_type and hasattr(neighbor_type, "value"):
            neighbor_type = neighbor_type.value

        if entity_id not in self.graph:
            return []

        results = []
        print(f"获取实体 '{entity_id}' 的邻居，方向: {direction}, 关系类型: {relation_type}, 邻居类型: {neighbor_type}")
        # Outgoing
        if direction in ["outgoing", "both"]:
            for neighbor_id in self.graph.successors(entity_id):
                neighbor_data = self.graph.nodes[neighbor_id]
                n_type = neighbor_data.get("type").value
                if neighbor_type and n_type != neighbor_type:
                    continue
                edge_data = self.graph.get_edge_data(entity_id, neighbor_id)
                r_type = edge_data.get("type").value
                if relation_type and r_type != relation_type:
                    continue
                if neighbor_id in self.entities:
                    results.append((self.entities[neighbor_id], r_type))

        # Incoming
        if direction in ["incoming", "both"]:
            for neighbor_id in self.graph.predecessors(entity_id):
                neighbor_data = self.graph.nodes[neighbor_id]
                # print(neighbor_data)
                n_type = neighbor_data.get("type").value
                if neighbor_type and n_type != neighbor_type:
                    continue
                edge_data = self.graph.get_edge_data(neighbor_id, entity_id)
                r_type = edge_data.get("type").value
                if relation_type and r_type != relation_type:
                    continue
                if neighbor_id in self.entities:
                    results.append((self.entities[neighbor_id], f"<-{r_type}"))

        return results

    def find_path(self, start_id: str, end_id: str, max_depth: int = 3, undirected: bool = False) -> List[List[str]]:
        """查找两个实体间的路径

        Args:
            start_id: 起始ID
            end_id: 结束ID
            max_depth: 最大深度
            undirected: 是否忽略方向（视为无向图）
        """
        if start_id not in self.graph or end_id not in self.graph:
            return []
        try:
            if undirected:
                search_graph = self.graph.to_undirected()
            else:
                search_graph = self.graph

            # 使用 NetworkX 的简单路径算法
            return list(nx.all_simple_paths(search_graph, start_id, end_id, cutoff=max_depth))
        except Exception:
            return []

    def get_entities_by_type(self, entity_type: Union[str, GraphEntityType]) -> List[Entity]:
        """获取指定类型的实体"""
        if hasattr(entity_type, "value"):
            entity_type = entity_type.value

        results = []
        for entity in self.entities.values():
            e_type = entity.entity_type.value
            if e_type == entity_type:
                results.append(entity)
        return results


class GraphRetriever(ABC):
    """图检索器基类"""

    def __init__(self):
        self.knowledge_graph: KnowledgeGraph = KnowledgeGraph()

    @abstractmethod
    def retrieve(self, query: str, entities: List[str], **kwargs) -> List[Dict[str, Any]]:
        """检索相关知识"""
        pass

    @abstractmethod
    def multi_hop_retrieve(self, start_entities: List[str], max_hops: int = 2) -> List[Dict[str, Any]]:
        """多跳检索"""
        pass

    @abstractmethod
    def save_graph_data(self) -> None:
        """保存图数据"""
        pass

    @abstractmethod
    def retrieve_one_entity(self, entity_name: str) -> Optional[Entity]:
        """检索单个实体"""
        pass

    @abstractmethod
    def get_entities_by_type(self, entity_type: Union[str, GraphEntityType]) -> List[Entity]:
        """获取指定类型的实体名称列表"""
        pass

    @abstractmethod
    def retrieve_relation_between_entities(self, entity_a: str, entity_b: str) -> List[Relation]:
        """检索两个实体之间的关系"""
        pass

    @abstractmethod
    def get_neighbors(
        self,
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
        entity_a: str,
        entity_b: str,
        direction: str = "both",
        neighbor_type: Optional[Union[str, GraphEntityType]] = None,
        needed_neighbors: int = -1,
    ) -> List[Entity]:
        """获取两个实体的共同邻居"""
        pass

    @abstractmethod
    def find_connections(self, entity_a: str, entity_b: str, needed_path_num: int = -1) -> List[str]:
        """查找两个实体之间的关联 (LLM工具接口)"""
        pass


class InMemoryGraphRetriever(GraphRetriever):
    """内存图检索器

    用于小规模知识图谱的内存检索
    """

    def __init__(self, config: Dict[str, Any]):
        """初始化内存图检索器

        Args:
            config: 配置字典
        """
        self.logger = get_logger(__name__)
        self.config = config
        self.knowledge_graph = KnowledgeGraph()
        self.graph_data_dir: Optional[str] = config.get("graph_data_dir", None)
        self.graph_data_path: Optional[str] = None
        self.graph_alias_path: Optional[str] = None

        if self.graph_data_dir:
            self.graph_data_path = f"{self.graph_data_dir}/{config.get('graph_data_path', 'knowledge_graph.json')}"
            self.graph_alias_path = f"{self.graph_data_dir}/{config.get('graph_alias_path', 'alias.json')}"
        else:
            raise ValueError("必须在配置中指定 graph_data_dir")

        self.load_graph_data(self.graph_data_path, self.graph_alias_path)

        self.logger.info("内存图检索器初始化完成")

    def load_graph_data(self, data_path: str, alias_path: str) -> None:
        """加载图数据

        Args:
            data_path: 数据文件路径
            alias_path: 别名文件路径
        """
        # make dir if not exist
        graph_data_dir = self.graph_data_dir
        import os

        if not os.path.exists(graph_data_dir):
            os.makedirs(graph_data_dir, exist_ok=True)
        try:
            import json

            with open(data_path, "r", encoding="utf-8") as f:
                data: Dict[str, Any] = json.load(f)

            # 加载实体
            for entity_data in data.get("entities", []):
                entity = Entity(
                    id=entity_data["id"],
                    name=entity_data["name"],
                    entity_type=GraphEntityType(entity_data["type"]),
                    properties=entity_data.get("properties", {}),
                )
                self.knowledge_graph.add_entity(entity)

            # 加载关系
            for relation_data in data.get("relations", []):
                relation = Relation(
                    id=relation_data["id"],
                    source_id=relation_data["source"],
                    target_id=relation_data["target"],
                    relation_type=GraphRelationType(relation_data["type"]),
                    properties=relation_data.get("properties", {}),
                    weight=relation_data.get("weight", 1.0),
                )
                self.knowledge_graph.add_relation(relation)

            self.logger.info(f"加载了 {len(self.knowledge_graph.entities)} 个实体和 {len(self.knowledge_graph.relations)} 个关系")

        except Exception as e:
            self.logger.error(f"加载图数据失败: {e}")

        try:
            with open(alias_path, "r", encoding="utf-8") as f:
                self.knowledge_graph.alias_map = json.load(f)
            self.logger.info(f"加载了 {len(self.knowledge_graph.alias_map)} 条别名映射")
        except Exception as e:
            self.logger.error(f"加载别名映射失败: {e}")
            self.knowledge_graph.alias_map = {}

    def save_graph_data(self) -> None:
        """保存图数据

        Args:
            data_path: 数据文件路径
        """
        data_path = self.graph_data_path
        try:
            import json

            data = {
                "entities": [
                    {"id": entity.id, "name": entity.name, "type": entity.entity_type.value, "properties": entity.properties}
                    for entity in self.knowledge_graph.entities.values()
                ],
                "relations": [
                    {
                        "id": relation.id,
                        "source": relation.source_id,
                        "target": relation.target_id,
                        "type": relation.relation_type.value,
                        "properties": relation.properties,
                        "weight": relation.weight,
                    }
                    for relation in self.knowledge_graph.relations.values()
                ],
            }
            with open(data_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            self.logger.info(f"图数据已保存到 {data_path}")
        except Exception as e:
            self.logger.error(f"保存图数据失败: {e}")

    def save_alias_map(self) -> None:
        try:
            alias_path = self.graph_alias_path
            with open(alias_path, "w", encoding="utf-8") as f:
                json.dump(self.knowledge_graph.alias_map, f, ensure_ascii=False, indent=4)
            self.logger.info(f"别名映射已保存到 {alias_path}")
        except Exception as e:
            self.logger.error(f"保存别名映射失败: {e}")

    def get_aliased_name(self, entity_id: str) -> str:
        """
        考虑输入的是别名，返回标准实体名称
        """
        if not entity_id:
            return entity_id
        if entity_id in self.knowledge_graph.entities.keys():
            return entity_id
        if entity_id.lower() in self.knowledge_graph.entities.keys():
            return entity_id.lower()
        if entity_id in self.knowledge_graph.alias_map:
            return self.knowledge_graph.alias_map[entity_id]
        if entity_id.lower() in self.knowledge_graph.alias_map:
            return self.knowledge_graph.alias_map[entity_id.lower()]
        
        # 如果在别名映射中找不到，尝试在实体名称中进行模糊匹配
        def get_maximum_common_substring_length(s1: str, s2: str) -> int:
            """获取两个字符串的最大公共子串长度"""
            m = len(s1)
            n = len(s2)
            max_len = 0
            dp = [[0] * (n + 1) for _ in range(m + 1)]
            for i in range(1, m + 1):
                for j in range(1, n + 1):
                    if s1[i - 1] == s2[j - 1]:
                        dp[i][j] = dp[i - 1][j - 1] + 1
                        max_len = max(max_len, dp[i][j])
            return max_len
        # 找最大公共子串
        max_common_length = 0
        entity_id_len = len(entity_id)
        best_match = None
        for standard_name in self.knowledge_graph.entities.keys():
            common_length = get_maximum_common_substring_length(entity_id, standard_name)
            if common_length > max_common_length and common_length >= max(entity_id_len / 2, 2):
                max_common_length = common_length
                best_match = standard_name
        
        if best_match is not None:
            self.knowledge_graph.alias_map[entity_id] = best_match  # 添加到别名映射
            self.save_alias_map()

        return best_match

    def retrieve(self, query: str, entities: List[str], **kwargs) -> List[Dict[str, Any]]:
        """检索相关知识

        Args:
            query: 查询文本
            entities: 相关实体列表
            **kwargs: 额外参数

        Returns:
            检索结果列表
        """
        results = []

        for entity_name in entities:
            # 查找实体
            entity = self._find_entity_by_name(entity_name)
            if not entity:
                continue

            # 获取邻居实体和关系
            neighbors = self.knowledge_graph.get_neighbors(entity.id)

            for neighbor, relation_type in neighbors:
                result = {
                    "source_entity": entity.name,
                    "target_entity": neighbor.name,
                    "relation": relation_type,
                    "properties": neighbor.properties,
                }
                results.append(result)

        return results

    def multi_hop_retrieve(self, start_entities: List[str], max_hops: int = 2) -> List[Dict[str, Any]]:
        """多跳检索

        Args:
            start_entities: 起始实体列表
            max_hops: 最大跳数

        Returns:
            多跳检索结果
        """
        results = []

        for entity_name in start_entities:
            entity = self._find_entity_by_name(entity_name)
            if not entity:
                continue

            # 如果指定了 end_entity (在 kwargs 中) 则查找路径
            # 注意：这里假设 kwargs 是通过 retrieve 传递下来的，或者直接调用
            # 但 multi_hop_retrieve 签名没有 kwargs，这里只能做简单的邻居扩展

            neighbors = self.knowledge_graph.get_neighbors(entity.id)
            for neighbor, r_type in neighbors:
                results.append(
                    {"start_entity": entity.name, "path": [entity.id, neighbor.id], "hop_count": 1, "relation": r_type}
                )

        return results

    def _find_entity_by_name(self, name: str) -> Optional[Entity]:
        """根据名称查找实体

        Args:
            name: 实体名称

        Returns:
            实体对象或None
        """
        for entity in self.knowledge_graph.entities.values():
            if entity.name == name:
                return entity
        return None

    def retrieve_one_entity(self, entity_name: str) -> Optional[Entity]:
        """检索单个实体"""
        aliased_name = self.get_aliased_name(entity_name)
        return self.knowledge_graph.entities.get(aliased_name)

    def get_entities_by_type(self, entity_type: Union[str, GraphEntityType]) -> List[Entity]:
        """获取指定类型的实体名称列表"""
        entities = self.knowledge_graph.get_entities_by_type(entity_type)
        return entities

    def retrieve_relation_between_entities(self, entity_a: str, entity_b: str) -> List[Relation]:
        """检索两个实体之间的关系"""
        relations = []
        if entity_a not in self.knowledge_graph.entities or entity_b not in self.knowledge_graph.entities:
            return relations

        # 检查从 A 到 B 的关系
        if self.knowledge_graph.graph.has_edge(entity_a, entity_b):
            edge_data = self.knowledge_graph.graph.get_edge_data(entity_a, entity_b)
            relation = Relation(
                id=edge_data.get("id", f"{entity_a}_{entity_b}"),
                source_id=entity_a,
                target_id=entity_b,
                relation_type=GraphRelationType(edge_data.get("type")),
                properties={k: v for k, v in edge_data.items() if k not in ["type", "id"]},
            )
            relations.append(relation)

        # 检查从 B 到 A 的关系
        if self.knowledge_graph.graph.has_edge(entity_b, entity_a):
            edge_data = self.knowledge_graph.graph.get_edge_data(entity_b, entity_a)
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
        entity_name: str,
        direction="both",
        relation_type: Optional[Union[str, GraphRelationType]] = None,
        neighbor_type: Optional[Union[str, GraphEntityType]] = None,
        needed_neighbors: int = -1,
    ):
        """获取实体的邻居"""
        neighbors = self.knowledge_graph.get_neighbors(entity_name, direction, relation_type, neighbor_type)
        if needed_neighbors > 0:
            neighbors = neighbors[:needed_neighbors]
        return neighbors

    def get_shared_neighbors(
        self,
        entity_a: str,
        entity_b: str,
        direction="both",
        neighbor_type: Optional[Union[str, GraphEntityType]] = None,
        needed_neighbors=-1,
    ) -> List[Entity]:
        print(f"查找 '{entity_a}' 和 '{entity_b}' 的共享邻居...")
        neighbors_a = self.knowledge_graph.get_neighbors(entity_a, direction, neighbor_type=neighbor_type)
        neighbors_b = self.knowledge_graph.get_neighbors(entity_b, direction, neighbor_type=neighbor_type)
        set_a: Set[str] = set([n.id for n, _ in neighbors_a])
        set_b: Set[str] = set([n.id for n, _ in neighbors_b])
        shared_ids = set_a.intersection(set_b)
        shared_neighbors = []
        for n_id in shared_ids:
            neighbor_entity = self.knowledge_graph.entities[n_id]
            shared_neighbors.append(neighbor_entity)  # 关系类型未知
        if needed_neighbors > 0:
            shared_neighbors = shared_neighbors[:needed_neighbors]
        return shared_neighbors

    def find_connections(self, entity_a: str, entity_b: str, needed_path_num: int = -1) -> List[str]:
        """查找两个实体之间的关联路径"""
        # 使用无向搜索以忽略方向
        paths = self.knowledge_graph.find_path(entity_a, entity_b, max_depth=3, undirected=True)
        readable_paths = []
        for path in paths:
            # 将ID路径转换为可读描述
            desc = []
            for i in range(len(path) - 1):
                u, v = path[i], path[i + 1]

                # 尝试获取正向边
                edge_data = self.knowledge_graph.graph.get_edge_data(u, v)
                if edge_data:
                    r_type = edge_data.get("type", "RELATED_TO")
                    desc.append(f"{u} --[{r_type}]--> {v}")
                else:
                    # 尝试获取反向边
                    edge_data = self.knowledge_graph.graph.get_edge_data(v, u)
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
