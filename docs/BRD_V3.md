# SupaDupaScrapa BRD V3

> 이 문서는 V3 단계 기록용 문서입니다. 현재 최신 방향은 [BRD_V3_1.md](/Users/allon.km/PromptFactory/supadupascrapa-engine/docs/BRD_V3_1.md:1) 입니다.

## 문서 목적

이 문서는 SupaDupaScrapa의 세 번째 수집 전략을 정의합니다.

V3의 핵심 변화는 단순합니다.

- 검색어를 먼저 정하고 영상을 찾는 방식에서
- region에서 지금 실제로 뜨는 영상을 먼저 넓게 수집한 뒤
- 후처리에서 우리 taxonomy를 붙이는 방식으로 전환합니다

즉 V3의 제1 목표는 `taxonomy precision`이 아니라 `stable high-volume discovery`입니다.

## Pain Journey

### V1

V1은 방향 자체는 좋았습니다.

- YouTube raw 데이터를 모은다
- trend score를 계산한다
- industry/category 문맥에서 trend를 찾는다

하지만 실제 API 특성을 과소평가했습니다.

- `search.list`를 time-series snapshot처럼 다뤘다
- `views`, `likes`, `comments`가 자동으로 들어올 것처럼 설계했다
- channel baseline이 없는 상태에서 `ViewVelocity`를 정의했다

### V2

V2는 raw stream 분리까지는 올바르게 진전했습니다.

- `search_hits`
- `video_snapshots`
- `channel_snapshots`

하지만 discovery를 여전히 `industry x category` 검색어에 과하게 의존했습니다.

실제 운영에서 드러난 문제:
- 내부 taxonomy가 업로더 언어와 잘 맞지 않았다
- 결과가 많이 비었다
- query를 길게 합칠수록 결과가 줄었다
- `앱홍보 서비스홍보`, `앱튜토리얼 웹튜토리얼`처럼 alias를 한 줄에 합치면 discovery가 오히려 나빠졌다

### V3

V3는 discovery surface 자체를 YouTube native signal로 바꿉니다.

- `search.list` 중심에서 벗어난다
- `videos.list(chart=mostPopular)`를 region 중심으로 사용한다
- label은 post-processing에서 붙인다

정리하면:
- V1은 snapshot 가정이 틀렸다
- V2는 query-language fit이 나빴다
- V3는 discovery를 region chart로 바꿔 그 문제를 우회한다

## V1 / V2가 그대로 성립하지 않았던 이유

### 1. `search.list`는 trend snapshot의 안정적인 기반이 아니다

검색 결과는 고정된 모집단이 아닙니다.

- 오늘 잡힌 영상이 내일 빠질 수 있다
- relevance나 date ranking이 계속 바뀐다
- 그래서 동일 `video_id`의 연속 관측을 search 결과만으로 보장할 수 없다

### 2. internal taxonomy와 YouTube 업로더 언어는 다르다

우리는 `CLIENT_INDUSTRY`와 `PROJECT_CATEGORY`로 사고하지만, 업로더는 그렇게 제목을 쓰지 않습니다.

예:
- `앱/서비스 홍보`
- `제품/모델 촬영`
- `웹/앱 듀토리얼`

이런 내부 label을 query에 억지로 밀어 넣으면, 좋은 taxonomy일수록 오히려 discovery는 빈약해질 수 있습니다.

### 3. boolean-like query synthesis가 생각보다 제어되지 않는다

YouTube `q` 파라미터는 일반적인 검색엔진 수준의 괄호 그룹핑을 보장하지 않습니다.

그래서:
- `(패션 OR 레저) AND (앱홍보 OR 서비스홍보)`

같은 의도를 query 문자열 하나로 안정적으로 표현하기 어렵습니다.

### 4. 이 시스템의 본질은 `분류기`와 `발견기`를 분리하는 것이다

V1/V2는 두 역할이 아직 섞여 있었습니다.

- 발견기: 최대한 많은 의미 있는 영상을 안정적으로 가져오는 것
- 분류기: 그 영상을 industry/category/topic에 매핑하는 것

V3에서는 이 둘을 명확히 분리합니다.

## V3 제품 정의

### 한 문장 정의

SupaDupaScrapa V3는 `region-based YouTube trend intake engine`입니다.

처음부터 label을 맞히는 시스템이 아니라:
- region별 인기 영상을 넓게 수집하고
- 후처리에서 business taxonomy를 입히고
- 결국 rising/falling topic을 찾는 시스템입니다

### 최종 산출물

각 `region x industry x category` 문맥에 대해:

- rising topics
- falling topics
- supporting videos
- supporting channels

### 비목표

V3 초반에는 아래를 목표로 하지 않습니다.

- query tuning 최적화
- 모든 region에 동일한 taxonomy 기반 검색
- transcript 기반 완전한 semantic understanding
- 완성된 trend score 모델 확정

## V3 핵심 가설

다음 가설을 채택합니다.

1. `search.list`보다 `mostPopular` chart가 discovery volume을 훨씬 안정적으로 준다
2. trend system의 초반 성공은 label precision보다 ingest volume에 더 민감하다
3. region chart에서 충분히 넓게 모은 뒤 분류하는 쪽이 query-first보다 운영 안정성이 높다

## V3 API 모델

### 1. `i18nRegions.list`

역할:
- 지원 region 확인
- region config의 기준 목록 생성

### 2. `videoCategories.list`

역할:
- region별 유효 `videoCategoryId` 조회
- category chart 확장 시 사용할 shortlist 관리

주의:
- `videoCategoryId` 목록은 region별로 다를 수 있으므로 캐시 전제로 사용합니다
- `assignable=true`가 항상 `mostPopular` category chart 지원을 보장하지는 않습니다
- 일부 region/category 조합은 `videos.list(chart=mostPopular, videoCategoryId=...)`에서 `404 notFound`를 반환할 수 있습니다
- 따라서 런타임은 scope error를 기록하고 나머지 region/category 수집을 계속할 수 있어야 합니다

### 3. `videos.list(chart=mostPopular)`

역할:
- V3의 primary discovery feed
- 동시에 video snapshot source

예시 파라미터:
- `part=snippet,statistics,contentDetails,status`
- `chart=mostPopular`
- `regionCode=KR`
- `videoCategoryId` optional
- `maxResults=50`
- `pageToken`

이 API 하나로 얻는 것:
- discovery 대상 video list
- title, description, tags
- view/like/comment statistics
- categoryId
- publishedAt

### 4. `channels.list`

역할:
- channel baseline snapshot 보강
- 후속 velocity normalization용 채널 성과 시계열 생성

## V3 Discovery 전략

### 기본 원칙

- query-first가 아니라 region-first
- `overall chart`와 `category chart`를 같이 사용
- 중복 제거는 `video_id` 기준
- quota가 아니라 supply를 먼저 보는 구조

### Region 운영안

| Tier | Region | 일일 목표 영상 수 |
| --- | --- | ---: |
| 1 | `KR` 한국 | 100,000 |
| 1 | `US` 미국 | 100,000 |
| 2 | `JP` 일본 | 50,000 |
| 2 | `FR` 프랑스 | 50,000 |
| 3 | `GB` 영국 | 20,000 |
| 3 | `SG` 싱가포르 | 20,000 |
| 4 | `ID` 인도네시아 | 10,000 |

총합:

- 일일 목표 영상 수: `350,000`

### Region 내부 배분

각 region 목표치는 아래처럼 나눕니다.

- `50%`: region overall chart
- `50%`: region-specific category chart

예:
- `KR 100,000/day`
  - overall: `50,000`
  - category charts: `50,000`

이 비율은 초기값이며, 실제 depth와 중복률을 보고 조정 가능합니다.

### Why overall + category split

`overall`만 쓰면:
- 메인스트림 편향이 강해질 수 있다
- niche format이 묻힐 수 있다

`category`만 쓰면:
- 너무 잘게 쪼개져 운영 복잡도가 커진다
- region-wide big signal이 약해진다

그래서 V3는 두 레이어를 동시에 사용합니다.

## Quota 계산

### 비용 가정

- `videos.list` 1페이지: `1 unit`
- `channels.list` 1페이지 대응 배치 호출: `1 unit`
- 페이지당 영상 수: `50`

즉:

```txt
units_per_page = 2
videos_per_page = 50
```

### 전체 일일 운영안 계산

```txt
daily_target_videos = 350,000
pages_per_day = 350,000 / 50 = 7,000
daily_units = 7,000 * 2 = 14,000
```

정리:

- quota limit: `50,000 units/day`
- V3 plan usage: `14,000 units/day`
- remaining headroom: `36,000 units/day`

이 구조에서는 quota가 병목이 아닙니다. 병목은 주로:
- chart depth
- region/category별 중복률
- downstream processing capacity

## 저장 용량 감각

현재 JSONL 저장 포맷을 기준으로 대략:

- `video_snapshot + channel_snapshot`만 보면 video 1개당 약 `1.7KB`
- `350,000 videos/day`면 대략 `600MB/day` 내외
- discovery hit까지 포함하면 `1GB/day` 안쪽에서 운영될 가능성이 높습니다

이 숫자는 현재 저장 포맷에서 추정한 값이며, V3에서 discovery row를 더 slim하게 만들면 더 줄일 수 있습니다.

## V3 Raw 저장 스키마

### 1. `youtube_chart_hits`

목적:
- 어느 region/chart/category 문맥에서 video가 발견되었는지 최소 로그 보관

권장 키:
- `PK = youtube#region#chart_scope`
- `SK = collected_at#video_category_id#rank#video_id`

필드:

| Field | Type | 설명 |
| --- | --- | --- |
| `collected_at` | string | UTC 수집 시각 |
| `region` | string | region code |
| `chart_scope` | string | `overall` 또는 `category` |
| `video_category_id` | string nullable | category chart일 때만 값 보유 |
| `page` | number | 차트 페이지. 디버깅용 보조 필드 |
| `rank` | number | 차트 내 절대 순위. 예: 2페이지 첫 결과는 `51`, 3페이지 첫 결과는 `101` |
| `video_id` | string | YouTube video ID |
| `channel_id` | string | YouTube channel ID |
| `chart_batch_key` | string | 동일 배치 추적용 ID |

V3에서 discovery row는 최소한으로 유지합니다. 상세 메타는 중복 저장하지 않고 `youtube_video_snapshots`에 둡니다.

rank 계산 규칙:

```txt
rank = ((page_number - 1) * page_size) + index_within_page
```

예:
- 1페이지 1번째 결과 = `1`
- 1페이지 50번째 결과 = `50`
- 2페이지 1번째 결과 = `51`
- 3페이지 1번째 결과 = `101`

### 2. `youtube_video_snapshots`

목적:
- video metadata + statistics 시점별 snapshot 저장

권장 키:
- `PK = video_id`
- `SK = collected_at`

필드:

| Field | Type | 설명 |
| --- | --- | --- |
| `video_id` | string | YouTube video ID |
| `channel_id` | string | channel ID |
| `region` | string | 수집 region |
| `collected_at` | string | UTC 수집 시각 |
| `chart_scope` | string | `overall` 또는 `category` |
| `video_category_id` | string | YouTube category ID |
| `title` | string | 제목 |
| `description` | string | 설명 |
| `tags` | list[string] | tags |
| `published_at` | string | 게시 시각 |
| `duration` | string | ISO 8601 duration |
| `definition` | string | SD/HD |
| `caption` | string | caption 여부 |
| `made_for_kids` | boolean | 아동용 여부 |
| `view_count` | number | 조회수 |
| `like_count` | number | 좋아요 수 |
| `comment_count` | number | 댓글 수 |

### 3. `youtube_channel_snapshots`

목적:
- channel baseline 저장

권장 키:
- `PK = channel_id`
- `SK = collected_at`

필드:

| Field | Type | 설명 |
| --- | --- | --- |
| `channel_id` | string | channel ID |
| `region` | string | 수집 region |
| `collected_at` | string | UTC 수집 시각 |
| `channel_title` | string | 채널명 |
| `channel_view_count` | number | 채널 총조회수 |
| `subscriber_count` | number | 구독자 수 |
| `hidden_subscriber_count` | boolean | 구독자 비공개 여부 |
| `video_count` | number | 총 영상 수 |

모든 timestamp는 UTC 기준 ISO 8601로 저장하고, 내부 생성 timestamp는 `Z` suffix를 사용합니다.

## 후처리 모델

V3에서 taxonomy는 ingestion 뒤에 붙습니다.

### Step 1. Labeling

video snapshot을 기반으로:
- `CLIENT_INDUSTRY`
- `PROJECT_CATEGORY`

를 후처리 classifier나 rule/LLM 파이프라인으로 부여합니다.

### Step 2. Topic Extraction

출처:
- title
- description
- tags

를 기반으로 keyword/topic candidate를 만듭니다.

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
- V2 `search-first` 실행 코드는 정리했다
- 현재 `youtube_scraper`에는 V3 `mostPopular` handler, output writer, region batch runner가 구현되어 있다
- region config는 국가별 JSON 파일로 분리되어 있다
- 다음 단계는 runner 고도화와 dedup / 후처리 파이프라인 연결이다

다음 구현 순서 추천:

1. region/category별 chart depth와 `404` 지원 여부를 측정해 config를 정교화
2. dedup 전략 설계 및 적용
3. raw 적재 후 taxonomy labeling 파이프라인 연결
4. topic aggregation 및 rising/falling detection 연결

## 참고

- V2 문서는 유지합니다: [BRD_V2.md](/Users/allon.km/PromptFactory/supadupascrapa-engine/docs/BRD_V2.md:1)
- V3는 V2를 부정하는 문서가 아니라, 실제 운영 실험 결과를 반영해 discovery layer를 다시 설계한 문서입니다
