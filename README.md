# ServiceFlow API

ServiceFlow is a portfolio-ready REST API for managing support tickets. It demonstrates more
than CRUD: role-based object access, explicit workflow and SLA rules, transactional audit history,
concurrency-safe ownership, JWT authentication, asynchronous notifications, and documented APIs.

## Stack

- Python 3.12, Django 5, Django REST Framework
- PostgreSQL, Redis, Celery, MinIO/S3-compatible object storage
- SimpleJWT, django-filter, drf-spectacular
- pytest, coverage, Ruff
- Docker Compose and GitHub Actions

## Architecture

```text
apps/
├── accounts/      custom email-based user, roles and authentication API
└── tickets/       models, serializers, filters, permissions, services and Celery tasks
config/
├── settings/      shared, local and test settings
├── celery.py      worker configuration
├── exceptions.py  consistent domain error responses
└── urls.py        API, schema, Swagger and health routes
tests/             domain and API integration tests
```

Business operations live in `apps/tickets/services.py`. Status changes and assignments lock the
ticket row with `select_for_update()`, update state and audit history in one transaction, then use
`transaction.on_commit()` to enqueue a notification. This prevents side effects for rolled-back
transactions and prevents two agents from silently taking the same ticket.

## Quick start with Docker

```bash
docker compose up -d --build
docker compose exec api python manage.py seed_dev
```

The Compose stack runs PostgreSQL, Redis, private MinIO object storage, the Gunicorn API, a Celery
worker and one Celery Beat instance. The `minio-init` container idempotently creates the private
`serviceflow-attachments` bucket. Beat is intentionally single-instance in development; row
locking and idempotent breach writes still protect against overlapping task executions.

Open Swagger at <http://localhost:8000/api/docs/> and health at
<http://localhost:8000/health/>. The MinIO console is available at <http://localhost:9001/> using
the development-only `minioadmin` credentials. Stop the stack with `docker compose down`; add `-v`
only when you intentionally want to remove PostgreSQL, Redis and MinIO data.

Development seed credentials use the password `ServiceFlow123!`:

- `admin@serviceflow.local`
- `agent@serviceflow.local`
- `requester@serviceflow.local`

These accounts are local examples only. `seed_dev` is idempotent.

## Local setup without Docker

SQLite is the zero-configuration fallback. PostgreSQL is used when `DATABASE_URL` is present.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install ".[dev]"
python manage.py migrate
python manage.py seed_dev
python manage.py runserver
```

Copy `.env.example` values into your environment when using PostgreSQL, Redis, or production-like
settings. Secrets and the real `.env` are intentionally excluded from Git.

## API

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/auth/register/` | Public requester registration |
| POST | `/api/v1/auth/login/` | Obtain access and refresh JWTs |
| POST | `/api/v1/auth/token/refresh/` | Refresh an access token |
| GET | `/api/v1/auth/me/` | Current user profile |
| GET, POST | `/api/v1/tickets/` | List accessible tickets or create one |
| GET, PATCH | `/api/v1/tickets/{public_id}/` | Retrieve or edit safe fields |
| POST | `/api/v1/tickets/{public_id}/take/` | Agent takes ownership |
| POST | `/api/v1/tickets/{public_id}/assign/` | Assign or unassign an operator |
| POST | `/api/v1/tickets/{public_id}/transition/` | Explicit workflow transition |
| GET, POST | `/api/v1/tickets/{public_id}/comments/` | Scoped comments |
| GET | `/api/v1/tickets/{public_id}/history/` | Read-only audit trail |
| GET | `/api/v1/categories/` | Active and inactive categories |
| POST, PATCH | `/api/v1/categories/` | Admin category management |
| GET | `/api/v1/sla-policies/` | Agent/admin policy lookup |
| POST, PATCH | `/api/v1/sla-policies/` | Admin policy management |
| GET | `/api/v1/metrics/` | Operator ticket and SLA metrics |
| GET, POST | `/api/v1/tickets/{public_id}/attachments/` | List or upload attachments |
| GET | `/api/v1/tickets/{public_id}/attachments/{attachment_id}/download/` | Signed download URL |
| DELETE | `/api/v1/tickets/{public_id}/attachments/{attachment_id}/` | Delete an attachment |

Ticket listing supports `status`, `priority`, category slug, assignee and requester filters;
`search` over title/description; controlled `ordering`; and page-number pagination (20 by default,
100 maximum). Requester filtering never bypasses the base object-access queryset.

## Roles and workflow

- Requesters create and see only their own tickets, comment on them, edit safe fields while open,
  and may cancel their own active ticket.
- Agents see operational tickets, take ownership, update safe fields and execute transitions.
- Admins have broad operational access and can reassign tickets or manage categories.
- Public registration always creates a requester, regardless of extra client fields.
- Assignees must be agents or admins. Server-controlled state cannot be mass-assigned.

```text
OPEN
├── IN_PROGRESS (requires assignee)
└── CANCELLED

IN_PROGRESS
├── WAITING_REQUESTER
├── RESOLVED
└── CANCELLED

WAITING_REQUESTER
├── IN_PROGRESS
├── RESOLVED
└── CANCELLED

RESOLVED
├── IN_PROGRESS (reopens and clears resolved_at)
└── CLOSED
```

Closed and cancelled tickets are terminal. Resolution and closure timestamps are server-owned.
Every important state, priority, category, assignment, and field change receives an audit entry.

## SLA Management

SLA uses elapsed calendar time. Business hours, holidays and regional calendars are intentionally
outside this phase. One active persisted policy defines first-response and resolution targets for
each priority:

| Priority | First response | Resolution |
|---|---:|---:|
| Low | 24 hours | 120 hours |
| Medium | 8 hours | 72 hours |
| High | 4 hours | 24 hours |
| Urgent | 1 hour | 8 hours |

Creating a ticket requires an active policy. Its deadlines are calculated from `created_at` and
stored on the ticket, so later policy edits never silently rewrite historical commitments. An
explicit priority change is different: it intentionally recalculates both deadlines from the
original creation timestamp using the newly applicable policy. If that makes the ticket overdue,
the breach is recorded in the same transaction.

The first agent or administrator comment completes First Response SLA; requester comments do not.
`first_resolved_at` records the first resolution permanently for Resolution SLA, while
`resolved_at` still describes the current state and is cleared on reopening. Completion at or
before the deadline is met; later completion is breached. Cancellation stops future checks but
preserves breaches already recorded.

```text
Ticket created
      │
      ▼
Resolve active policy → calculate and persist deadlines
      │
      ▼
Celery Beat checks overdue candidates every minute
      │
      ├── no breach → no write
      └── breach → row lock → timestamp + history → commit → notification task
```

Candidate selection happens in the database. Each update rechecks a locked row and only writes an
empty breach timestamp, making repeated or concurrent checks idempotent: timestamps, history and
notifications are not duplicated. The interval is controlled by `CELERY_BEAT_SCHEDULE` in Django
settings. Inspect processing with:

```bash
docker compose logs -f worker beat
```

Ticket details expose frozen deadlines, completion/breach timestamps and readable `pending`,
`met`, `breached` or `not_applicable` statuses. Operators can use `?sla_status=breached` or
`?overdue=true`; `/api/v1/metrics/` returns status counts, breach counts and database-calculated
average response/resolution durations.

## Attachments and object storage

Attachment metadata lives in PostgreSQL; binary content lives in private S3-compatible object
storage. Ticket services depend on a small storage adapter rather than MinIO or AWS directly.
MinIO is the local provider, while production can point the same environment variables at AWS S3
or another compatible service. There is intentionally no automatic filesystem fallback: storage
outages fail clearly with a sanitized `503` response.

```text
multipart upload
      |
      v
validate name + extension + MIME + size
      |
      v
stream SHA-256 -> upload UUID key to object storage
      |
      v
lock and revalidate ticket -> metadata + audit transaction
      |
      +-- database/state failure -> compensating object deletion
```

Upload permits PDF, PNG, JPEG, TXT, CSV, DOCX and XLSX files up to 10 MiB by default. Extension and
declared MIME must match the allowlist. Empty, extensionless, executable, HTML, SVG, oversized and
header-injection filenames are rejected. Original names are normalized as metadata only; object
keys use ticket and attachment UUIDs, so traversal and duplicate filenames cannot collide.

Requesters can access attachments only through their own ticket. They may delete only files they
uploaded; agents and administrators can delete files on accessible tickets. Closed and cancelled
tickets remain readable but reject upload and deletion. Downloads are explicit, authorized API
operations returning a five-minute presigned URL with the original filename in
`Content-Disposition`; lists never generate signed URLs or expose bucket keys.

Deletion commits metadata removal and audit history first, then deletes the object after commit.
If that final operation fails, the orphan is logged for future cleanup rather than restoring stale
metadata. Upload uses the inverse compensation: an object is deleted if metadata persistence or
the terminal-state recheck fails. This avoids pretending PostgreSQL and S3 share a distributed
transaction.

Current limitations:

- no malware scanning;
- no direct-to-S3 browser upload;
- no asynchronous media processing or orphan cleanup task.

Relevant storage settings are documented in `.env.example`. Check local infrastructure with:

```bash
docker compose logs minio minio-init
```

## Quality checks

```bash
ruff check .
ruff format --check .
python manage.py check
python manage.py makemigrations --check --dry-run
pytest
pytest --cov --cov-report=term-missing
docker compose config
```

The CI workflow runs the same checks against a PostgreSQL 16 service on pushes and pull requests
to `main`.
