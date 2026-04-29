import argparse
import os
import sys

cwd = os.getcwd()
sys.path.insert(0, str(cwd))

from src.plugins.citywalk.amap_client import AMapClient
from src.plugins.citywalk.config import load_citywalk_config
from src.plugins.citywalk.report_generator import CitywalkReportGenerator
from src.plugins.citywalk.session_runner import CitywalkSessionRunner


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one citywalk session and generate JSON report")
    parser.parse_args()

    cfg = load_citywalk_config("config/config.json")
    client = AMapClient(cfg)
    runner = CitywalkSessionRunner(cfg, client)
    result = runner.run()

    generator = CitywalkReportGenerator(
        title_prefix=cfg["report"].get("title_prefix", "逛街小洛"),
        history_file=cfg["report"].get("history_file", "data/citywalk_reports/citywalk_history.json"),
    )
    output_path = generator.save(result, cfg["report"].get("output_dir", "data/citywalk_reports"))

    print(f"Session完成, 事件数: {len(result.events)}")
    print(f"报告输出: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
