# Rider Payout Dispute Desk

A FastAPI service for verifying rider payout disputes against trip and payout records, with PaySwift integration and operations approval for payouts requiring human review.

## Requirements

- Docker Desktop
- Docker Compose

## Run the application

From the project root, run:

```bash
docker compose up --build
```

The services will be available at:

- API: http://localhost:8000
- Swagger documentation: http://localhost:8000/docs
- PaySwift sandbox: http://localhost:8081

Check service health:

```bash
curl http://localhost:8000/health
```

## API endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Check service health |
| POST | `/messages` | Submit a rider payout dispute |
| GET | `/trace/{rider_id}` | Inspect the processing trace |
| GET | `/ops/pending` | View pending operations approvals |

### Example message

```json
{
  "message_id": "wamid-example-001",
  "rider_id": "R003",
  "text": "Please check my payout for trip T926334.",
  "received_at": "2026-09-22T09:05:00+05:30"
}
```

## Evaluation

With the services running, execute:

```bash
python evals/run.py http://localhost:8000
```

The script checks the health and pending operations endpoints.

## Configuration

Configure `PAYSWIFT_BASE_URL` using the environment. Inside Docker Compose, the PaySwift service URL is `http://payswift:8081`.

See `.env.example` for the environment configuration.

## Project structure

- `app/` — API, dispute verification, data loading, and PaySwift client
- `data/` — rider, trip, payout, and conversation datasets
- `docs/policy.md` — payout policy reference
- `evals/` — evaluation script
- `payswift/` — provided PaySwift sandbox configuration
- `ai-logs/` — AI session export documentation and logs

## AI usage

AI assistance was used during development. Raw session exports should be placed in `ai-logs/`, following the submission instructions.
