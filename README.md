# SupaDupaScrapa Engine

Lambda-only repository for running and deploying AWS Lambda functions.

## Structure

```text
lambdas/
  hello_world/
    handler.py
    sample_event.json
  youtube_scraper/
    handler.py
    sample_event.json
    utils.py
    youtube_client.py
.github/workflows/deploy-lambda.yml
lambda-requirements.txt
```

## Local Run

```bash
python3 lambdas/hello_world/handler.py
python3 lambdas/youtube_scraper/handler.py
```

For YouTube scraper local execution, set:

```env
YOUTUBE_API_KEY=your_api_key_here
```

## Deployment

GitHub Actions workflow: `.github/workflows/deploy-lambda.yml`

Trigger:
- Push to `release` branch
- Manual run (`workflow_dispatch`)

Behavior:
- If Lambda exists: update code
- If Lambda does not exist: create function

## Required GitHub Secrets

- `AWS_DEPLOY_ROLE_ARN`
- `AWS_REGION`
- `LAMBDA_FUNCTION_NAME`
- `LAMBDA_EXECUTION_ROLE_ARN`

## Optional GitHub Variables

- `LAMBDA_SOURCE_DIR` (default: `lambdas/hello_world`)
- `LAMBDA_HANDLER` (default: `handler.handler`)
- `LAMBDA_RUNTIME` (default: `python3.12`)
- `LAMBDA_TIMEOUT` (default: `30`)
- `LAMBDA_MEMORY_SIZE` (default: `256`)
