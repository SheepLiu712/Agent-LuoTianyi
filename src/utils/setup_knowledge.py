"""
知识库初始化脚本

构建和初始化洛天依知识库
"""

import sys
import os
import json
from pathlib import Path
from typing import Dict, List, Any

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.memory.knowledge_builder import KnowledgeBuilder
from src.memory.vector_store import VectorStoreFactory
from src.memory.graph_retriever import GraphRetrieverFactory
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
        
        # 初始化图检索器（可选）
        graph_retriever = None
        # if "graph_store" in config.get("knowledge", {}):
        #     graph_config = config["knowledge"]["graph_store"]
        #     try:
        #         graph_retriever = GraphRetrieverFactory.create_retriever(
        #             graph_config.get("type", "memory"), 
        #             graph_config
        #         )
        #     except Exception as e:
        #         logger.warning(f"图检索器初始化失败，将跳过: {e}")
        
        # 创建知识库构建器
        builder = KnowledgeBuilder(vector_store, graph_retriever, config)
        
        # 数据目录
        data_dir = project_root / "data" / "knowledge_base"
        
        # 检查数据目录
        if not data_dir.exists():
            logger.info("创建知识库数据目录")
            data_dir.mkdir(parents=True, exist_ok=True)
            
            # 创建示例知识数据
            create_sample_knowledge(data_dir)
        
        # 构建知识库
        logger.info(f"从目录构建知识库: {data_dir}")
        builder.build_from_directory(str(data_dir))
        
        # 获取统计信息
        stats = builder.get_statistics()
        logger.info(f"知识库构建完成: {stats}")
        
        print("\n" + "="*50)
        print("🎵 洛天依知识库初始化完成 🎵")
        print("="*50)
        print(f"数据目录: {data_dir}")
        print(f"文档数量: {stats.get('total_documents', 0)}")
        print("="*50 + "\n")
        
    except Exception as e:
        logger.error(f"知识库初始化失败: {e}")
        print(f"❌ 初始化失败: {e}")
        return 1
    
    return 0


def create_sample_knowledge(data_dir: Path) -> None:
    """创建示例知识数据
    
    Args:
        data_dir: 数据目录
    """
    logger = get_logger(__name__)
    logger.info("创建示例知识数据")
    
    # 洛天依基本信息
    persona_data = {
        "title": "洛天依基本信息",
        "category": "persona",
        "content": """洛天依是中国第一位Vocaloid中文声库，由上海禾念信息科技有限公司开发。
        她的生日是7月12日，身高156cm，代表色是灰绿色。
        洛天依的性格活泼可爱，有亲和力，喜欢与粉丝互动。
        她最喜欢吃包子，特别是灌汤包。
        她的梦想是成为优秀的歌手，为大家带来美妙的音乐。""",
        "tags": ["基本信息", "人设", "性格"],
        "source": "官方设定"
    }
    
    # 代表歌曲信息
    songs_data = [
        {
            "title": "普通DISCO",
            "category": "songs",
            "content": """《普通DISCO》是洛天依的热门歌曲之一，发布于2017年。
            这是一首充满活力的电子舞曲，展现了洛天依青春活泼的一面。
            歌曲节奏欢快，深受粉丝喜爱。""",
            "tags": ["代表作", "电子舞曲", "2017年"],
            "album": "单曲",
            "release_date": "2017",
            "source": "歌曲信息"
        },
        {
            "title": "权御天下",
            "category": "songs", 
            "content": """《权御天下》是洛天依的经典古风歌曲，发布于2013年。
            这首歌气势磅礴，展现了不同于平时可爱形象的另一面。
            是洛天依古风系列的代表作品之一。""",
            "tags": ["代表作", "古风", "2013年"],
            "album": "单曲",
            "release_date": "2013",
            "source": "歌曲信息"
        },
        {
            "title": "九九八十一",
            "category": "songs",
            "content": """《九九八十一》是洛天依演唱的西游记主题古风歌曲，发布于2014年。
            歌曲以西游记的故事为背景，展现了唐僧师徒的取经之路。
            这首歌旋律优美，歌词富有深意。""",
            "tags": ["古风", "西游记", "2014年"],
            "album": "单曲",
            "release_date": "2014",
            "source": "歌曲信息"
        }
    ]
    
    # 活动演出信息
    events_data = [
        {
            "title": "洛天依生日会2024",
            "category": "events",
            "content": """2024年洛天依生日会在7月12日举行，庆祝洛天依的生日。
            活动包括歌曲演出、粉丝互动等环节。
            现场演唱了多首经典歌曲，包括《普通DISCO》、《权御天下》等。""",
            "date": "2024-07-12",
            "location": "线上直播",
            "tags": ["生日会", "2024年", "演出"],
            "source": "活动信息"
        }
    ]
    
    # 保存数据文件
    files_to_create = [
        ("persona.json", [persona_data]),
        ("songs.json", songs_data),
        ("events.json", events_data)
    ]
    
    for filename, data in files_to_create:
        file_path = data_dir / filename
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"创建示例数据文件: {filename}")
    
    # 创建文本格式的知识
    readme_content = """# 洛天依知识库

这里包含了洛天依的各种信息，包括：

## 人设信息
- 基本资料和性格特征
- 喜好和特点

## 歌曲作品
- 代表歌曲和专辑
- 歌词和创作背景

## 活动演出
- 演唱会和活动记录
- 重要时间节点

## 社交媒体
- 官方动态和粉丝互动
- 相关新闻和资讯
"""
    
    readme_path = data_dir / "README.md"
    with open(readme_path, 'w', encoding='utf-8') as f:
        f.write(readme_content)
    
    logger.info("示例知识数据创建完成")


def add_custom_knowledge():
    """添加自定义知识的示例"""
    print("\n如果您有额外的知识数据，可以：")
    print("1. 将JSON/YAML文件放入 data/knowledge_base/ 目录")
    print("2. 使用程序API动态添加知识")
    print("3. 重新运行此脚本更新知识库")


if __name__ == "__main__":
    exit_code = main()
    if exit_code == 0:
        add_custom_knowledge()
    sys.exit(exit_code)
