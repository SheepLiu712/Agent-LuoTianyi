import time
import random
from typing import Any, Dict, List, Optional

import requests

from ...utils.logger import get_logger
from .errors import AMapRequestError, AMapResponseError
from .types import POI, POIDetail, RouteResult


class AMapClient:
    def __init__(self, config: Dict[str, Any]):
        amap_cfg = config.get("amap", {})
        self.api_key = amap_cfg.get("api_key", "")
        self.base_url = amap_cfg.get("base_url", "https://restapi.amap.com/v3").rstrip("/")
        self.timeout_seconds = int(amap_cfg.get("timeout_seconds", 10))
        self.max_retries = int(amap_cfg.get("max_retries", 1))
        self.logger = get_logger(__name__)
        self.session = requests.Session()

        if not self.api_key or str(self.api_key).startswith("$"):
            raise AMapRequestError("AMap key is missing. Set environment variable AMAP_KEY.")

    def _request(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        query = {**params, "key": self.api_key}
        url = f"{self.base_url}/{path.lstrip('/')}"

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.get(url, params=query, timeout=self.timeout_seconds)
                resp.raise_for_status()
                payload = resp.json()
                if payload.get("status") != "1":
                    raise AMapResponseError(
                        f"AMap business error: info={payload.get('info')} infocode={payload.get('infocode')}"
                    )
                return payload
            except (requests.RequestException, ValueError, AMapResponseError) as exc:
                last_error = exc
                self.logger.warning("AMap request failed at attempt %s: %s", attempt + 1, exc)
                if attempt < self.max_retries:
                    time.sleep(0.3 * (attempt + 1))

        raise AMapRequestError(f"AMap request failed: {last_error}")

    def search_nearby_pois(
        self,
        location: str,
        city: str = "",
        keywords: str = "",
        types: str = "",
        radius_m: int = 3000,
        page: int = 1,
        offset: int = 10,
    ) -> List[POI]:
        payload = self._request(
            "/place/around",
            {
                "location": location,
                "city": city,
                "keywords": keywords,
                "types": types,
                "radius": radius_m,
                "page": page,
                "offset": offset,
                "extensions": "base",
            },
        )

        pois: List[POI] = []
        for row in payload.get("pois", []):
            if not row.get("id") or not row.get("location"):
                continue
            distance_raw = row.get("distance", "0")
            try:
                distance_m = int(float(distance_raw))
            except (TypeError, ValueError):
                distance_m = 0

            pois.append(
                POI(
                    poi_id=row.get("id", ""),
                    name=row.get("name", ""),
                    location=row.get("location", ""),
                    address=row.get("address", ""),
                    distance_m=distance_m,
                    type_name=row.get("type", ""),
                )
            )
        return pois

    def geocode_place(self, address: str, city: str = "") -> Dict[str, str]:
        payload = self._request(
            "/geocode/geo",
            {
                "address": address,
                "city": city,
            },
        )
        geocodes = payload.get("geocodes", [])
        if not geocodes:
            raise AMapResponseError(f"No geocode found for address={address}, city={city}")

        row = geocodes[0]
        location = str(row.get("location", "")).strip()
        if not location or "," not in location:
            raise AMapResponseError(f"Invalid geocode location for address={address}, city={city}")

        return {
            "location": location, # 经纬度
            "formatted_address": str(row.get("formatted_address", "")).strip(),
            "province": str(row.get("province", "")).strip(),
            "city": str(row.get("city", "")).strip(),
            "district": str(row.get("district", "")).strip(),
        }

    def get_poi_detail(self, poi_id: str) -> POIDetail:
        payload = self._request(
            "/place/detail",
            {
                "id": poi_id,
                "extensions": "all",
            },
        )
        pois = payload.get("pois", [])
        if not pois:
            raise AMapResponseError(f"No POI detail found for {poi_id}")

        row = pois[0]
        poi = POI(
            poi_id=row.get("id", ""),
            name=row.get("name", ""),
            location=row.get("location", ""),
            address=row.get("address", ""),
            distance_m=0,
            type_name=row.get("type", ""),
        )

        rating = None
        try:
            if row.get("biz_ext", {}).get("rating"):
                rating = float(row["biz_ext"]["rating"])
        except (ValueError, TypeError):
            rating = None

        tag_value = row.get("tag", "") or ""
        tags = [x.strip() for x in str(tag_value).replace("|", ";").split(";") if x.strip()]
        photos_raw = row.get("photos", []) or []
        photo_urls: List[str] = []
        for p in photos_raw:
            if isinstance(p, dict) and p.get("url"):
                photo_urls.append(str(p.get("url")))

        return POIDetail(
            poi=poi,
            tel=row.get("tel", ""),
            rating=rating,
            business_hours=row.get("business_hours", ""),
            intro=tag_value,
            tags=tags,
            photos=photo_urls,
        )

    def resolve_random_start_by_district_code(self, district_code: str, jitter: float = 0.015) -> str:
        payload = self._request(
            "/config/district",
            {
                "keywords": district_code,
                "subdistrict": 0,
                "extensions": "base",
            },
        )
        districts = payload.get("districts", [])
        if not districts:
            raise AMapResponseError(f"No district found for code {district_code}")

        center = str(districts[0].get("center", "")).strip()
        if not center or "," not in center:
            raise AMapResponseError(f"District center missing for code {district_code}")

        lng_s, lat_s = center.split(",", 1)
        lng = float(lng_s)
        lat = float(lat_s)
        lng += random.uniform(-jitter, jitter)
        lat += random.uniform(-jitter, jitter)
        return f"{lng:.6f},{lat:.6f}"

    def plan_walking_route(self, origin: str, destination: str) -> RouteResult:
        payload = self._request(
            "/direction/walking",
            {
                "origin": origin,
                "destination": destination,
            },
        )
        route = payload.get("route", {})
        paths = route.get("paths", [])
        if not paths:
            return RouteResult(reachable=False, distance_m=0, duration_s=0, steps=[])

        best = paths[0]
        steps = [step.get("instruction", "") for step in best.get("steps", []) if step.get("instruction")]
        distance_m = int(float(best.get("distance", 0) or 0))
        duration_s = int(float(best.get("duration", 0) or 0))
        return RouteResult(
            reachable=True,
            distance_m=distance_m,
            duration_s=duration_s,
            steps=steps,
        )
