## Context

The existing `recruit-social` eTalent module already exposes candidate search through `TalentController /talent/list/page`, converts `TalentResumeForm` into `ESResumeQuery`, applies dictionary and label conversion, executes existing `ResumeQueryBuilder` implementations, and returns masked candidate cards. Its request object is broad and contains fields that V1 does not support, so it must not be exposed directly to an LLM.

The new project currently contains only a minimal Python package and an experimental `ChatOpenAI` client. The target system is a separate Python orchestration service. Recruiters interact through a conversation UI, while Java remains authoritative for business codes, permissions, Elasticsearch semantics, and candidate-card visibility.

V1 supports candidate search without a recruitment position. Candidate position text such as “Java backend” is a search condition; recruitment `positionId`, JD interpretation, and person-to-job matching remain outside the boundary.

## Goals / Non-Goals

**Goals:**

- Translate recruiter messages into a visible, validated, versioned SearchPlan.
- Support exactly nine candidate-search dimensions in V1: name, candidate position, minimum education, work years, company, school, expected work location, current location, and school-level labels.
- Support first search, multi-turn plan changes, clarification cards, reset, pagination, status queries, casual messages, and cancellation.
- Reuse eTalent search while preserving Java permission and masking behavior.
- Keep the workflow deterministic and testable: the LLM interprets language, while application code decides what may execute.
- Allow relevant user messages to supersede long-running work without adding complex distributed fencing to V1.

**Non-Goals:**

- Recruitment-position binding, `positionId`, JD parsing, job profiles, or person-to-job scoring.
- Project/skill evidence search, preference ranking, per-candidate LLM assessment, or generated qualification claims.
- Vector search, external sourcing, candidate contact, export, or workflow mutation.
- An open-ended ReAct loop, multiple autonomous agents, or unrestricted model-selected tools.
- Strong rollback of a database write that already started when a user interrupts execution.

## Decisions

### 1. Separate Python orchestration service

`talent-agent-py` SHALL be a FastAPI service using Python 3.12, Pydantic v2, LangGraph `StateGraph`, HTTPX, SQLAlchemy async, Alembic, and PostgreSQL. The service owns conversation state and orchestration but does not own candidate data.

Keeping orchestration separate allows Python-native structured model output and graph control without duplicating Java talent-domain logic. Embedding Python in the Java process was rejected because it would complicate deployment and blur ownership.

### 2. Fixed LangGraph instead of an autonomous tool loop

The graph has code-defined nodes and edges:

```text
receive_message
→ route_message
→ load_context
→ parse_plan_patch
→ validate_draft
→ resolve_entities
→ clarify | save_plan
→ compile_search
→ search_candidates
→ finalize
```

Chat, progress, stop, page, clarification-answer, parse-error, unsupported-condition, and dependency-error paths are explicit branches. The model cannot add tools, retry indefinitely, or decide to bypass validation.

### 3. Message routing precedes the search graph

Every message is persisted and routed as one of:

```text
CASUAL_CHAT
STATUS_QUERY
CONTROL_STOP
PAGE_ACTION
CLARIFICATION_ANSWER
SEARCH_NEW
SEARCH_PATCH
UNKNOWN
```

Deterministic UI events and obvious control phrases are handled by rules. Ambiguous free text uses a lightweight structured classifier. Casual chat and status questions do not interrupt a search; new or changed search requirements do.

### 4. SearchPlan is the durable conversation memory

The service persists sessions, ordered messages, runs, pending clarifications, and immutable SearchPlan versions. A plan records the last applied message sequence. Model calls receive the current plan, pending clarification, and only the unapplied or necessary recent messages rather than the full conversation.

Initial search produces a `SearchPlanDraft`. Later changes produce a `PlanPatch` with add, replace, remove, or reset operations. Application code applies patches and preserves unmentioned conditions.

### 5. LLM output is semantic and code-free

The LLM produces Pydantic-validated structured output. It may emit human-language entities and scopes but MUST NOT emit business codes, Elasticsearch fields, SQL, operator identity, permission scopes, or system pagination settings. Java resolves natural-language entities into current business codes.

The experimental source-level API key in `internal_llm.py` is not an acceptable implementation. Model name, base URL, credentials, timeout, and retry policy are injected through settings and secret management behind an application `LLMClient` port.

### 6. Narrow Java integration contract

Python exposes only the nine supported dimensions to its compiler. The preferred integration is an internal Java adapter with two operations:

```text
resolve_entities
search_candidates
```

The adapter may internally reuse `/talent/list/page`, but Python does not send natural language or the full `TalentResumeForm`. Java injects the authenticated operator, resolves codes, applies existing query builders and permissions, and returns safe candidate cards.

Important known mappings include `topDegree` as a minimum degree, `workYearsMin/workYearsMax`, `nowPosition/onlyNowPosition`, `nowCompany/onlyNowCompany`, `livePlace`, `expectWorkPlace`, `schoolLevelList`, and `firstDegree`. Contract tests must fix the exact boundary and multiple-value semantics before production rollout.

### 7. Clarification is an explicit application state

When a blocking ambiguity or unsupported condition exists, the run returns `NEEDS_CLARIFICATION` and stores a `PendingClarification`. The frontend displays a fixed card generated from a reason code and safe parameters. A button submits `questionId + value`; the next invocation validates and applies the answer without another model call. Free-text answers pass through routing and structured interpretation.

This V1 request/response approach was selected over keeping an HTTP request or worker suspended. LangGraph checkpoint-based `interrupt/resume` can be introduced later without changing the API contract.

### 8. Lightweight interruption

The service keeps the active asynchronous task for a session. When routing identifies `SEARCH_NEW`, `SEARCH_PATCH`, or `CONTROL_STOP`, it attempts `asyncio.Task.cancel()`. Long-running LLM, entity-resolution, and Java-search nodes are registered through a common `@interruptible` wrapper that checks cancellation before and after the call.

An already-started database save is allowed to finish. A replacement run then reloads the latest committed SearchPlan and applies the new message. The UI accepts events only for its current `activeRunId`, preventing a late old result from replacing the visible result. V1 does not add complex per-write fencing.

### 9. Deterministic results and pagination

Python does not rerank candidates. Java supplies authorized, masked cards using existing search order. Responses include the executed plan version and a server-controlled page reference. Pagination does not call the LLM and is rejected if it no longer belongs to the active plan.

### 10. Distinct terminal states

The API and UI distinguish `OK`, `EMPTY`, `UNSUPPORTED`, `NEEDS_CLARIFICATION`, `DENIED`, `MODEL_ERROR`, `DEPENDENCY_ERROR`, `CANCELLED`, and `SUPERSEDED`. Permission or dependency failures must never appear as an empty candidate result.

## Risks / Trade-offs

- **Existing Java field semantics differ from recruiter wording** → Add contract tests for degree thresholds, work-year boundaries, position tokenization, company/school multi-value behavior, and city code types before enabling each field.
- **Cancellation cannot always stop an upstream LLM, Java, or Elasticsearch request** → Cancel local waiting where possible and ignore results from a non-active run in the frontend/event layer.
- **A plan save may complete after a user asks to change the search** → Accept the intermediate version as history; the replacement run reads it and creates the next version.
- **A lightweight classifier can misclassify short messages** → Handle card actions and explicit controls deterministically, preserve pending clarification state, and return an intent clarification for low-confidence messages.
- **Exposing the broad Java request would expand scope accidentally** → Maintain a narrow Python DTO and reject unknown fields at every external and LLM boundary.
- **Entity dictionaries change over time** → Resolve through Java at execution time and store both display values and resolved identifiers with the plan version used for a run.
- **Single-process task cancellation does not span replicas** → Keep V1 deployment simple or add a small Redis cancellation signal when horizontal execution is introduced; logical active-run filtering remains required at the event boundary.

## Migration Plan

1. Initialize the Python service foundation, configuration, persistence schema, and health endpoints.
2. Implement the domain schemas and graph with fake LLM and fake Java adapters.
3. Add Java entity-resolution and candidate-search contracts behind feature flags.
4. Run contract tests against a non-production eTalent environment and compare Agent requests with equivalent manual searches.
5. Enable the conversation entry point for an internal allowlist and collect parse, clarification, empty-result, and latency metrics.
6. Roll back by disabling the Agent entry point; the existing eTalent manual search remains unchanged.

## Open Questions

- Will Java expose dedicated internal Agent endpoints, or will the first adapter call the existing browser-oriented endpoint behind a service facade?
- What are the authoritative APIs and exact payloads for company, school, school-level, and city resolution?
- Does product require SSE in the first delivery, or is request polling sufficient for the initial internal release?
- What persistence engine and secret-management service are approved in the target environment?
- What exact timeout and cancellation behavior does the internal LLM gateway support?

