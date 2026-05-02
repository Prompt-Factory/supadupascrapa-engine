# SupaDupaScrapa BRD V3.1

## 문서 목적

이 문서는 SupaDupaScrapa의 현재 discovery 전략인 `V3.1`을 정의합니다.

V3.1의 핵심 변화는 다음 한 줄로 요약됩니다.

- `mostPopular`만으로는 discovery volume이 충분하지 않았다
- 따라서 `region-first chart intake`는 유지하되
- `broad search seed`를 보조 discovery source로 추가한다

즉 V3.1은 `YouTube native chart intake + language-localized broad search intake`의 혼합 전략입니다.

## Pain Journey

### V1

V1은 방향 자체는 좋았지만, raw 수집 구조가 실제 API 특성과 맞지 않았습니다.

- `search.list`를 안정적인 snapshot처럼 가정했다
- `views`, `likes`, `comments`가 자동으로 들어올 것처럼 설계했다
- channel baseline 없이 `ViewVelocity`를 정의했다

### V2

V2는 raw stream을 분리한 점은 맞았지만 discovery를 여전히 taxonomy query에 강하게 의존했습니다.

- `search_hits`
- `video_snapshots`
- `channel_snapshots`

하지만 실제 운영에서는:
- 내부 taxonomy와 업로더 언어가 잘 맞지 않았다
- query가 길어질수록 결과가 줄었다
- `industry x category`를 직접 query에 밀어 넣는 방식이 sparse result를 만들었다

### V3

V3는 discovery surface를 YouTube native chart로 옮겼습니다.

- `videos.list(chart=mostPopular)` 중심
- region-first intake
- taxonomy는 후처리 단계에서 분류

이 변화는 맞는 방향이었습니다. 하지만 실제 실험에서 한계도 드러났습니다.

- chart lane 목표치는 크게 잡았지만
- 실제 full run에서는 chart depth가 예상보다 얕았다
- region/category별 `nextPageToken` 공급량이 빨리 소진됐다
- 결과적으로 broad intake volume이 충분히 채워지지 않았다

### V3.1

V3.1은 V3를 버리는 게 아니라 보강합니다.

- `mostPopular`는 그대로 primary source로 유지
- broad discovery가 필요한 구간은 `search.list(order=date)` seed layer로 보강
- seed는 taxonomy 직접 검색용이 아니라 creative trend intake 보강용으로 설계

정리하면:
- V1은 snapshot 가정이 틀렸다
- V2는 query-language fit이 나빴다
- V3는 source 자체는 맞았지만 supply depth가 부족했다
- V3.1은 chart + search 혼합 intake로 supply 문제를 보강한다

## V3.1 제품 정의

### 한 문장 정의

SupaDupaScrapa V3.1은 `region-based YouTube trend intake engine with broad search expansion`입니다.

처음부터 label을 맞히는 시스템이 아니라:
- region별로 지금 뜨는 영상을 최대한 넓게 수집하고
- broad search seed로 niche / early trend를 보강하고
- 후처리에서 business taxonomy를 입히는 시스템입니다

### 최종 산출물

각 `region x industry x category` 문맥에 대해:

- rising topics
- falling topics
- supporting videos
- supporting channels

### 비목표

V3.1 초반에는 아래를 목표로 하지 않습니다.

- taxonomy query precision 최적화
- transcript 기반 full semantic understanding
- 완성된 trend score 모델 확정
- broad search seed의 완전한 local perfection

## V3.1 Discovery 전략

V3.1에서는 discovery를 2개 layer로 나눕니다.

### Layer A. Region Chart Intake

기본 수집원:
- `videos.list(chart=mostPopular)`
- `channels.list`

역할:
- region별 mainstream / high-signal 영상 대량 intake
- 저비용 discovery
- video statistics snapshot 동시 확보

특징:
- quota 효율이 매우 높다
- 하지만 chart depth가 region/category별로 얕을 수 있다

### Layer B. Broad Search Seed Intake

보강 수집원:
- `search.list(order=date)`
- 필요 시 이후 `videos.list` / `channels.list` enrichment

역할:
- `mostPopular`에 잘 안 잡히는 niche / early trend 보강
- creative format / production language 기반 discovery
- taxonomy 직접 검색이 아니라 제작 시장 언어 기반 intake

원칙:
- 모든 region은 같은 seed set을 쓴다
- region별로 바뀌는 것은 query language 뿐이다
- broad search는 `industry x category` 직접 검색용이 아니다

## Broad Search Seed 설계

공통 seed config:
- [broad_search_seeds.json](/Users/allon.km/PromptFactory/supadupascrapa-engine/lambdas/youtube_scraper/broad_search_seeds.json:1)
- [broad_search_seed_config.py](/Users/allon.km/PromptFactory/supadupascrapa-engine/lambdas/youtube_scraper/broad_search_seed_config.py:1)

현재 seed set:

- `COMMERCIAL`
- `BRAND_FILM`
- `PRODUCT_AD`
- `APP_SERVICE_PROMO`
- `TUTORIAL_EXPLAINER`
- `INTERVIEW`
- `MOTION_GRAPHICS`
- `INFOGRAPHIC`
- `THREE_D_GRAPHICS`
- `MEDIA_ART`
- `YOUTUBE_PRODUCTION`
- `MAKING_FILM`

이 seed들은 다음 기준으로 설계했습니다.

- 제작/광고 시장에서 실제로 쓰이는 표현일 것
- 너무 taxonomy-like 하지 않을 것
- region별로 언어 번역만 바꿔도 구조가 유지될 것
- 후처리에서 `CLIENT_INDUSTRY`, `PROJECT_CATEGORY`로 분류 가능한 raw material을 늘릴 것

## Region 운영안

현재 운영 대상 region:

| Tier | Region | Chart Reserve / Day |
| --- | --- | ---: |
| 1 | `KR` 한국 | 1,500 |
| 1 | `US` 미국 | 1,500 |
| 2 | `JP` 일본 | 1,500 |
| 2 | `FR` 프랑스 | 1,500 |
| 3 | `GB` 영국 | 1,500 |
| 3 | `SG` 싱가포르 | 1,500 |
| 4 | `ID` 인도네시아 | 1,500 |

총 chart reserve:

- 일일 chart reserve 영상 수: `10,500`

region config의 `daily_target_videos`는 이제 full daily target이 아니라 chart lane reserve 값을 뜻합니다.

## Region Chart 배분

현재 region chart 배분은 아래와 같습니다.

- `50%`: region overall chart
- `50%`: region-specific category chart

예:
- `KR 1,500/day`
  - overall: `750`
  - category charts: `750`

category shortlist와 배분은 region config JSON에 기록합니다.

- 예: [KR.json](/Users/allon.km/PromptFactory/supadupascrapa-engine/lambdas/youtube_scraper/region_configs/KR.json:1)
- 예: [US.json](/Users/allon.km/PromptFactory/supadupascrapa-engine/lambdas/youtube_scraper/region_configs/US.json:1)

## 현재 Daily Allocation

V3.1 현재 운영안은 아래처럼 고정합니다.

### 1. Chart Lane Reserve

- 모든 region에서 `mostPopular` chart를 하루 `1,500 videos`씩 reserve
- region당 `30 pages`
- region당 `60 units`

합계:
- `10,500 videos/day`
- `420 units/day`

### 2. Search Top-up Allocation

chart lane 이후 부족분은 broad search seed 기반 `search.list(order=date)`로 채웁니다.

현재 page budget:

| Tier | Region | Search Pages / Day | Search Videos / Day | Search Units / Day |
| --- | --- | ---: | ---: | ---: |
| 1 | `KR` | 120 | 6,000 | 12,240 |
| 1 | `US` | 120 | 6,000 | 12,240 |
| 2 | `JP` | 60 | 3,000 | 6,120 |
| 2 | `FR` | 60 | 3,000 | 6,120 |
| 3 | `GB` | 20 | 1,000 | 2,040 |
| 3 | `SG` | 20 | 1,000 | 2,040 |
| 4 | `ID` | 10 | 500 | 1,020 |

search top-up 합계:
- `20,500 videos/day`
- `41,820 units/day`

### 3. Current Combined Daily Plan

| Lane | Videos / Day | Units / Day |
| --- | ---: | ---: |
| `mostPopular` chart lane | 10,500 | 420 |
| broad search top-up lane | 20,500 | 41,820 |
| 합계 | 31,000 | 42,240 |

현재 운영안 기준:
- 일일 총수집량: `31,000 videos/day`
- 일일 총사용량: `42,240 units/day`
- 잔여 quota: `7,760 units/day`

## V3.1 API 모델

### 1. `videos.list(chart=mostPopular)`

역할:
- primary discovery feed
- video snapshot source

주요 필드:
- `snippet`
- `statistics`
- `contentDetails`
- `status`

### 2. `channels.list`

역할:
- channel baseline snapshot 보강

### 3. `search.list(order=date)`

역할:
- broad search discovery source

원칙:
- 최신 업로드 중심
- 긴 taxonomy query 대신 broad creative seed 사용
- broad discovery 후 `videos.list` / `channels.list`로 enrichment

## Raw 저장 모델

V3.1에서도 raw stream 기본 구조는 유지합니다.

### `youtube_chart_hits`

목적:
- chart discovery 로그

핵심 필드:
- `collected_at`
- `region`
- `chart_scope`
- `video_category_id`
- `page`
- `rank`
- `video_id`
- `channel_id`

### `youtube_video_snapshots`

목적:
- video metadata + statistics snapshot

핵심 필드:
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

목적:
- channel baseline snapshot

핵심 필드:
- `channel_id`
- `region`
- `collected_at`
- `channel_title`
- `channel_view_count`
- `subscriber_count`
- `hidden_subscriber_count`
- `video_count`

현재 구현 메모:
- 같은 run 안에서 이미 본 `video_id`는 `video_snapshot`을 다시 저장하지 않습니다
- 같은 run 안에서 이미 본 `channel_id`는 `channel_snapshot`을 다시 저장하지 않습니다
- 현재 dedup은 `chart + search`를 함께 도는 run 내부 snapshot dedup까지 구현되어 있습니다
- 터미널 progress 로그와 run summary에는 `dupVideos`, `dupChannels`가 함께 출력됩니다

### Discovery stream 분리

V3.1에서는 broad search가 이미 붙어 있으므로 discovery stream은 2개입니다.

- `youtube_chart_hits`
- `youtube_search_hits`

이 두 stream은 source 해석을 위해 분리 저장하는 것이 좋습니다.

권장 저장 구조 예시:

```text
outputs/youtube_scraper/
  region=KR/
    chart_hits/date=YYYY-MM-DD/
    search_hits/date=YYYY-MM-DD/
    video_snapshots/date=YYYY-MM-DD/
    channel_snapshots/date=YYYY-MM-DD/
    runs/date=YYYY-MM-DD/
```

운영 전환 시에는 위 partition 구조를 Lambda에서 그대로 S3 prefix 아래에 미러링합니다.

예:

```text
s3://promptfactory-data-trend/youtube_scraper/
  region=KR/
    chart_hits/date=YYYY-MM-DD/
    search_hits/date=YYYY-MM-DD/
    video_snapshots/date=YYYY-MM-DD/
    channel_snapshots/date=YYYY-MM-DD/
    runs/date=YYYY-MM-DD/
```

또한 daily scheduler run은 `runAllRegions=true` 이벤트를 통해 한 번에 전체 region을 실행하고, batch-level summary를 `batches/date=YYYY-MM-DD/*.json`로 별도 저장합니다.

## 후처리 모델

taxonomy는 ingestion 뒤에 붙습니다.

### Step 1. Labeling

video snapshot 기반으로:
- `CLIENT_INDUSTRY`
- `PROJECT_CATEGORY`

를 classifier / rule / LLM 파이프라인으로 부여합니다.

### Step 2. Topic Extraction

출처:
- title
- description
- tags

### Step 3. Aggregation

집계 축:
- `region`
- `industry`
- `category`
- `topic`
- `date`

### Step 4. Rising/Falling Detection

예시 지표:
- mention growth
- share-of-voice change
- view-weighted momentum
- recency-weighted support

## 구현 상태와 다음 단계

현재 상태:
- V3 `mostPopular` region runner는 구현되어 있다
- region config는 국가별 JSON 파일로 분리되어 있다
- broad search seed 공통 config와 로더를 추가했다
- `search.list(order=date)` broad search runner도 구현되어 있다
- current runner에는 chart + search를 가로지르는 run 내부 `video/channel snapshot dedup`이 들어가 있다

운영 메모:
- chart lane은 region별 fixed reserve로 운용한다
- broad search는 quota 잔량이 아니라 daily page budget 기준으로 운용한다
- 현재 search top-up budget은 tier별 `120 / 60 / 20 / 10 pages`이다

다음 구현 순서 추천:

1. search seed별 alternate query fallback 전략 추가
2. persisted daily dedup / resume 전략 추가
3. raw 적재 후 taxonomy labeling 파이프라인 연결
4. topic aggregation 및 rising/falling detection 연결
5. search lane 운영 비율을 region별 실측 데이터 기준으로 재조정

## 참고

- V2 문서는 유지합니다: [BRD_V2.md](/Users/allon.km/PromptFactory/supadupascrapa-engine/docs/BRD_V2.md:1)
- V3 문서는 유지합니다: [BRD_V3.md](/Users/allon.km/PromptFactory/supadupascrapa-engine/docs/BRD_V3.md:1)
- V3.1은 V3를 폐기하는 문서가 아니라, 실험 결과를 반영해 discovery layer를 확장한 문서입니다
