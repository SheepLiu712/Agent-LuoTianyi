
import json
import os
import time
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.memory.knowledge_builder import KnowledgeBuilder
from src.memory.graph_retriever import GraphRetrieverFactory
from src.memory.memory_type import Entity, GraphEntityType
from src.utils.helpers import load_config

config = load_config(str(project_root / "config" / "config.json"))

memory_config = config.get("memory_manager", {})
graph_retriever_config = memory_config.get("graph_retriever", {})
graph_retriever = GraphRetrieverFactory.create_retriever(graph_retriever_config["retriever_type"], graph_retriever_config)

# entity = graph_retriever.retrieve_one_entity("为了你唱下去")  # 示例调用
# if entity:
#     print(f"实体名称: {entity.name}")
#     print(f"属性: {entity.properties}")

# entity_list = graph_retriever.get_shared_neighbors("洛天依", "ilem", neighbor_type=GraphEntityType.SONG)
# for entity in entity_list:
#     print(f"共享邻居实体: {entity.name}")

entity = graph_retriever.retrieve_one_entity("阿良良")
if entity:
    print(f"实体名称: {entity.name}")
    print(f"属性: {entity.properties}")