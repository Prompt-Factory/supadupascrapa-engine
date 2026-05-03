import json
from pathlib import Path
from typing import Final, Literal, NotRequired, TypedDict, cast


V3RegionTier = Literal[1, 2, 3, 4]
V3ChartScope = Literal["overall", "category"]


class V3RegionLabels(TypedDict):
    en: str
    ko: str


class V3CategoryAllocationConfig(TypedDict):
    id: str
    label: str
    weight: float
    reason: NotRequired[str]


class V3CategoryAllocationPlan(TypedDict):
    id: str
    label: str
    weight: float
    target_videos: int
    reason: NotRequired[str]


class V3RegionConfig(TypedDict):
    code: str
    labels: V3RegionLabels
    tier: V3RegionTier
    daily_target_videos: int
    overall_ratio: float
    category_ratio: float
    preferred_video_category_ids: list[str]
    category_allocations: NotRequired[list[V3CategoryAllocationConfig]]


class V3RegionPlan(TypedDict):
    code: str
    labels: V3RegionLabels
    tier: V3RegionTier
    daily_target_videos: int
    overall_ratio: float
    category_ratio: float
    overall_target_videos: int
    category_target_videos: int
    preferred_video_category_ids: list[str]
    category_allocations: list[V3CategoryAllocationPlan]
    estimated_pages: int
    estimated_units: int


YOUTUBE_V3_PAGE_SIZE: Final[int] = 50
YOUTUBE_V3_VIDEOS_LIST_COST_UNITS: Final[int] = 1
YOUTUBE_V3_CHANNELS_LIST_COST_UNITS: Final[int] = 1
YOUTUBE_V3_UNITS_PER_PAGE: Final[int] = (
    YOUTUBE_V3_VIDEOS_LIST_COST_UNITS
    + YOUTUBE_V3_CHANNELS_LIST_COST_UNITS
)
YOUTUBE_V3_DAILY_QUOTA_UNITS: Final[int] = 50_000
V3_REGION_CONFIG_DIR: Final[Path] = (
    Path(__file__).resolve().parent / "region_configs"
)


def load_region_config(path: Path) -> V3RegionConfig:
    raw_config = json.loads(path.read_text(encoding="utf-8"))
    required_fields = {
        "code",
        "labels",
        "tier",
        "daily_target_videos",
        "overall_ratio",
        "category_ratio",
        "preferred_video_category_ids",
    }
    missing_fields = sorted(required_fields - set(raw_config.keys()))
    if missing_fields:
        raise ValueError(
            f"{path.name} is missing required fields: {missing_fields}"
        )

    overall_ratio = float(raw_config["overall_ratio"])
    category_ratio = float(raw_config["category_ratio"])
    total_ratio = overall_ratio + category_ratio
    if abs(total_ratio - 1.0) > 1e-9:
        raise ValueError(
            f"{path.name} has invalid ratio sum: "
            f"{overall_ratio} + {category_ratio} != 1.0"
        )

    config: V3RegionConfig = {
        "code": str(raw_config["code"]).upper(),
        "labels": {
            "en": str(raw_config["labels"]["en"]),
            "ko": str(raw_config["labels"]["ko"]),
        },
        "tier": cast(V3RegionTier, int(raw_config["tier"])),
        "daily_target_videos": int(raw_config["daily_target_videos"]),
        "overall_ratio": overall_ratio,
        "category_ratio": category_ratio,
        "preferred_video_category_ids": [
            str(category_id)
            for category_id in raw_config["preferred_video_category_ids"]
        ],
    }

    raw_category_allocations = raw_config.get("category_allocations")
    if raw_category_allocations is not None:
        category_allocations: list[V3CategoryAllocationConfig] = []
        for item in raw_category_allocations:
            allocation: V3CategoryAllocationConfig = {
                "id": str(item["id"]),
                "label": str(item["label"]),
                "weight": float(item["weight"]),
            }
            if "reason" in item:
                allocation["reason"] = str(item["reason"])
            category_allocations.append(allocation)

        allocation_ids = [item["id"] for item in category_allocations]
        preferred_ids = config["preferred_video_category_ids"]
        if allocation_ids != preferred_ids:
            raise ValueError(
                f"{path.name} category_allocations ids must match "
                "preferred_video_category_ids in the same order"
            )

        weight_sum = sum(item["weight"] for item in category_allocations)
        if abs(weight_sum - 1.0) > 1e-9:
            raise ValueError(
                f"{path.name} category_allocations weight sum must be 1.0, "
                f"got {weight_sum}"
            )

        config["category_allocations"] = category_allocations

    return config


def load_region_configs() -> list[V3RegionConfig]:
    config_paths = sorted(
        path
        for path in V3_REGION_CONFIG_DIR.glob("*.json")
        if path.name != "example.json"
    )
    configs = [load_region_config(path) for path in config_paths]
    return sorted(configs, key=lambda item: (item["tier"], item["code"]))


def build_v3_region_plan(config: V3RegionConfig) -> V3RegionPlan:
    overall_target_videos = int(
        config["daily_target_videos"] * config["overall_ratio"]
    )
    category_target_videos = (
        config["daily_target_videos"] - overall_target_videos
    )
    estimated_pages = -(
        -config["daily_target_videos"] // YOUTUBE_V3_PAGE_SIZE
    )
    estimated_units = estimated_pages * YOUTUBE_V3_UNITS_PER_PAGE

    raw_allocations = config.get("category_allocations")
    if raw_allocations:
        category_allocations: list[V3CategoryAllocationPlan] = []
        allocated_so_far = 0
        for index, item in enumerate(raw_allocations):
            if index == len(raw_allocations) - 1:
                target_videos = category_target_videos - allocated_so_far
            else:
                target_videos = int(
                    category_target_videos * item["weight"]
                )
                allocated_so_far += target_videos

            allocation: V3CategoryAllocationPlan = {
                "id": item["id"],
                "label": item["label"],
                "weight": item["weight"],
                "target_videos": target_videos,
            }
            if "reason" in item:
                allocation["reason"] = item["reason"]
            category_allocations.append(allocation)
    else:
        weight = 1 / len(config["preferred_video_category_ids"])
        category_allocations = []
        allocated_so_far = 0
        preferred_ids = config["preferred_video_category_ids"]
        for index, category_id in enumerate(preferred_ids):
            if index == len(preferred_ids) - 1:
                target_videos = category_target_videos - allocated_so_far
            else:
                target_videos = int(category_target_videos * weight)
                allocated_so_far += target_videos
            category_allocations.append(
                {
                    "id": category_id,
                    "label": category_id,
                    "weight": weight,
                    "target_videos": target_videos,
                }
            )

    return {
        "code": config["code"],
        "labels": config["labels"],
        "tier": config["tier"],
        "daily_target_videos": config["daily_target_videos"],
        "overall_ratio": config["overall_ratio"],
        "category_ratio": config["category_ratio"],
        "overall_target_videos": overall_target_videos,
        "category_target_videos": category_target_videos,
        "preferred_video_category_ids": config[
            "preferred_video_category_ids"
        ],
        "category_allocations": category_allocations,
        "estimated_pages": estimated_pages,
        "estimated_units": estimated_units,
    }


V3_REGION_CONFIGS: Final[list[V3RegionConfig]] = load_region_configs()
V3_REGION_PLANS: Final[list[V3RegionPlan]] = [
    build_v3_region_plan(config)
    for config in V3_REGION_CONFIGS
]

V3_TOTAL_TARGET_VIDEOS: Final[int] = sum(
    plan["daily_target_videos"] for plan in V3_REGION_PLANS
)
V3_TOTAL_ESTIMATED_PAGES: Final[int] = sum(
    plan["estimated_pages"] for plan in V3_REGION_PLANS
)
V3_TOTAL_ESTIMATED_UNITS: Final[int] = sum(
    plan["estimated_units"] for plan in V3_REGION_PLANS
)
V3_ESTIMATED_DAILY_QUOTA_HEADROOM: Final[int] = (
    YOUTUBE_V3_DAILY_QUOTA_UNITS - V3_TOTAL_ESTIMATED_UNITS
)
