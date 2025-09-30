import sys
import os
import json
from pathlib import Path
from typing import Dict, List, Any

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.knowledge.knowledge_builder import KnowledgeBuilder
from src.knowledge.vector_store import VectorStoreFactory
from src.knowledge.graph_retriever import GraphRetrieverFactory
from src.utils.logger import setup_logging, get_logger
from src.utils.helpers import load_config

def main():
    """主函数"""
    # 设置日志
    setup_logging({
        "level": "INFO",
        "console_output": True,
        "file_output": True
    })
    
    logger = get_logger(__name__)
    logger.info("开始初始化洛天依知识库")
    
    try:
        # 加载配置
        config_path = project_root / "config" / "config.json"
        config = load_config(str(config_path))
        
        # 初始化向量存储
        vector_config = config.get("knowledge", {}).get("vector_store", {})
        vector_store = VectorStoreFactory.create_vector_store("chroma", vector_config)

        while True:
            query = input("请输入查询内容（输入 'exit' 退出）：")
            if query.lower() == 'exit':
                break
            ret = vector_store.search(query, k=5)

            print(f"查询：{query}")
            for doc, distance in ret:
                print(f"相似度: {1.0 - distance:.4f},  内容: {doc.page_content}")
    except Exception as e:
        logger.error(f"知识库初始化失败: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()