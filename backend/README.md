# FlowPilot AI - Backend (Week 1 / Phase 1)

This is the **first vertical slice** of FlowPilot AI: turning free-text
requests into a validated, structured, human-approvable execution plan.

**Nothing in this phase executes a real action.** No Google Calendar, no
Gmail, no Todoist, no n8n, no database, no auth. The agent only understands
a request and proposes a plan; a later phase adds approval + execution.

## 1. What Week 1 implements

- A single FastAPI service exposing `GET /health` and `POST /api/v1/agent/plan`.
- An explicit, linear LangGraph workflow (no loops, no branching, no
  multi-agent orchestration) that turns text into a plan.
- A local LLM (via Ollama) that proposes the plan; the raw output is never
  trusted — it is always parsed and re-validated with Pydantic before being
  returned.
- A fixed catalog of three logical tools (`calendar`, `tasks`, `email`) with
  a fixed set of operations each. Anything outside that catalog is rejected
  with a structured error instead of being silently accepted or hallucinated.
- Explicit handling of requests that are missing required details (e.g. "schedule
  a meeting tomorrow" with no title): the agent still returns a plan, but marks
  the missing fields instead of inventing them.

## 2. Architecture

```
Text Input
    |
    v
FastAPI            (app/api/v1/agent.py)
    |
    v
LangGraph          (app/agent/graph.py)
    |  UNDERSTAND_REQUEST -> GENERATE_PLAN -> VALIDATE_PLAN
    v
Ollama             (app/services/ollama_service.py)
    |
    v
Structured Plan    (raw JSON from the LLM)
    |
    v
Pydantic Validation (app/models/*)
    |
    v
JSON Response       (AgentPlanResponse)
```

The LangGraph state (`app/agent/state.py`) is an explicit `TypedDict` with:
`request_id`, `user_text`, `intent`, `raw_plan`, `execution_plan`,
`validation_errors`, `status`, `errors`.

Each node checks `state["errors"]` on entry and no-ops if a previous node
already failed — the graph itself has a single linear path
(`START -> UNDERSTAND_REQUEST -> GENERATE_PLAN -> VALIDATE_PLAN -> END`),
there is no conditional branching or looping.

The LLM call is isolated behind `app/services/ollama_service.py`
(`LLMProvider` protocol + `OllamaProvider` implementation), so a different
provider can be added later without touching the graph or nodes.

## 3. Folder structure

```
backend/
├── app/
│   ├── main.py                  FastAPI app, /health
│   ├── api/v1/agent.py          POST /api/v1/agent/plan
│   ├── agent/
│   │   ├── graph.py             LangGraph wiring
│   │   ├── state.py             Typed graph state
│   │   └── nodes/
│   │       ├── understand.py    UNDERSTAND_REQUEST
│   │       ├── plan.py          GENERATE_PLAN (calls Ollama)
│   │       └── validate.py      VALIDATE_PLAN (Pydantic validation)
│   ├── models/
│   │   ├── request.py           AgentPlanRequest
│   │   ├── action.py            Action, ToolName, OperationName
│   │   └── execution_plan.py    ExecutionPlan, AgentPlanResponse
│   ├── services/ollama_service.py   LLM provider abstraction
│   ├── core/{config.py,logging.py}
│   └── prompts/planner_prompt.py
├── tests/
├── requirements.txt
├── .env.example
└── README.md
```

## 4. Prerequisites

- Python 3.11+
- [Ollama](https://ollama.com) installed and running locally

## 5. Install Ollama and pull a model

Install Ollama from https://ollama.com (or your platform's package manager),
then pull a small instruction-tuned model that's good enough at following a
JSON-output instruction:

```bash
ollama pull llama3.2:3b
```

Any other Ollama chat model will work — just point `OLLAMA_MODEL` (see below)
at it. Larger/newer instruct models generally produce more reliable JSON.

## 6. Environment configuration

```bash
cd backend
cp .env.example .env
```

Key variables (see `.env.example` for the full list):

| Variable | Default | Meaning |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3.2:3b` | Model tag to use for planning |
| `OLLAMA_TIMEOUT_SECONDS` | `60` | Request timeout when calling Ollama |
| `LOG_LEVEL` | `INFO` | Root log level |

## 7. Install dependencies and start the backend

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt

uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/docs for the interactive OpenAPI docs.

## 8. Example request

```bash
curl -X POST http://localhost:8000/api/v1/agent/plan \
  -H "Content-Type: application/json" \
  -d '{"text": "Schedule a meeting with my AI team tomorrow at 3 PM and create a task to prepare the demo."}'
```

Example successful response shape:

```json
{
  "request_id": "b6b6...",
  "status": "success",
  "execution_plan": {
    "plan_id": "...",
    "intent": "productivity_workflow",
    "summary": "Create a meeting and a preparation task.",
    "status": "ready",
    "actions": [
      {
        "action_id": "action_1",
        "tool": "calendar",
        "operation": "create_event",
        "parameters": {"title": "AI Team Meeting", "datetime": "tomorrow at 3 PM"},
        "missing_information": [],
        "requires_approval": true
      },
      {
        "action_id": "action_2",
        "tool": "tasks",
        "operation": "create_task",
        "parameters": {"title": "Prepare the demo"},
        "missing_information": [],
        "requires_approval": true
      }
    ]
  },
  "errors": null
}
```

If the request is missing required details, `execution_plan.status` becomes
`"needs_clarification"` and the relevant action lists the missing field
names in `missing_information` instead of a guessed value.

If the LLM proposes an unsupported tool/operation or returns something that
can't be parsed into the schema, the response is `{"status": "error",
"execution_plan": null, "errors": [...]}` with HTTP 200 (the request itself
was fine, the *content* couldn't be turned into a valid plan). If Ollama
itself can't be reached at all, the API returns HTTP 502.

## 9. Run tests

Tests mock the LLM provider layer (`app.services.ollama_service`), so they
run without a live Ollama server.

```bash
cd backend
pytest
```

## 10. Current limitations (Week 1)

- No real execution of any action — `requires_approval` is always `true` and
  nothing is ever called against Google/Gmail/Todoist/etc.
- No persistence: nothing is stored between requests.
- No authentication/authorization.
- Single LLM call per request; no retry loop on malformed JSON (a malformed
  response is surfaced as a structured error, not silently retried forever).
- Time expressions (e.g. "tomorrow at 3 PM") are kept as the LLM's raw text,
  not resolved to a real timestamp — that belongs to a later phase.
- Plan quality depends on the chosen local model; smaller models may
  occasionally violate the JSON contract, which shows up as a
  `validation_failed`/`error` response rather than a crash.
