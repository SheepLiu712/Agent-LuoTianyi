import sys
import os
import json
from pathlib import Path
from typing import Dict, List, Any

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.knowledge.vector_store import VectorStoreFactory, ThreeTupleDocument
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
        vector_store = VectorStoreFactory.create_vector_store("custom", vector_config)

        # results = vector_store.search("殿堂曲")
        # for doc, similarity in results:
        #     print(f"相似度: {similarity:.4f},  内容: {doc.page_content}")
        
        # knowledge_path = project_root / "data" / "MemoryReadable" / "memory_stable.json"
        # import json
        # with open(knowledge_path, 'r', encoding='utf-8') as f:
        #     knowledge_data = json.load(f)
        # for key, value in knowledge_data.items():
        #     knowledge_list = value
        #     for term in knowledge_list:
        #         s,r,o = term
        #         doc = ThreeTupleDocument(s,r,o,key)
        #         vector_store.add_documents([doc])
        
        # vector_store.save_vector_store()

        while True:
            query = input("请输入查询内容（输入 'exit' 退出）：")
            if query.lower() == 'exit':
                break
            ret = vector_store.search(query, k=3)

            print(f"查询：{query}")
            idx = 0
            for doc, distance in ret:
                print(f"[{idx}] 相似度: {distance:.4f},  内容: {doc.page_content}")
                idx += 1

    except Exception as e:
        logger.error(f"知识库初始化失败: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()