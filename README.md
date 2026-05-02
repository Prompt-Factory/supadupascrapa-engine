# SupaDupaScrapa Engine

AWS Lambda 기반의 YouTube 수집 실험 레포지토리입니다.

현재 제품 방향은 `query-first` 수집보다 `region-first` 수집에 가깝습니다. V3에서는 YouTube의 `mostPopular` 차트를 region 기준으로 최대한 넓게 수집하고, 우리 내부 taxonomy인 `CLIENT_INDUSTRY`와 `PROJECT_CATEGORY`는 후처리 단계에서 분류하는 방향으로 전환합니다.

현재 문서 기준:
- 현재 방향: [BRD_V3.md](/Users/allon.km/PromptFactory/supadupascrapa-engine/docs/BRD_V3.md:1)
- 이전 방향 보관본: [BRD_V2.md](/Users/allon.km/PromptFactory/supadupascrapa-engine/docs/BRD_V2.md:1)

중요:
- V2의 `search-first` 실행 코드는 정리했습니다.
- 현재 `youtube_scraper`는 V3 region tier config를 노출하는 가벼운 scaffold 상태입니다.
- 실제 `mostPopular` 수집 runner는 다음 구현 단계입니다.

## 구조

```text
docs/
  BRD_V2.md
  BRD_V3.md
lambdas/
  hello_world/
    handler.py
    sample_event.json
  youtube_scraper/
    handler.py
    region_configs/
      FR.json
      GB.json
      ID.json
      JP.json
      KR.json
      SG.json
      US.json
    run_full_scrape.py
    sample_event.json
    utils.py
    v3_region_config.py
    youtube_client.py
.github/workflows/deploy-lambda.yml
lambda-requirements.txt
```

## Pain Journey

### V1

- `search.list` 결과를 안정적인 일별 snapshot처럼 다루려 했다
- `views`, `likes`, `comments`가 `search.list`만으로 채워질 수 있다고 가정했다
- trend entity보다 개별 video 수집에 더 끌려가며 목표가 모호했다

### V2

- `search_hits`, `video_snapshots`, `channel_snapshots`로 raw stream을 분리한 점은 맞는 방향이었다
- 하지만 discovery를 여전히 `industry x category` 검색어에 강하게 의존했다
- 실제 업로더 언어와 내부 taxonomy가 어긋나서 빈 결과가 많았고, query를 길게 합칠수록 결과가 급격히 줄었다

### V3

- discovery 목표를 `label을 맞히는 것`이 아니라 `하루에 최대한 많은 유효 영상을 안정적으로 확보하는 것`으로 바꾼다
- YouTube native surface인 `videos.list(chart=mostPopular)`를 region 중심으로 사용한다
- 내부 taxonomy는 검색 시점이 아니라 후처리 단계에서 붙인다

## V3 운영 요약

V3의 기본 아이디어는 아래와 같습니다.

- 1차 수집: `videos.list(chart=mostPopular, regionCode=...)`
- 2차 보강: `channels.list`로 채널 snapshot 저장
- 3차 후처리: `industry/category/topic` 분류, trend aggregation, rising/falling detection

또한 region별 수집량 목표를 두고:
- `50%`는 region overall 차트
- `50%`는 region별 `videoCategoryId` 차트

로 배분합니다.

V3 region tier 설정은 국가별 JSON 파일로 분리되어 있습니다.

- 설정 파일 위치: [region_configs](/Users/allon.km/PromptFactory/supadupascrapa-engine/lambdas/youtube_scraper/region_configs)
- 로더: [v3_region_config.py](/Users/allon.km/PromptFactory/supadupascrapa-engine/lambdas/youtube_scraper/v3_region_config.py:1)
- 설명용 템플릿: [example.json](/Users/allon.km/PromptFactory/supadupascrapa-engine/lambdas/youtube_scraper/region_configs/example.json:1)

예:
- [KR.json](/Users/allon.km/PromptFactory/supadupascrapa-engine/lambdas/youtube_scraper/region_configs/KR.json:1)
- [US.json](/Users/allon.km/PromptFactory/supadupascrapa-engine/lambdas/youtube_scraper/region_configs/US.json:1)

각 국가 파일에는 아래 같은 사람용 참고 필드를 함께 둘 수 있습니다.

- `_preferred_video_category_notes`: 왜 이 shortlist를 골랐는지 기록
- `_reference_video_categories`: API 기준 assignable `true/false` 목록 참고자료

주의:
- `assignable=true`가 항상 `videos.list(chart=mostPopular, videoCategoryId=...)` 성공을 보장하지는 않습니다.
- 실제 region/category 조합에 따라 `404 notFound`가 날 수 있으므로, 런타임에서는 scope error를 기록하고 나머지 수집을 계속 진행합니다.

## Region Tier 운영안

현재 운영 대상 region:

| Tier | Region | 일일 목표 영상 수 |
| --- | --- | ---: |
| 1 | `KR` 한국 | 100,000 |
| 1 | `US` 미국 | 100,000 |
| 2 | `JP` 일본 | 50,000 |
| 2 | `FR` 프랑스 | 50,000 |
| 3 | `GB` 영국 | 20,000 |
| 3 | `SG` 싱가포르 | 20,000 |
| 4 | `ID` 인도네시아 | 10,000 |

총 목표:

- 일일 목표 영상 수: `350,000`
- discovery 비율: region overall `50%` + category chart `50%`

## V3 Quota 계산

V3의 핵심은 `videos.list`가 discovery와 video snapshot을 동시에 해결한다는 점입니다.

- `videos.list(chart=mostPopular, maxResults=50)`: `1 unit`
- 같은 페이지에서 나온 채널들을 `channels.list`로 조회: `1 unit`
- 즉 `50 videos + channel snapshot` 묶음이 대략 `2 units`

계산식:

```txt
videos_per_page = 50
units_per_page = videos.list + channels.list = 1 + 1 = 2

pages_per_day = 350,000 / 50 = 7,000
daily_units = 7,000 * 2 = 14,000
```

정리:

- 일일 quota: `50,000 units/day`
- 현재 V3 운영안 예상 사용량: `14,000 units/day`
- 잔여 headroom: `36,000 units/day`

즉 현재 tier 운영안은 quota 관점에서 매우 안전합니다.

## V3 Raw 저장 모델

V3에서는 3개 raw stream을 유지하되, discovery source를 검색 결과가 아니라 chart hit로 바꿉니다.

### `youtube_chart_hits`

- 목적: 어느 region/chart/category 문맥에서 어떤 영상이 발견되었는지 기록
- 성격: 최소 discovery 로그
- `rank`는 차트 내 절대 순위를 저장합니다
  - 예: 1페이지 첫 결과 `1`, 2페이지 첫 결과 `51`, 3페이지 첫 결과 `101`
- `page`는 디버깅용으로만 보조 저장합니다
- 예시 필드:
  - `collected_at`
  - `region`
  - `chart_scope` (`overall` 또는 `category`)
  - `video_category_id`
  - `page`
  - `rank`
  - `video_id`
  - `channel_id`

### `youtube_video_snapshots`

- 목적: video metadata + statistics snapshot 저장
- 주 필드:
  - `video_id`
  - `channel_id`
  - `region`
  - `collected_at`
  - `title`
  - `description`
  - `published_at`
  - `tags`
  - `duration`
  - `view_count`
  - `like_count`
  - `comment_count`
  - `video_category_id`

### `youtube_channel_snapshots`

- 목적: channel baseline snapshot 저장
- 주 필드:
  - `channel_id`
  - `region`
  - `collected_at`
  - `channel_title`
  - `channel_view_count`
  - `subscriber_count`
  - `hidden_subscriber_count`
  - `video_count`

모든 timestamp는 UTC 기준 ISO 8601 문자열로 저장합니다. 내부 생성 timestamp는 `Z` suffix를 사용합니다.

## 저장 구조

V3 raw 저장의 목표 구조는 아래와 같습니다.

```text
outputs/youtube_scraper/
  region=KR/
    chart_hits/
      date=YYYY-MM-DD/
        *.jsonl
    video_snapshots/
      date=YYYY-MM-DD/
        *.jsonl
    channel_snapshots/
      date=YYYY-MM-DD/
        *.jsonl
    runs/
      date=YYYY-MM-DD/
        *.json
```

- `chart_hits/`는 discovery 최소 로그입니다
- `video_snapshots/`, `channel_snapshots/`는 DB 적재용 primary raw 저장본입니다
- region별로 먼저 분리한 뒤, 각 stream 아래 UTC 기준 `date=YYYY-MM-DD` partition을 둡니다

## 현재 구현 상태

현재 `youtube_scraper`는 V3 `mostPopular` 수집기가 붙어 있습니다.

- `handler.py`: regionCode 기준으로 overall chart + category chart를 실제 호출
- `region_configs/*.json`: 국가별 tier, daily target, category shortlist 설정
- `v3_region_config.py`: JSON 로더와 quota 계산값 정의
- `youtube_client.py`: `videos.list` / `channels.list` 호출
- `utils.py`: UTC timestamp, region-first output writer, record builder
- `run_full_scrape.py`: configured region들을 순회하는 배치 러너

관련 파일:
- [handler.py](/Users/allon.km/PromptFactory/supadupascrapa-engine/lambdas/youtube_scraper/handler.py:1)
- [run_full_scrape.py](/Users/allon.km/PromptFactory/supadupascrapa-engine/lambdas/youtube_scraper/run_full_scrape.py:1)
- [utils.py](/Users/allon.km/PromptFactory/supadupascrapa-engine/lambdas/youtube_scraper/utils.py:1)
- [v3_region_config.py](/Users/allon.km/PromptFactory/supadupascrapa-engine/lambdas/youtube_scraper/v3_region_config.py:1)
- [youtube_client.py](/Users/allon.km/PromptFactory/supadupascrapa-engine/lambdas/youtube_scraper/youtube_client.py:1)

## 로컬 실행

```bash
python3 lambdas/hello_world/handler.py
python3 lambdas/youtube_scraper/handler.py
python3 lambdas/youtube_scraper/run_full_scrape.py
```

예시 `sample_event.json`:

```json
{
  "regionCode": "KR",
  "maxResults": 50,
  "maxPagesPerScope": 1,
  "includeOverallChart": true,
  "includeCategoryCharts": true,
  "includeChannelSnapshots": true,
  "saveToFile": true,
  "saveSplitFiles": true,
  "saveBundleFile": true,
  "outputDir": "outputs/youtube_scraper"
}
```

핵심 실행 옵션:

- `regionCode`: 수집할 region
- `maxResults`: 페이지당 결과 수, 기본 `50`
- `maxPagesPerScope`: 테스트용 page limit
- `includeOverallChart`: overall chart 수집 여부
- `includeCategoryCharts`: category chart 수집 여부
- `includeChannelSnapshots`: channel snapshot 저장 여부

실행 결과:

- `chart_hits`, `video_snapshots`, `channel_snapshots`는 JSONL로 저장됩니다
- `runs`에는 summary bundle JSON이 저장됩니다
- 일부 category chart가 `404 notFound`여도 `scopeErrors`에 기록하고 나머지 scope는 계속 진행합니다

## 배포

GitHub Actions 워크플로: `.github/workflows/deploy-lambda.yml`

트리거:
- `release` 브랜치로 push
- 수동 실행 (`workflow_dispatch`)

동작 방식:
- `handler.py`가 있는 `lambdas/*` 폴더를 자동 탐색합니다
- 탐색된 각 Lambda를 matrix job으로 배포합니다
- Lambda 이름은 `${LAMBDA_NAME_PREFIX}<folder_name>` 형식으로 동적으로 결정됩니다
- Lambda가 이미 있으면 코드를 업데이트합니다
- Lambda가 없으면 새로 생성합니다

## 필수 GitHub Secrets

- `AWS_DEPLOY_ROLE_ARN`
- `AWS_REGION`
- `LAMBDA_EXECUTION_ROLE_ARN`

## 선택 GitHub Variables

- `LAMBDA_NAME_PREFIX` 예시: `supadupascrapa-`
- `LAMBDA_HANDLER` 기본값: `handler.handler`
- `LAMBDA_RUNTIME` 기본값: `python3.12`
- `LAMBDA_TIMEOUT` 기본값: `30`
- `LAMBDA_MEMORY_SIZE` 기본값: `256`

## IAM Roles

IAM Role은 2개가 필요합니다.

1. GitHub deploy role (`AWS_DEPLOY_ROLE_ARN`)
- 신뢰 주체: GitHub OIDC (`token.actions.githubusercontent.com`)
- 레포/브랜치 범위: `Prompt-Factory/supadupascrapa-engine` 의 `release`
- 최소 권한:
  - `lambda:GetFunction`
  - `lambda:CreateFunction`
  - `lambda:UpdateFunctionCode`
  - Lambda 실행 role에 대한 `iam:PassRole`

2. Lambda execution role (`LAMBDA_EXECUTION_ROLE_ARN`)
- 신뢰 주체: `lambda.amazonaws.com`
- 최소 관리형 정책: `AWSLambdaBasicExecutionRole`

## EventBridge Scheduler

EventBridge Scheduler를 사용해 Lambda를 스케줄 실행할 수 있습니다.

- 대상: 배포된 Lambda 함수
- 스케줄 타입: `Cron-based schedule`
- 매일 오전 10시 표현식:

```txt
cron(0 10 * * ? *)
```

- 올바른 time zone을 설정하세요. 예: `America/Los_Angeles`, `Asia/Seoul`
- 정확한 실행 시각이 필요하면 `Flexible time window`를 `Off`로 설정하세요

주의:
- Scheduler 실행 role은 `scheduler.amazonaws.com`을 신뢰해야 합니다
- Scheduler role에는 대상 Lambda ARN에 대한 `lambda:InvokeFunction` 권한이 필요합니다
