import json
from pathlib import Path
from typing import Final, TypedDict


BROAD_SEARCH_SEED_CONFIG_PATH: Final[Path] = (
    Path(__file__).resolve().parent / "broad_search_seeds.json"
)
DEFAULT_SEARCH_TOP_UP_PAGES_BY_TIER: Final[dict[int, int]] = {
    1: 120,
    2: 60,
    3: 20,
    4: 10,
}


class BroadSearchSeedLabel(TypedDict):
    en: str
    ko: str


class BroadSearchSeedQueryLocale(TypedDict):
    primary: str
    alternates: list[str]


class BroadSearchSeedQueries(TypedDict):
    ko: BroadSearchSeedQueryLocale
    en: BroadSearchSeedQueryLocale
    ja: BroadSearchSeedQueryLocale
    fr: BroadSearchSeedQueryLocale
    id: BroadSearchSeedQueryLocale


class BroadSearchSeedConfig(TypedDict):
    code: str
    priority_weight: float
    group: str
    label: BroadSearchSeedLabel
    reason: str
    queries: BroadSearchSeedQueries


class BroadSearchSeedPlan(TypedDict):
    code: str
    priority_weight: float
    group: str
    label: BroadSearchSeedLabel
    reason: str
    language: str
    primary_query: str
    alternate_queries: list[str]
    target_pages: int


class BroadSearchRegionPlan(TypedDict):
    region_code: str
    tier: int
    language: str
    total_target_pages: int
    seeds: list[BroadSearchSeedPlan]


class BroadSearchRootConfig(TypedDict):
    region_language_map: dict[str, str]
    seed_groups: list[BroadSearchSeedConfig]


def load_broad_search_root_config() -> BroadSearchRootConfig:
    raw = json.loads(
        BROAD_SEARCH_SEED_CONFIG_PATH.read_text(encoding="utf-8")
    )
    region_language_map = {
        str(region_code).upper(): str(language_code)
        for region_code, language_code in raw["region_language_map"].items()
    }
    seed_groups: list[BroadSearchSeedConfig] = []
    for item in raw["seed_groups"]:
        seed_groups.append(
            {
                "code": str(item["code"]),
                "priority_weight": float(item["priority_weight"]),
                "group": str(item["group"]),
                "label": {
                    "en": str(item["label"]["en"]),
                    "ko": str(item["label"]["ko"]),
                },
                "reason": str(item["reason"]),
                "queries": item["queries"],
            }
        )

    weight_sum = sum(item["priority_weight"] for item in seed_groups)
    if abs(weight_sum - 1.0) > 1e-9:
        raise ValueError(
            "broad_search_seeds.json priority_weight sum must be 1.0, "
            f"got {weight_sum}"
        )

    return {
        "region_language_map": region_language_map,
        "seed_groups": seed_groups,
    }


def build_broad_search_region_plan(
    *,
    region_code: str,
    tier: int,
    root_config: BroadSearchRootConfig,
) -> BroadSearchRegionPlan:
    normalized_region_code = region_code.upper()
    language = root_config["region_language_map"].get(normalized_region_code)
    if not language:
        raise ValueError(
            f"No broad search language configured for region "
            f"{normalized_region_code}"
        )

    total_target_pages = DEFAULT_SEARCH_TOP_UP_PAGES_BY_TIER[tier]
    seeds: list[BroadSearchSeedPlan] = []
    allocated_pages_so_far = 0
    for index, item in enumerate(root_config["seed_groups"]):
        locale_queries = item["queries"][language]
        if index == len(root_config["seed_groups"]) - 1:
            target_pages = total_target_pages - allocated_pages_so_far
        else:
            target_pages = int(total_target_pages * item["priority_weight"])
            allocated_pages_so_far += target_pages
        seeds.append(
            {
                "code": item["code"],
                "priority_weight": item["priority_weight"],
                "group": item["group"],
                "label": item["label"],
                "reason": item["reason"],
                "language": language,
                "primary_query": locale_queries["primary"],
                "alternate_queries": locale_queries["alternates"],
                "target_pages": target_pages,
            }
        )

    return {
        "region_code": normalized_region_code,
        "tier": tier,
        "language": language,
        "total_target_pages": total_target_pages,
        "seeds": seeds,
    }


BROAD_SEARCH_ROOT_CONFIG: Final[BroadSearchRootConfig] = (
    load_broad_search_root_config()
)
def build_broad_search_region_plans() -> dict[str, BroadSearchRegionPlan]:
    from v3_region_config import V3_REGION_PLANS

    region_tiers = {
        plan["code"]: plan["tier"]
        for plan in V3_REGION_PLANS
    }
    plans: dict[str, BroadSearchRegionPlan] = {}
    for region_code in BROAD_SEARCH_ROOT_CONFIG["region_language_map"]:
        tier = region_tiers.get(region_code)
        if tier is None:
            continue
        plans[region_code] = build_broad_search_region_plan(
            region_code=region_code,
            tier=tier,
            root_config=BROAD_SEARCH_ROOT_CONFIG,
        )
    return plans


BROAD_SEARCH_REGION_PLANS: Final[dict[str, BroadSearchRegionPlan]] = (
    build_broad_search_region_plans()
)
