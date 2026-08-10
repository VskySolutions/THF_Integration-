# FastAPI backend

Feature-first FastAPI service with PostgreSQL, SQLAlchemy 2, Alembic, and
`X-API-KEY` header authentication.

## Structure

```text
app/
├── core/                 # Shared configuration
├── db/                   # Shared database primitives
├── features/
│   ├── auth/
│   │   ├── dependencies/ # X-API-KEY dependency
│   │   ├── models/       # Reserved for auth persistence
│   │   ├── routers/      # Auth endpoints
│   │   └── schemas/      # Auth request/response objects
│   ├── caseware_cloud_intergration/ # Caseware models, schemas, services, routers
│   └── exception_logs/              # Shared exception persistence
└── main.py               # App creation and feature-router imports
```

For each new feature, create `app/features/<feature>/` and keep its `models`,
`schemas`, `services`, `dependencies`, and `routers` packages there. Only create
the packages a feature needs. Only genuinely shared infrastructure belongs in
`core` or `db`.

## Run locally

```powershell
cd backend
Copy-Item .env.example .env
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
docker compose up -d db
alembic upgrade head
uvicorn app.main:app --reload
```

Swagger UI is at `http://localhost:8000/docs`. Click **Authorize** and enter the
configured API key, or send it in the `X-API-KEY` header.

Application, PostgreSQL, API-key, and Maconomy connection settings are loaded
from `.env`. Copy `.env.example` for the complete supported variable list.

To run everything in containers, create `.env` and run
`docker compose up --build`.

## Quality checks

```powershell
pytest
ruff check .
```

The default `change-me` key only makes a fresh local checkout importable. Always
set `API_KEYS` to one or more long random values outside local development.

## Exception logging

Central exception handlers persist HTTP exceptions, request-validation errors,
and unexpected exceptions to PostgreSQL's `exception_logs` table. Every request
gets an `X-Request-ID` response header, which can be used to find its log entry.
The logger stores routing and debugging metadata but never stores request headers
or request bodies, preventing API keys and payload secrets from being persisted.
If database logging fails, the original API response is still returned.

## Caseware Cloud integration

The `app/features/caseware_cloud_intergration` feature owns the Caseware Cloud
entity-engagement mapping and integration-log models and schemas. Integration
status is constrained to `SUCCESS` or `FAILED`, and action is constrained to
`CREATE` or `UPDATE` at both the API-schema and PostgreSQL levels.
