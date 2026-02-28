"""
知识图谱数据结构
"""

from typing import Dict, List, Optional, Any, Tuple, Set, Union
import json
import networkx as nx
from ..types.memory_type import Entity, Relation, GraphEntityType, GraphRelationType
from ..utils.logger import get_logger
import os

class KnowledgeGraph:
    """知识图谱类 (基于 NetworkX 实现)"""

    def __init__(self, config: Dict[str, Any]):
        """初始化知识图谱"""
        self.logger = get_logger(__name__)
        self.graph = nx.DiGraph()
        self.entities: Dict[str, Entity] = {}
        self.relations: Dict[str, Relation] = {}
        self.alias_map: Dict[str, str] = {}
        
        self.config = config
        self.graph_data_dir: Optional[str] = config.get("graph_data_dir", None)
        self.graph_data_path: Optional[str] = None
        self.graph_alias_path: Optional[str] = None

        if self.graph_data_dir:
            self.graph_data_path = f"{self.graph_data_dir}/{config.get('graph_data_path', 'knowledge_graph.json')}"
            self.graph_alias_path = f"{self.graph_data_dir}/{config.get('graph_alias_path', 'alias.json')}"
        else:
             raise ValueError("必须在配置中指定 graph_data_dir")

        self.load_graph_data(self.graph_data_path, self.graph_alias_path)
        self.logger.info("知识图谱初始化完成")

    def add_entity(self, entity: Entity) -> None:
        """添加实体"""
        if entity.id in self.entities:
            # print(f"实体已存在: {entity.id}")
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
            # print(f"关系已存在: {relation.id}")
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
        # print(f"获取实体 '{entity_id}' 的邻居，方向: {direction}, 关系类型: {relation_type}, 邻居类型: {neighbor_type}")
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

    def load_graph_data(self, data_path: str, alias_path: str) -> None:
        """加载图数据

        Args:
            data_path: 数据文件路径
            alias_path: 别名文件路径
        """
        # make dir if not exist
        if self.graph_data_dir and not os.path.exists(self.graph_data_dir):
            os.makedirs(self.graph_data_dir, exist_ok=True)
            
        try:
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
                self.add_entity(entity)

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
                self.add_relation(relation)

            self.logger.info(f"加载了 {len(self.entities)} 个实体和 {len(self.relations)} 个关系")

        except Exception as e:
            self.logger.error(f"加载图数据失败: {e}")

        try:
            with open(alias_path, "r", encoding="utf-8") as f:
                self.alias_map = json.load(f)
            self.logger.info(f"加载了 {len(self.alias_map)} 条别名映射")
        except Exception as e:
            self.logger.error(f"加载别名映射失败: {e}")
            self.alias_map = {}

    def save_graph_data(self) -> None:
        """保存图数据"""
        data_path = self.graph_data_path
        if not data_path:
             self.logger.error("未指定数据路径，无法保存")
             return
             
        try:
            data = {
                "entities": [
                    {"id": entity.id, "name": entity.name, "type": entity.entity_type.value, "properties": entity.properties}
                    for entity in self.entities.values()
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
                    for relation in self.relations.values()
                ],
            }
            with open(data_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            self.logger.info(f"图数据已保存到 {data_path}")
        except Exception as e:
            self.logger.error(f"保存图数据失败: {e}")

    def save_alias_map(self) -> None:
        alias_path = self.graph_alias_path
        if not alias_path:
             return
             
        try:
            with open(alias_path, "w", encoding="utf-8") as f:
                json.dump(self.alias_map, f, ensure_ascii=False, indent=4)
            self.logger.info(f"别名映射已保存到 {alias_path}")
        except Exception as e:
            self.logger.error(f"保存别名映射失败: {e}")

    def get_aliased_name(self, entity_id: str) -> str:
        """
        考虑输入的是别名，返回标准实体名称
        """
        if not entity_id:
            return entity_id
        if entity_id in self.entities.keys():
            return entity_id
        if entity_id.lower() in self.entities.keys():
            return entity_id.lower()
        if entity_id in self.alias_map:
            return self.alias_map[entity_id]
        if entity_id.lower() in self.alias_map:
            return self.alias_map[entity_id.lower()]
        
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
        for standard_name in self.entities.keys():
            common_length = get_maximum_common_substring_length(entity_id, standard_name)
            if common_length > max_common_length and common_length >= max(entity_id_len / 2, 2):
                max_common_length = common_length
                best_match = standard_name
        
        if best_match is not None:
            self.alias_map[entity_id] = best_match  # 添加到别名映射
            self.save_alias_map()

        return best_match


knowledge_graph = None

def init_knowledge_graph(config: Dict[str, Any]):
    global knowledge_graph
    knowledge_graph = KnowledgeGraph(config)

def get_knowledge_graph() -> KnowledgeGraph:
    global knowledge_graph
    if knowledge_graph is None:
        raise Exception("KnowledgeGraph not initialized")
    return knowledge_graph