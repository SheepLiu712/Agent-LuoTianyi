"""
Memory Search Module
--------------------
负责记忆的检索（Recall）。
核心难点在于如何根据用户模糊的输入，精确召回相关记忆。
"""

from ..utils.logger import get_logger
from .vector_store import VectorStore
from .graph_retriever import GraphRetriever
from ..llm.prompt_manager import PromptManager
from ..llm.llm_module import LLMModule
from ..utils.vcpedia_fetcher import VCPediaFetcher
from typing import Tuple, Dict, List, Any, Set


class MemorySearcher:
    def __init__(
        self, config: Dict[str, Any], vector_store: VectorStore, graph_retriever: GraphRetriever, prompt_manager: PromptManager
    ):
        self.logger = get_logger(__name__)
        self.config = config
        self.vector_store = vector_store
        self.graph_retriever = graph_retriever
        self.llm = LLMModule(config["llm_module"], prompt_manager)
        self.max_k_vector_entities = config.get("max_k_vector_entities", 3)
        self.max_k_graph_entities = config.get("max_k_graph_entities", 3)
        self.used_uuid: Set[str] = set()
        self.vcpedia_fetcher = VCPediaFetcher(config.get("crawler", {}))

    def search(self, user_input: str, history: List[str]) -> List[str]:
        """
        执行混合检索策略
        """
        # 1. 查询理解与扩展 (Query Expansion)
        # 利用LLM将用户的自然语言转换为具体的搜索意图
        search_queries = self._generate_search_queries(user_input, history)

        funcname_project_dict = {
            "v_search": self._vector_search,
            "g_search_entity": self._retrieve_one_entity,
            "get_neighbors": self._get_neighbors,
            "get_shared_neighbors": self._get_shared_neighbors,
            "find_connections": self._find_connections,
        }
        returned_results = []
        for funcname, kwargs in search_queries:
            if funcname not in funcname_project_dict:
                self.logger.warning(f"Unknown search function: {funcname}")
                continue
            search_func = funcname_project_dict[funcname]
            try:
                result = search_func(**kwargs)
                if isinstance(result, list):
                    returned_results.extend(result)
                else:
                    returned_results.append(result)
            except Exception as e:
                self.logger.error(f"Error executing {funcname} with args {kwargs}: {e}")

        return returned_results

    def _generate_search_queries(self, user_input: str, history: List[str]) -> List[Tuple[str, Dict[str, str]]]:
        """
        使用LLM分析用户意图，生成搜索查询。
        这是提高召回率的关键步骤：将"记得那首歌吗"转换为"用户上次提到的歌曲"。
        """
        self.used_uuid.clear()
        cmd: List[Tuple[str, Dict[str, str]]] = []
        try:
            response = self.llm.generate_response(
                user_input=user_input,
                history=history,
                max_k_graph_entities=self.max_k_graph_entities,
                max_k_vector_entities=self.max_k_vector_entities,
            )
            response = response.split("\n")
            self.logger.debug(f"Generated search queries: {response}")

            for line in response:
                if line.startswith("##"):
                    break
                if line == "":
                    continue
                if "(" not in line or ")" not in line:
                    self.logger.warning(f"Unrecognized command format: {line}")
                    continue
                funcname, args_str = line.split("(", 1)
                args_str = args_str.rstrip(")")
                kwargs = {}
                for arg in args_str.split(","):
                    key, value = arg.split("=", 1)
                    kwargs[key.strip()] = value.strip().strip("\'").strip('\"')  
                cmd.append((funcname.strip(), kwargs))
        except Exception as e:
            self.logger.error(f"Error generating search queries: {e}")
        finally:
            return cmd
    
    def _vector_search(self, query: str) -> List[str]:
        """
        基于向量检索的记忆搜索
        """
        results = self.vector_store.search(query, k=self.max_k_vector_entities)
        combined_result = []
        for doc, score in results:
            if doc.id not in self.used_uuid:
                timestamp = doc.metadata.get("timestamp", "unknown time")
                combined_result.append(f" ({timestamp}) {doc.get_content()}")
                self.used_uuid.add(doc.id)
        return combined_result

    def _retrieve_one_entity(self, entity_name: str) -> str:
        """
        根据实体名称检索单个实体
        """
        entity_name = entity_name.strip("\'\"《》").strip()
        entity = self.graph_retriever.retrieve_one_entity(entity_name)
        if entity and entity.properties.get("summary", ""):
            return entity.properties.get("summary", "")
        
        # 尝试从vcpedia抓取内容
        vcpedia_content = self.vcpedia_fetcher.fetch_entity_description(entity_name)
        return vcpedia_content or f"未找到关于{entity_name}的相关信息。"
    
    def _get_neighbors(self, entity_name: str, neighbor_type: str) -> List[str]:
        """
        获取指定实体的邻居节点
        """
        neighbors = self.graph_retriever.get_neighbors(entity_name, neighbor_type=neighbor_type, needed_neighbors=self.max_k_graph_entities)
        ret = []
        for neighbor, _ in neighbors:
            ret.append(f"{neighbor.name}: {neighbor.properties.get('summary', '')}")
        return ret
    
    def _get_shared_neighbors(self, entity_name1: str, entity_name2: str, neighbor_type: str) -> List[str]:
        """
        获取两个实体的共同邻居节点
        """
        shared_neighbors = self.graph_retriever.get_shared_neighbors(
            entity_name1, entity_name2, neighbor_type=neighbor_type, needed_neighbors=self.max_k_graph_entities
        )
        ret = []
        for neighbor in shared_neighbors:
            ret.append(f"{neighbor.name}: {neighbor.properties.get('summary', '')}")
        return ret
    
    def _find_connections(self, entity_name1: str, entity_name2: str) -> List[str]:
        """
        查找两个实体之间的连接路径
        """
        connections = self.graph_retriever.find_connections(entity_name1, entity_name2, needed_path_num=self.max_k_graph_entities)
        return connections