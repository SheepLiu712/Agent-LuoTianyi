
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

entities = graph_retriever.get_entities_by_type(GraphEntityType.PERSON)
for ent in entities:
    entity = graph_retriever.retrieve_one_entity(ent)
    if entity:
        try:
            with open(f"data/crawled_data/person/{entity.name}.json", "r", encoding="utf-8") as f:
                entity_new_data = json.load(f)
                entity.properties.update({"summary": entity_new_data.get("summary", "")})
                graph_retriever.knowledge_graph.update_entity(entity)
        except Exception as e:
            print(f"Error updating entity {entity.name}: {e}")

graph_retriever.save_graph_data()
