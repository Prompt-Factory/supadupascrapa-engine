# SupaDupaScrapa BRD V2

## 문서 목적

이 문서는 기존 V1 BRD의 의도는 유지하되, 실제 YouTube Data API 제약과 일별 snapshot 운영 방식을 반영해 SupaDupaScrapa를 다시 정의한 문서입니다.

V2의 핵심 목표는 다음과 같습니다.

- `industry x category x region` 문맥별로 상승/하락하는 `trend keyword/topic`을 찾는다
- 개별 유튜브 영상은 최종 산출물이 아니라 트렌드의 `evidence`로 취급한다
- `search.list` 기반 discovery와 `videos.list`/`channels.list` 기반 snapshot tracking을 분리한다

## V1 문서가 하려던 것

기존 V1 문서들은 크게 두 가지 방향을 담고 있었습니다.

1. `SupaDupaScrapa API & Infra Overview`
- YouTube 데이터를 스크래핑해 DynamoDB에 저장하는 서버리스 구조
- `/scrape`, `/status`, `/health` 같은 control plane
- raw video metadata 저장용 테이블

2. `AI Trend Model Overview`
- `TrendScore = w1 * ViewVelocity + w2 * EngagementRate + w3 * RecencyBoost`
- OpenSearch KNN 기반 유사도 분석
- Trend alignment score

이 방향 자체는 유효합니다. 문제는 V1에서 정의한 raw 수집 구조가 실제로는 그 점수식을 안정적으로 뒷받침하지 못한다는 점입니다.

## V1의 오류

### 1. `search.list` 결과를 snapshot으로 취급했다

V1은 사실상 검색 결과를 raw 데이터의 중심으로 보고 있었습니다. 하지만 `search.list`는 특정 검색어에 대한 `relevance` 기반 discovery 결과입니다.

즉:
- 오늘의 상위 50개와 내일의 상위 50개가 같다는 보장이 없다
- 어떤 영상은 오늘 잡히고 내일 빠질 수 있다
- 그러면 `video_id`별 시계열 snapshot이 끊긴다

이 문제 때문에 `ViewVelocity` 계산에 필요한 안정적인 `viewCount_today - viewCount_2daysAgo`를 얻기 어렵습니다.

### 2. V1 raw 스키마가 `search.list`만으로 채워질 수 있다고 가정했다

V1의 raw 테이블에는 아래 필드가 포함되어 있었습니다.

- `views`
- `likes`
- `comments`

하지만 이 값들은 `search.list` 응답에 기본 포함되지 않습니다. 이 필드들은 `videos.list(part=statistics)`를 별도로 호출해야만 얻을 수 있습니다.

즉 V1 raw 스키마는 방향은 맞았지만, 어떤 API가 어떤 필드를 제공하는지에 대한 매핑이 빠져 있었습니다.

### 3. `ViewVelocity` 계산에 필요한 channel baseline이 없었다

V1 수식:

```txt
ViewVelocity = (viewCount_today - viewCount_2daysAgo) / channel_avg_daily_views
```

이 식을 계산하려면 최소 2종류의 시계열이 필요합니다.

- 같은 `video_id`의 일별 조회수 snapshot
- 같은 `channel_id`의 일별 baseline snapshot

V1에는 `channel_id`는 있었지만 `channel_avg_daily_views`를 만들기 위한 별도의 channel snapshot 설계가 없었습니다.

### 4. 최종 산출물이 `video ranking`인지 `topic trend`인지 모호했다

우리가 진짜 원하는 것은 각 `industry x category` 조합마다 상승하는 트렌드와 하락하는 트렌드입니다.

즉 관심의 대상은:
- 개별 영상 자체가 아니라
- 반복적으로 등장하고, 조회수/반응/신선도가 같이 움직이는 `keyword/topic cluster`

V1은 raw video collection과 trend detection을 충분히 분리하지 못했습니다.

### 5. single-table raw 모델로는 discovery와 tracking을 동시에 처리하기 어렵다

V1의 `trend_raw_data`는 의미적으로는 맞았지만, 한 테이블 안에 다음 두 역할을 동시에 담으려 했습니다.

- 검색에서 발견된 hit
- 영상의 일별 snapshot

이 둘은 쓰임새가 다릅니다.

- search hit는 `문맥에서 무엇이 발견되었는가`를 설명
- video snapshot은 `그 영상의 성과가 시간에 따라 어떻게 변하는가`를 설명

따라서 V2에서는 raw를 3개 stream으로 분리합니다.

## V2 제품 정의

### 한 문장 정의

SupaDupaScrapa V2는 `Google Trends for YouTube creative content`에 가깝습니다.

다만 데이터 소스는 Google Search가 아니라 YouTube이고, 결과는 일반 대중 검색 트렌드가 아니라 `industry x category` 문맥의 콘텐츠 트렌드입니다.

### 최종 산출물

각 `industry x category x region`에 대해:

- `rising keywords/topics`
- `falling keywords/topics`
- 각 trend를 설명하는 supporting videos

### 비목표

V2 초반에는 아래를 목표로 삼지 않습니다.

- 개별 영상의 절대 랭킹 최적화
- transcript 기반 full semantic understanding
- embedding 기반 fine-grained similarity search

이것들은 후속 단계입니다.

## V2 핵심 개념

### 1. Context

트렌드를 해석하는 문맥입니다.

- `region`
- `industry`
- `category`
- `source_query`

예:
- `KR + 뷰티 + 제품 광고 + "뷰티 제품 광고"`

`source_query`는 내부 taxonomy 라벨을 그대로 쓰지 않고, 실제 YouTube 검색에 보낼 자연어 검색어를 사용합니다. 예를 들어 `앱/서비스 홍보`는 `앱홍보`, `브랜드필름`은 `브랜드필름`, `미디어아트`는 `미디어아트`로 검색합니다.

운영 데이터에서는 `industry`와 `category`를 한글 라벨 대신 서버 enum의 `code` 값으로 저장하는 것을 권장합니다. 표시용 한글은 별도 metadata 또는 join 대상으로 다룹니다.

모든 timestamp는 UTC 기준 ISO 8601로 저장합니다. 시스템 실행 timezone과 무관하게 raw 저장 시점에는 UTC만 사용합니다.

### 2. Evidence Video

YouTube에서 수집된 개별 영상입니다.

- trend의 최종 결과가 아니라
- trend를 설명하는 근거 데이터입니다

### 3. Trend Entity

초기 V2에서는 `trend = keyword/topic`으로 정의합니다.

출처는 다음과 같습니다.

- `title`
- `description`
- `tags`

향후 transcript, embedding, cluster merge로 확장할 수 있습니다.

## V2 수집 아키텍처

### Step 1. Discovery

`search.list`로 각 `industry x category x region` 문맥에서 후보 영상을 찾습니다.

역할:
- 어떤 query에서 어떤 영상이 발견되었는지 기록
- discovery 전용

주의:
- 이 데이터만으로는 점수 계산을 하지 않음

기본 discovery 전략:
- `order = date`
- `publishedAfter = now - 7 days`
- `maxResults = 50`
- `2 pages/query = 최대 100개`

이 전략은 "가장 대표적인 기존 영상"보다 "최근에 새로 올라온 관련 영상"을 우선 수집하기 위한 것입니다.

### Step 2. Video Snapshot Enrichment

`videos.list(part=snippet,statistics,contentDetails,status)`로 발견된 `video_id`들을 일괄 조회합니다.

역할:
- `views`
- `likes`
- `comments`
- `tags`
- `duration`
- 기타 분석용 메타데이터

이 layer가 있어야 `EngagementRate`를 계산할 수 있습니다.

### Step 3. Channel Snapshot Enrichment

`channels.list(part=statistics,snippet)`로 관련 `channel_id`를 일괄 조회합니다.

역할:
- channel baseline snapshot 저장
- 향후 `channel_avg_daily_views` 추정

이 layer가 있어야 `ViewVelocity`를 채널 규모 대비로 정규화할 수 있습니다.

### Step 4. Trend Aggregation

영상별 raw snapshot을 바로 최종 trend로 보지 않고, 문맥별 keyword/topic aggregate로 변환합니다.

예:
- keyword mention count
- total supporting views
- unique channel count
- average engagement
- recency mix

### Step 5. Rising/Falling Detection

집계된 keyword/topic 시계열을 비교해 상승/하락을 판정합니다.

예시 지표:
- day-over-day share change
- 7-day mention growth
- view-weighted momentum

## V2 Raw 저장 스키마

아래 스키마는 DynamoDB를 기준으로 설명하지만, 로컬 JSON 저장에도 같은 논리를 적용합니다.

### 1. `youtube_search_hits`

목적:
- 특정 query 맥락에서 어떤 영상이 발견되었는지 보존

권장 키:
- `PK = context_key`
- `SK = collected_at#page#rank#video_id`

`context_key` 예시:

```txt
youtube#KR#뷰티#제품 광고
```

필드:

| Field | Type | 설명 |
| --- | --- | --- |
| `context_key` | string | `platform#region#industry#category` |
| `collected_at` | string | 수집 시각 |
| `platform` | string | `youtube` |
| `region` | string | 국가 코드 |
| `industry` | string | 산업 enum code |
| `category` | string | 카테고리 enum code |
| `source_query` | string | 실제 검색 쿼리 |
| `search_order` | string | 예: `relevance`, `date`, `viewCount` |
| `page` | number | 검색 페이지 |
| `rank` | number | 페이지 내 순위 |
| `video_id` | string | YouTube video ID |
| `channel_id` | string | YouTube channel ID |
| `channel_title` | string | 채널명 |
| `title` | string | 제목 |
| `description` | string | 설명 |
| `published_at` | string | 영상 게시 시각 |
| `thumbnails` | map/json | thumbnail metadata |

비고:
- `search_hits`는 discovery 로그입니다
- raw score 계산의 기준 테이블로 쓰지 않습니다

### 2. `youtube_video_snapshots`

목적:
- 동일 `video_id`에 대한 일별 시계열 snapshot 저장

권장 키:
- `PK = video_id`
- `SK = collected_at`

필드:

| Field | Type | 설명 |
| --- | --- | --- |
| `video_id` | string | YouTube video ID |
| `collected_at` | string | snapshot 시각 |
| `channel_id` | string | 채널 ID |
| `region` | string | 수집 문맥의 region |
| `industry` | string | 수집 문맥의 industry enum code |
| `category` | string | 수집 문맥의 category enum code |
| `source_query` | string | 어떤 query로 발견되었는지 |
| `title` | string | 제목 |
| `description` | string | 설명 |
| `tags` | list[string] | video tags |
| `published_at` | string | 게시 시각 |
| `category_id` | string | YouTube category ID |
| `default_language` | string | 기본 언어 |
| `duration` | string | ISO 8601 duration |
| `caption` | string/bool | 자막 여부 |
| `definition` | string | `hd`/`sd` |
| `made_for_kids` | bool | 아동용 여부 |
| `view_count` | number | 조회수 |
| `like_count` | number | 좋아요 수 |
| `comment_count` | number | 댓글 수 |

이 테이블로 가능한 것:
- `EngagementRate`
- `RecencyBoost`
- `video_id` 기준 조회수 delta

### 3. `youtube_channel_snapshots`

목적:
- 동일 `channel_id`에 대한 일별 baseline snapshot 저장

권장 키:
- `PK = channel_id`
- `SK = collected_at`

필드:

| Field | Type | 설명 |
| --- | --- | --- |
| `channel_id` | string | YouTube channel ID |
| `collected_at` | string | snapshot 시각 |
| `region` | string | 수집 문맥의 region |
| `industry` | string | 수집 문맥의 industry enum code |
| `category` | string | 수집 문맥의 category enum code |
| `source_query` | string | 어떤 query에서 유입되었는지 |
| `channel_title` | string | 채널명 |
| `channel_view_count` | number | 채널 총조회수 |
| `subscriber_count` | number | 구독자 수 |
| `hidden_subscriber_count` | bool | 구독자 수 비공개 여부 |
| `video_count` | number | 공개 영상 수 |

이 테이블로 가능한 것:
- `channel_avg_daily_views` 추정
- channel 규모 대비 영상 성장률 정규화

## TrendScore 계산 관점에서 필요한 raw 데이터

V2 수식:

```txt
TrendScore = w1 * ViewVelocity + w2 * EngagementRate + w3 * RecencyBoost
```

각 항목과 필요한 raw source:

| Metric | 계산식 | 필요한 raw source |
| --- | --- | --- |
| `ViewVelocity` | `(viewCount_today - viewCount_2daysAgo) / channel_avg_daily_views` | `youtube_video_snapshots`, `youtube_channel_snapshots` |
| `EngagementRate` | `(likeCount + commentCount) / viewCount_today` | `youtube_video_snapshots` |
| `RecencyBoost` | 업로드 후 경과 시간 기반 decay | `youtube_video_snapshots` |

즉:
- `search_hits`만으로는 불충분
- 최소 `video_snapshots + channel_snapshots`가 필요

## Quota 계산

현재 quota:

- `50,000 units/day`

API 비용:

- `search.list = 100 units`
- `videos.list = 1 unit`
- `channels.list = 1 unit`

운영 가정:

- 전체 조합 `15 x 13 = 195`
- `search.list` 1페이지 = 최대 `50 results`
- discovery window = 최근 `7일`
- `50 results`를 받으면 `videos.list` 1회, `channels.list` 1회로 후속 snapshot 저장

따라서 1페이지당 raw 수집 비용은:

```txt
raw_units_per_page = 100 + 1 + 1 = 102
```

조합별 결과 수와 일일 비용:

| 페이지 수/조합 | 결과 수/조합 | 비용/조합 | 총 비용/일 | 잔여 quota | 상태 |
| --- | ---: | ---: | ---: | ---: | --- |
| 1 | 50 | 102 | 19,890 | 30,110 | 가능 |
| 2 | 100 | 204 | 39,780 | 10,220 | 가능 |
| 3 | 150 | 306 | 59,670 | -9,670 | 불가 |

결론:

- `50,000 / (195 * 102) = 2.51...` 이므로 정수 페이지 운영 기준 최대치는 `2 pages/query`
- `195`개 전체 조합을 매일 모두 돌릴 경우, 현재 quota 기준 현실적인 상한은 `100 results/query`
- `150 results/query`부터는 불가능
- 따라서 V2 baseline 운영값은 `2 pages = 100 results/query`

## V2에서의 Trend 정의

초기 V2는 `trend = keyword/topic`으로 정의합니다.

예:
- `클린뷰티`
- `저자극`
- `3D 모션`
- `브랜드필름`

영상은 이러한 trend를 설명하는 supporting evidence입니다.

향후 확장:

1. `keyword trend`
- title + description + tags 기반

2. `topic cluster trend`
- 유사 표현 merge
- 예: `브랜드 필름`, `brand film`, `브랜디드 필름`

3. `semantic trend`
- embedding
- transcript
- visual motif

## 즉시 실행 항목

1. `search.list` 결과를 `youtube_search_hits` 형태로 저장
2. `video_id` batch를 `videos.list`로 재조회해 `youtube_video_snapshots` 저장
3. `channel_id` batch를 `channels.list`로 재조회해 `youtube_channel_snapshots` 저장
4. raw snapshot을 기반으로 keyword aggregate layer 설계
5. 그 다음에야 `TrendScore`와 rising/falling trend 계산으로 이동

## 최종 요약

V1은 좋은 방향을 잡았지만, discovery와 snapshot tracking을 혼동했고, `search.list`만으로 수식에 필요한 raw 데이터를 모두 확보할 수 있다고 가정한 것이 가장 큰 오류였습니다.

V2에서는 다음을 분명히 합니다.

- `trend`의 주인공은 video가 아니라 keyword/topic이다
- `search.list`는 discovery다
- `videos.list`는 video snapshot이다
- `channels.list`는 channel baseline snapshot이다
- `100 results/query`가 현재 quota에서의 일일 운영 상한이다
