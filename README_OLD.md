# 🧠 SupaDupaScrapa Engine

> A scalable trend scraping engine that powers content intelligence by crawling and analyzing data from SNS platforms like YouTube.

---

## 🚀 Overview

The SupaDupaScrapa Engine is designed to gather, store, and expose trend signals (by region, industry, and content type) via a serverless-first backend stack.

It currently supports:
- 🔍 Daily YouTube video scraping by keyword & region
- 📦 Structured result output (title, view count, videoId, etc.)
- 💬 FastAPI interface for querying trend scores (planned)
- 🧠 Future integration with LLM & embedding-based trend scoring

---

## 🔧 Component Summary

| Component          | Role                                                       | Tech                      |
|--------------------|------------------------------------------------------------|---------------------------|
| `Lambda`           | Executes platform-specific scrapers (e.g. YouTube)         | AWS Lambda                |
| `EventBridge`      | Triggers daily scraping jobs per platform/region/topic     | AWS EventBridge Scheduler |
| `FastAPI`          | Serves client-facing endpoints (trend queries, scoring)    | ECS (Fargate), FastAPI    |
| `DynamoDB`         | Stores raw and processed trend data for each query domain  | AWS DynamoDB              |
| `OpenSearch` (📍Future) | Powers similarity search and style clustering       | Amazon OpenSearch         |
| `Bedrock` (📍Future)    | Embedding generation, scoring recommendations        | Amazon Bedrock (Titan/Claude) |

---

## 📅 Current Milestone

| Phase     | Goal                             | Status     |
|-----------|----------------------------------|------------|
| Phase 1   | YouTube Scraper MVP              | ✅ Done     |
| Phase 2   | FastAPI Trend Query Endpoint     | 🛠 In Progress |
| Phase 3   | DynamoDB Storage + Scoring       | ⏳ Upcoming |
| Phase 4   | Embedding + Model Integration    | 🔮 Future   |

---

## 📂 Supported Metadata

### 🎯 Query Filters
- `regionCode` (e.g., `"KR"`)
- `query` (e.g., `"브랜드필름"`)

### 🏷️ Supported Industries (15)
```python
class Industry(Enum):

```

### 🎬 Supported Content Categories (13)
```python
class ProjectCategory(Enum):

```

---

## 🔑 Local Setup

1. Clone repo and install dependencies:
   ```bash
   pip install -r lambda-requirements.txt
   ```

2. Create a `.env` in the root:
   ```env
   YOUTUBE_API_KEY=your_api_key_here
   ```

3. Run the YouTube scraper manually:
   ```bash
   python lambdas/youtube_scraper/handler.py
   ```

---

## ☁️ Infra Stack

| Resource        | Purpose                         |
|-----------------|---------------------------------|
| `Lambda`        | YouTube scraping logic          |
| `EventBridge`   | Daily scraping scheduler        |
| `FastAPI`       | Client-serving backend          |
| `DynamoDB`      | Data warehouse for trends       |
| `OpenSearch`    | Similarity & vector search (🚧 later) |
| `Bedrock`       | Embeddings & LLM scoring (🚧 later) |

---

## 🧪 Scoring Idea (v0)

A basic scoring model could be:

```
trend_score = (views × 0.5) + (recency_weight × 0.3) + (engagement × 0.2)
```

Where:
- `views` = view count
- `recency_weight` = inverse of days since upload
- `engagement` = likes + comments + shares (if available)

You'll evolve this as you bring in ML later.

---

## 📌 TODOs

- [ ] Store scraped data in DynamoDB
- [ ] Implement trend scoring endpoint
- [ ] Add support for more SNS platforms (TikTok, IG, etc.)
- [ ] Add CI/CD pipeline (GitHub Actions → AWS)

---

## 🧠 Name Origin

Because this engine goes **supadupa hard** at scrappin' them trends.
