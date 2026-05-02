from itertools import product
from typing import Final, Literal, TypedDict


QueryMode = Literal["industry_and_category", "category_only"]


class IndustryConfig(TypedDict):
    code: str
    label: str
    query_mode: QueryMode
    search_term: str


class ProjectCategoryConfig(TypedDict):
    code: str
    label: str
    search_term: str


class ScrapeTarget(TypedDict):
    client_industry_code: str
    client_industry_label: str
    project_category_code: str
    project_category_label: str
    query_mode: QueryMode
    search_terms: list[str]
    query: str


CLIENT_INDUSTRY: Final[list[IndustryConfig]] = [
    {
        "code": "IT_COMMUNICATIONS",
        "label": "IT/정보통신",
        "query_mode": "industry_and_category",
        "search_term": "IT 정보통신",
    },
    {
        "code": "EDUCATION",
        "label": "교육",
        "query_mode": "industry_and_category",
        "search_term": "교육",
    },
    {
        "code": "DIGITAL_ELECTRONICS",
        "label": "디지털/가전",
        "query_mode": "industry_and_category",
        "search_term": "디지털가전",
    },
    {
        "code": "LIVING_SUPPLIES",
        "label": "리빙/생활용품",
        "query_mode": "industry_and_category",
        "search_term": "리빙생활용품",
    },
    {
        "code": "BEAUTY",
        "label": "뷰티",
        "query_mode": "industry_and_category",
        "search_term": "뷰티",
    },
    {
        "code": "COMMERCE_DISTRIBUTION",
        "label": "커머스/유통",
        "query_mode": "industry_and_category",
        "search_term": "커머스 유통",
    },
    {
        "code": "PUBLIC_ADMIN",
        "label": "공공/행정",
        "query_mode": "industry_and_category",
        "search_term": "공공행정",
    },
    {
        "code": "PHARMA_MEDICAL",
        "label": "제약/의료",
        "query_mode": "industry_and_category",
        "search_term": "제약 의료",
    },
    {
        "code": "SPACE_ARCHITECTURE",
        "label": "공간/건축",
        "query_mode": "industry_and_category",
        "search_term": "공간 건축",
    },
    {
        "code": "CULTURE_ART",
        "label": "문화/예술",
        "query_mode": "industry_and_category",
        "search_term": "문화 예술",
    },
    {
        "code": "FINANCE_INSURANCE",
        "label": "금융/보험",
        "query_mode": "industry_and_category",
        "search_term": "금융 보험",
    },
    {
        "code": "FOOD_BEVERAGE",
        "label": "식품/음료",
        "query_mode": "industry_and_category",
        "search_term": "식품 음료",
    },
    {
        "code": "FASHION_LEISURE",
        "label": "패션/레저",
        "query_mode": "industry_and_category",
        "search_term": "패션 레저",
    },
    {
        "code": "GAMING",
        "label": "게임",
        "query_mode": "industry_and_category",
        "search_term": "게임",
    },
    {
        "code": "ETC",
        "label": "기타",
        "query_mode": "category_only",
        "search_term": "",
    },
]

PROJECT_CATEGORY: Final[list[ProjectCategoryConfig]] = [
    {
        "code": "APP_SERVICE_AD",
        "label": "앱/서비스 홍보",
        "search_term": "앱홍보 서비스홍보",
    },
    {
        "code": "PRODUCT_AD",
        "label": "제품 광고",
        "search_term": "제품광고영상",
    },
    {
        "code": "WEB_APP_TUTORIAL",
        "label": "웹/앱 듀토리얼",
        "search_term": "앱튜토리얼 웹튜토리얼",
    },
    {
        "code": "INTERVIEW",
        "label": "인터뷰",
        "search_term": "인터뷰",
    },
    {
        "code": "BRAND_FILM",
        "label": "브랜드필름",
        "search_term": "브랜드필름",
    },
    {
        "code": "GRAPHIC_VIDEO",
        "label": "그래픽 영상",
        "search_term": "그래픽영상 모션그래픽",
    },
    {
        "code": "CHARACTER_INFOGRAPHIC",
        "label": "캐릭터/인포그래픽",
        "search_term": "캐릭터 인포그래픽",
    },
    {
        "code": "GRAPHIC_3D",
        "label": "3D 그래픽",
        "search_term": "3D그래픽",
    },
    {
        "code": "MEDIA_ART",
        "label": "미디어아트",
        "search_term": "미디어아트",
    },
    {
        "code": "YOUTUBE_PRODUCTION",
        "label": "유튜브 제작",
        "search_term": "유튜브영상제작",
    },
    {
        "code": "PRODUCT_MODEL_SHOOT",
        "label": "제품/모델 촬영",
        "search_term": "제품촬영 모델촬영",
    },
    {
        "code": "ON_SITE_SKETCH",
        "label": "현장 스케치",
        "search_term": "현장스케치",
    },
    {
        "code": "LECTURE_VOD",
        "label": "강의/VOD",
        "search_term": "강의VOD",
    },
]


def build_search_terms(
    client_industry: IndustryConfig,
    project_category: ProjectCategoryConfig,
) -> list[str]:
    return [
        search_term
        for search_term in [
            client_industry["search_term"],
            project_category["search_term"],
        ]
        if search_term
    ]


def build_search_query(
    client_industry: IndustryConfig,
    project_category: ProjectCategoryConfig,
) -> str:
    return " ".join(
        build_search_terms(client_industry, project_category)
    )


def build_scrape_targets() -> list[ScrapeTarget]:
    return [
        {
            "client_industry_code": client_industry["code"],
            "client_industry_label": client_industry["label"],
            "project_category_code": project_category["code"],
            "project_category_label": project_category["label"],
            "query_mode": client_industry["query_mode"],
            "search_terms": build_search_terms(
                client_industry,
                project_category,
            ),
            "query": build_search_query(client_industry, project_category),
        }
        for client_industry, project_category in product(
            CLIENT_INDUSTRY,
            PROJECT_CATEGORY,
        )
    ]


SCRAPE_TARGETS: Final[list[ScrapeTarget]] = build_scrape_targets()

YOUTUBE_DAILY_QUOTA_UNITS: Final[int] = 50_000
YOUTUBE_SEARCH_COST_UNITS: Final[int] = 100
YOUTUBE_VIDEO_DETAILS_COST_UNITS: Final[int] = 1
YOUTUBE_CHANNEL_DETAILS_COST_UNITS: Final[int] = 1
YOUTUBE_DISCOVERY_ORDER: Final[str] = "date"
YOUTUBE_DISCOVERY_LOOKBACK_DAYS: Final[int] = 7
YOUTUBE_SEARCH_PAGE_SIZE: Final[int] = 50
YOUTUBE_SEARCH_PAGES_PER_QUERY: Final[int] = 2
YOUTUBE_LOCAL_OUTPUT_DIR: Final[str] = "outputs/youtube_scraper"
YOUTUBE_TARGET_RESULTS_PER_QUERY: Final[int] = (
    YOUTUBE_SEARCH_PAGE_SIZE * YOUTUBE_SEARCH_PAGES_PER_QUERY
)
YOUTUBE_RAW_CAPTURE_UNITS_PER_PAGE: Final[int] = (
    YOUTUBE_SEARCH_COST_UNITS
    + YOUTUBE_VIDEO_DETAILS_COST_UNITS
    + YOUTUBE_CHANNEL_DETAILS_COST_UNITS
)
YOUTUBE_ESTIMATED_RAW_CAPTURE_UNITS_PER_QUERY: Final[int] = (
    YOUTUBE_SEARCH_PAGES_PER_QUERY * YOUTUBE_RAW_CAPTURE_UNITS_PER_PAGE
)
YOUTUBE_ESTIMATED_DAILY_RAW_CAPTURE_UNITS: Final[int] = (
    len(SCRAPE_TARGETS) * YOUTUBE_ESTIMATED_RAW_CAPTURE_UNITS_PER_QUERY
)
YOUTUBE_ESTIMATED_DAILY_QUOTA_HEADROOM: Final[int] = (
    YOUTUBE_DAILY_QUOTA_UNITS - YOUTUBE_ESTIMATED_DAILY_RAW_CAPTURE_UNITS
)
