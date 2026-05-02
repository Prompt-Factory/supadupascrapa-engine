import json
from pathlib import Path
from typing import Final, TypedDict


BROAD_SEARCH_SEED_CONFIG_PATH: Final[Path] = (
    Path(__file__).resolve().parent / "broad_search_seeds.json"
)


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


class BroadSearchRegionPlan(TypedDict):
    region_code: str
    language: str
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
    root_config: BroadSearchRootConfig,
) -> BroadSearchRegionPlan:
    normalized_region_code = region_code.upper()
    language = root_config["region_language_map"].get(normalized_region_code)
    if not language:
        raise ValueError(
            f"No broad search language configured for region "
            f"{normalized_region_code}"
        )

    seeds: list[BroadSearchSeedPlan] = []
    for item in root_config["seed_groups"]:
        locale_queries = item["queries"][language]
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
            }
        )

    return {
        "region_code": normalized_region_code,
        "language": language,
        "seeds": seeds,
    }


BROAD_SEARCH_ROOT_CONFIG: Final[BroadSearchRootConfig] = (
    load_broad_search_root_config()
)
BROAD_SEARCH_REGION_PLANS: Final[dict[str, BroadSearchRegionPlan]] = {
    region_code: build_broad_search_region_plan(
        region_code=region_code,
        root_config=BROAD_SEARCH_ROOT_CONFIG,
    )
    for region_code in BROAD_SEARCH_ROOT_CONFIG["region_language_map"]
}
