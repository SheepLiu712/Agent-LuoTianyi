
import json
import os
import time
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.memory.knowledge_builder import KnowledgeBuilder
from src.memory.graph_retriever import GraphRetrieverFactory
from src.utils.helpers import load_config

config = load_config(str(project_root / "config" / "config.json"))

memory_config = config.get("memory_manager", {})
graph_retriever_config = memory_config.get("graph_retriever", {})
graph_retriever = GraphRetrieverFactory.create_retriever(graph_retriever_config["retriever_type"], graph_retriever_config)

builder = KnowledgeBuilder(
    vector_store=None,  # 假设不需要向量存储
    graph_retriever=graph_retriever,
    config=config
)

builder.build_from_directory("data/crawled_data/vcpedia")