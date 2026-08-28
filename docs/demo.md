# ServiceFlow API Demo Guide

This walkthrough demonstrates the core engineering story in a few minutes. It uses only local,
development-only data.

## 1. Start and Seed

```bash
docker compose up -d --build
docker compose exec api python manage.py seed_dev
```

Open Swagger UI at <http://localhost:8000/api/docs/> and readiness at
<http://localhost:8000/health/ready/>.

Development accounts use password `ServiceFlow123!`:

- `requester@serviceflow.local`
- `agent@serviceflow.local`
- `admin@serviceflow.local`

## 2. Requester Creates a Ticket

1. Call `POST /api/v1/auth/login/` as the requester.
2. Authorize Swagger with the access token.
3. Read `GET /api/v1/categories/` and choose a category ID.
4. Create a high-priority ticket with `POST /api/v1/tickets/`.
5. Note the public ticket UUID, frozen SLA deadlines, and `X-Request-ID` response header.

## 3. Agent Takes Ownership and Responds

1. Log in as `agent@serviceflow.local` and replace the Swagger authorization token.
2. Call `POST /api/v1/tickets/{public_id}/take/`.
3. Transition the ticket to `in_progress`.
4. Add a comment through `POST /api/v1/tickets/{public_id}/comments/`.
5. Retrieve the ticket and observe `first_responded_at` and the first-response SLA status.

The first operator comment completes first response; requester comments do not.

## 4. Inspect Audit and Workflow

1. Read `GET /api/v1/tickets/{public_id}/history/`.
2. Confirm assignment, transition, comment/SLA, and attachment events are traceable.
3. Transition to `resolved`, inspect `first_resolved_at`, then optionally close the ticket.

## 5. Upload and Download an Attachment

1. Before entering a terminal state, upload a small PDF or TXT file through the multipart
   `attachments` action.
2. List attachments and confirm the object key is not exposed.
3. Call the download action and inspect the temporary presigned URL.
4. Open MinIO at <http://localhost:9001> with local credentials `minioadmin` / `minioadmin` to show
   that bytes are private object-storage data while metadata remains in PostgreSQL.

## 6. Show Async Correlation

Create or transition another ticket with an explicit request header:

```text
X-Request-ID: interview-demo-001
```

Then inspect:

```bash
docker compose logs --tail=100 api worker
```

The API completion and notification task logs share `interview-demo-001`, while the task log also
contains its Celery task name and ID.

## 7. Operational Endpoints

- `/health/` proves process liveness without dependency checks.
- `/health/ready/` checks PostgreSQL and reports Redis degradation separately.
- `/api/v1/metrics/` exposes ticket and SLA aggregates to agents/admins.

The editable [REST Client collection](serviceflow.http) automates the same HTTP sequence.
