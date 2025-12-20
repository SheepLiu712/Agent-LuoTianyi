
import sys
import os
from pathlib import Path
import json
import networkx as nx

# Add src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.memory.graph_retriever import GraphRetrieverFactory, InMemoryGraphRetriever
from src.memory.memory_type import Entity, Relation, GraphEntityType, GraphRelationType
from src.utils.helpers import load_config

def merge_events():
    config_path = project_root / "config" / "config.json"
    if not config_path.exists():
        print(f"Config file not found at {config_path}")
        return
        
    config = load_config(str(config_path))
    
    memory_config = config.get("memory_manager", {})
    graph_retriever_config = memory_config.get("graph_retriever", {})
    
    # Force using InMemoryGraphRetriever to access internal structures
    print("Initializing GraphRetriever...")
    retriever = GraphRetrieverFactory.create_retriever(graph_retriever_config["retriever_type"], graph_retriever_config)
    
    if not isinstance(retriever, InMemoryGraphRetriever):
        print("Error: This script only supports InMemoryGraphRetriever")
        return

    kg = retriever.knowledge_graph
    
    target_name = "洛天依2025“无限共鸣·流光协奏”全息巡回演唱会"
    search_keyword = "流光协奏"
    target_type = GraphEntityType.EVENT
    
    # 1. Find nodes to merge
    nodes_to_merge = []
    for entity in kg.entities.values():
        if entity.entity_type == target_type and search_keyword in entity.name:
            nodes_to_merge.append(entity)
            
    if not nodes_to_merge:
        print(f"No nodes found containing '{search_keyword}' with type {target_type}")
        return

    print(f"Found {len(nodes_to_merge)} nodes to merge:")
    for node in nodes_to_merge:
        print(f" - {node.name} ({node.id})")

    # 2. Create or get target node
    if kg.has_entity(target_name):
        target_entity = kg.entities[target_name]
        print(f"Target entity '{target_name}' already exists.")
    else:
        print(f"Creating target entity '{target_name}'...")
        target_entity = Entity(
            id=target_name,
            name=target_name,
            entity_type=target_type,
            properties={}
        )
        kg.add_entity(target_entity)

    # 3. Merge relations
    relations_to_add = []
    entities_to_remove = []

    for source_entity in nodes_to_merge:
        if source_entity.id == target_entity.id:
            continue
            
        print(f"Merging '{source_entity.name}' into '{target_entity.name}'...")
        
        # Incoming edges (Something -> Source)
        for pred_id in kg.graph.predecessors(source_entity.id):
            edge_data = kg.graph.get_edge_data(pred_id, source_entity.id)
            relation_type = edge_data.get("type")
            props = {k: v for k, v in edge_data.items() if k != "type"}
            
            # Ensure relation_type is GraphRelationType enum
            if isinstance(relation_type, str):
                try:
                    relation_type = GraphRelationType(relation_type)
                except ValueError:
                    # Fallback if not a standard relation type, though it should be
                    pass

            # Construct new relation ID
            # Use .value if it's an Enum, otherwise str()
            rel_type_str = relation_type.value if hasattr(relation_type, "value") else str(relation_type)
            
            new_rel_id = f"{pred_id}_{rel_type_str}_{target_entity.id}"
            
            new_relation = Relation(
                id=new_rel_id,
                source_id=pred_id,
                target_id=target_entity.id,
                relation_type=relation_type,
                properties=props
            )
            relations_to_add.append(new_relation)

        # Outgoing edges (Source -> Something)
        for succ_id in kg.graph.successors(source_entity.id):
            edge_data = kg.graph.get_edge_data(source_entity.id, succ_id)
            relation_type = edge_data.get("type")
            props = {k: v for k, v in edge_data.items() if k != "type"}
            
            if isinstance(relation_type, str):
                try:
                    relation_type = GraphRelationType(relation_type)
                except ValueError:
                    pass

            rel_type_str = relation_type.value if hasattr(relation_type, "value") else str(relation_type)
            
            new_rel_id = f"{target_entity.id}_{rel_type_str}_{succ_id}"
            
            new_relation = Relation(
                id=new_rel_id,
                source_id=target_entity.id,
                target_id=succ_id,
                relation_type=relation_type,
                properties=props
            )
            relations_to_add.append(new_relation)

        entities_to_remove.append(source_entity.id)

    if not entities_to_remove:
        print("No entities to remove (maybe only target entity matched).")
        return

    # Apply changes
    print("Applying changes...")
    
    # 1. Add new relations
    for rel in relations_to_add:
        kg.add_relation(rel)
        
    # 2. Remove old entities and their incident relations from internal dicts
    
    # Build a set of relation IDs to remove
    rel_ids_to_remove = set()
    for rel_id, rel in kg.relations.items():
        if rel.source_id in entities_to_remove or rel.target_id in entities_to_remove:
            rel_ids_to_remove.add(rel_id)
            
    for rel_id in rel_ids_to_remove:
        if rel_id in kg.relations:
            del kg.relations[rel_id]
        
    for entity_id in entities_to_remove:
        if entity_id in kg.entities:
            del kg.entities[entity_id]
        if kg.graph.has_node(entity_id):
            kg.graph.remove_node(entity_id)
            
    print(f"Merged {len(entities_to_remove)} entities.")
    print(f"Added {len(relations_to_add)} new relations.")
    print(f"Removed {len(rel_ids_to_remove)} old relations.")
    
    # Save
    print("Saving graph data...")
    retriever.save_graph_data()
    print("Done.")

if __name__ == "__main__":
    merge_events()
