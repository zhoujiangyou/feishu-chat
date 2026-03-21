# AGENTS.md

## Cursor Cloud specific instructions

### Overview

Feishu Chat Service is a Python 3.12+ FastAPI backend that connects Feishu (Lark) with LLM-powered chatbots. It uses embedded SQLite (no external DB server), so no database setup is needed.

### Running the dev server

```bash
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The `--reload` flag enables hot-reload during development. The database (`data/app.db`) is auto-created on first startup.

### Running tests

```bash
source .venv/bin/activate
python3 -m pytest
```

All tests use mocks for external services (Feishu API, LLM endpoints). No external credentials are required to run the test suite.

### Key caveats

- The project requires `python3.12-venv` system package (not installed by default on some Ubuntu images). The update script handles this.
- External Feishu/LLM features require real credentials configured per-service instance via the `POST /api/v1/services` API. For local testing, dummy credentials work for creating service instances and exercising the knowledge base.
- The MCP sidecar (`python3 -m app.mcp_server`) is optional and only needed if testing MCP tool integration.
- API docs are at `/docs` (Swagger UI) and `/openapi.json` once the server is running.
