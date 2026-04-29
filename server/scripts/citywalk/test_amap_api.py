import argparse
import os
import sys

cwd = os.getcwd()
sys.path.insert(0, str(cwd))

from src.plugins.citywalk.amap_client import AMapClient
from src.plugins.citywalk.config import load_citywalk_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Test AMap API for citywalk")
    parser.add_argument("--city", default="北京", help="城市名")
    parser.add_argument("--location", default="116.397428,39.90923", help="经纬度，lng,lat")
    parser.add_argument("--keyword", default="咖啡", help="搜索关键词")
    parser.add_argument("--api-key", default="", help="可选，直接指定高德key，优先级高于环境变量")
    args = parser.parse_args()

    cfg = load_citywalk_config("config/config.json")
    if args.api_key:
        cfg.setdefault("amap", {})["api_key"] = args.api_key
    client = AMapClient(cfg)

    print("[1/3] 搜索周边POI...")
    pois = client.search_nearby_pois(
        location=args.location,
        city=args.city,
        keywords=args.keyword,
        types=cfg["search"].get("types", ""),
        radius_m=int(cfg["search"].get("radius_m", 3000)),
        offset=5,
    )
    print(f"返回数量: {len(pois)}")
    if not pois:
        print("未检索到POI")
        return 1

    target = pois[0]
    print(f"样例POI: {target.name} | {target.location} | {target.distance_m}m")

    print("[2/3] 获取POI详情...")
    detail = client.get_poi_detail(target.poi_id)
    print(f"详情: {detail.poi.name} | rating={detail.rating} | tel={detail.tel}")

    print("[3/3] 路线规划...")
    route = client.plan_walking_route(args.location, target.location)
    print(f"可达: {route.reachable}, 距离: {route.distance_m}m, 时长: {route.duration_s}s")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
