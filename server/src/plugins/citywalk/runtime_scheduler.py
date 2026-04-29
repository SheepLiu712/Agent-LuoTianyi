from typing import Any, Optional

from ...utils.logger import get_logger
from .amap_client import AMapClient
from .config import load_citywalk_config
from .memory_ingestor import CitywalkMemoryIngestor
from .report_generator import CitywalkReportGenerator
from .session_runner import CitywalkSessionRunner


class CitywalkRuntimeService:
    def __init__(self, config_path: str, vector_store: Any):
        self.logger = get_logger(__name__)
        self.config_path = config_path
        self.vector_store = vector_store

    def run_once(self) -> Optional[str]:
        cfg = load_citywalk_config(self.config_path)
        client = AMapClient(cfg)
        runner = CitywalkSessionRunner(cfg, client)

        result = runner.run()
        report_cfg = cfg.get("report", {})
        generator = CitywalkReportGenerator(
            title_prefix=report_cfg.get("title_prefix", "逛街小洛"),
            history_file=report_cfg.get("history_file", "data/citywalk_reports/citywalk_history.json"),
        )
        output_path = generator.save(result, report_cfg.get("output_dir", "data/citywalk_reports"))

        ingestor = CitywalkMemoryIngestor(cfg, self.vector_store)
        count = ingestor.ingest_session(result)
        self.logger.info("城市漫步完成, 事件数=%s, 记忆写入=%s, 报告=%s", len(result.events), count, output_path)
        return output_path
