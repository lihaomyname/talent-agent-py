## Why

Recruiters currently need to understand and operate a large number of eTalent filters to find candidates. A controlled natural-language search service can turn recruiter conversations into auditable search plans while preserving the existing Java service's dictionary, permission, Elasticsearch, and data-masking behavior.

## What Changes

- Add a Python FastAPI service that owns talent-search sessions, messages, runs, clarification state, and versioned search plans.
- Add a fixed LangGraph workflow for message routing, structured intent parsing, validation, entity resolution, clarification, plan persistence, Java request compilation, search, and result formatting.
- Support candidate search by name, candidate position, minimum education, work years, company, school, expected work location, current location, and school-level labels.
- Support multi-turn additions, replacements, removals, resets, structured clarification answers, and deterministic pagination.
- Add a narrow internal integration contract to reuse the existing `recruit-social` eTalent dictionary, permission, Elasticsearch query, and safe candidate-card capabilities.
- Add lightweight execution interruption: irrelevant chat does not stop a search; relevant search changes supersede the active run; long-running LLM and Java calls are cancellation-aware; an in-progress database save may complete and the next run continues from the latest saved plan.
- Explicitly reject or clarify unsupported search requirements instead of silently dropping them.
- Exclude recruitment-position binding, `positionId`, JD parsing, person-to-job scoring, per-candidate LLM ranking, vector retrieval, external sourcing, and candidate write actions from V1.

## Capabilities

### New Capabilities

- `conversation-orchestration`: Session and message handling, message routing, clarification cards, multi-turn memory, run lifecycle, interruption, and progress behavior.
- `search-plan-management`: Structured SearchPlan and PlanPatch creation, supported-field semantics, validation, entity resolution, versioning, and unsupported-condition handling.
- `talent-search-execution`: Deterministic compilation to a narrow Java request, authorized eTalent/Elasticsearch execution, safe results, pagination, and distinct failure states.

### Modified Capabilities

None. This is a new service and the project currently has no baseline OpenSpec capabilities.

## Impact

- New Python package under `src/talent_agent_py` using FastAPI, Pydantic v2, LangGraph, HTTPX, SQLAlchemy async, and Alembic.
- New Agent-owned persistence for sessions, messages, runs, SearchPlan versions, and pending clarifications.
- New or adapted Java internal APIs in `recruit-social` for entity resolution and candidate search; Java remains authoritative for user permissions, business codes, Elasticsearch query semantics, and masked candidate cards.
- The existing broad `TalentResumeForm` is not exposed to the model. Python compiles a narrow, validated V1 contract into the Java request.
- The current experimental `internal_llm.py` must be converted to a configured client adapter; secrets must not be embedded in source code.
