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
    parser = argparse.ArgumentParser(description="Run one citywalk session and generate markdown report")
    parser.add_argument("--city", default="北京", help="城市名")
    parser.add_argument("--location", default="116.397428,39.90923", help="起点经纬度，lng,lat")
    parser.add_argument("--api-key", default="", help="可选，直接指定高德key，优先级高于环境变量")
    args = parser.parse_args()

    cfg = load_citywalk_config("config/config.json")
    if args.api_key:
        cfg.setdefault("amap", {})["api_key"] = args.api_key
    client = AMapClient(cfg)
    runner = CitywalkSessionRunner(cfg, client)

    result = runner.run(city=args.city, start_location=args.location)

    generator = CitywalkReportGenerator(title_prefix=cfg["report"].get("title_prefix", "逛街小洛"))
    output_path = generator.save(result, cfg["report"].get("output_dir", "data/citywalk_reports"))

    print(f"Session完成, 事件数: {len(result.events)}")
    print(f"报告输出: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
