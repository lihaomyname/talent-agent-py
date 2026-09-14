## 1. Project Foundation

- [x] 1.1 Replace the generated package description and entry points with the approved `talent_agent_py` FastAPI application layout
- [x] 1.2 Add and lock the V1 runtime dependencies for FastAPI, Pydantic settings, LangGraph, HTTPX, SQLAlchemy async, Alembic, and the approved database driver
- [x] 1.3 Implement typed settings for the API, database, LLM, Java service, timeouts, search defaults, and feature flags
- [x] 1.4 Implement FastAPI lifespan initialization and cleanup for shared HTTP and database resources
- [x] 1.5 Add health and readiness endpoints that verify application startup without exposing credentials

## 2. Domain Models and Persistence

- [x] 2.1 Implement strict Pydantic models for the nine supported search dimensions and their scopes
- [x] 2.2 Implement immutable SearchPlan, SearchPlanDraft, PlanPatch, unsupported-condition, and clarification models
- [x] 2.3 Implement message route, session, run status, result status, and page-reference models
- [x] 2.4 Add SQLAlchemy models and Alembic migrations for sessions, ordered messages, runs, plan versions, and pending clarifications
- [x] 2.5 Implement repositories and transaction boundaries for creating sessions, idempotently accepting messages, reading the current plan, and saving a new plan version
- [x] 2.6 Persist `appliedThroughMessageSeq` and verify that a replacement run can load all relevant unapplied messages

## 3. LLM and Structured Parsing

- [x] 3.1 Define the application `LLMClient` port for message classification, initial draft parsing, and PlanPatch parsing
- [x] 3.2 Replace the experimental hard-coded LLM client with a settings-driven HTTP adapter that does not contain source-level credentials
- [x] 3.3 Implement versioned structured-output schemas with unknown-field rejection and one bounded repair attempt
- [x] 3.4 Implement and version the system prompts for routing, SearchPlanDraft parsing, and PlanPatch parsing
- [x] 3.5 Add tests covering supported-field extraction, no invented conditions, unsupported-condition capture, and malformed model output

## 4. Message Routing, Clarification, and Interruption

- [x] 4.1 Implement rule-first routing for card answers, page actions, explicit stop commands, progress queries, and obvious casual conversation
- [x] 4.2 Implement lightweight structured classification for messages that deterministic routing cannot resolve
- [x] 4.3 Implement fixed clarification-card templates for location scope, position/company scope, entity ambiguity, and unsupported conditions
- [x] 4.4 Implement pending-clarification storage and validation of `questionId + value` card answers without another LLM call
- [x] 4.5 Implement the per-session asynchronous TaskRegistry and cancellation service for active runs
- [x] 4.6 Implement the shared `@interruptible` wrapper for long-running LLM and Java nodes while allowing an active plan save to complete
- [x] 4.7 Verify that casual chat does not interrupt search and that late events from a superseded run are not exposed as the active result

## 5. SearchPlan Validation and Java Contracts

- [x] 5.1 Implement deterministic validation for field support, ranges, scopes, conflicts, string lengths, and required clarifications
- [x] 5.2 Define the `TalentSearchPort` request and response models for entity resolution and candidate search
- [x] 5.3 Implement the HTTPX Java adapter with service authentication, correlation IDs, bounded timeouts, and error mapping
- [x] 5.4 Implement entity resolution for education, company, school, city, and school-level labels without accepting model-generated codes
- [x] 5.5 Implement the narrow compiler mapping SearchPlan fields to the Java eTalent request and server-controlled search defaults
- [x] 5.6 Add Java contract tests for minimum-degree semantics, work-year boundaries, position tokenization, current/history scopes, multi-value behavior, and city representation

## 6. LangGraph Orchestration

- [x] 6.1 Implement serializable AgentState containing session, run, current plan, unapplied messages, draft or patch, clarification, compiled request, and result references
- [x] 6.2 Implement nodes for context loading, structured parsing, validation, entity resolution, clarification, plan saving, request compilation, search, and finalization
- [x] 6.3 Build the fixed StateGraph with explicit search, patch, card-answer, page, casual-chat, progress, stop, unsupported, and failure branches
- [x] 6.4 Implement the replacement-run path so a user search change reloads the latest committed plan and continues with unapplied messages
- [x] 6.5 Add graph tests for initial search, clarification round trip, multi-turn patch, explicit reset, interruption during LLM search, and interruption during plan save

## 7. API and Result Delivery

- [x] 7.1 Implement authenticated session creation and session-read endpoints
- [x] 7.2 Implement the idempotent message endpoint and return run, clarification, or immediate-chat responses as appropriate
- [x] 7.3 Implement run status and cancellation endpoints
- [x] 7.4 Implement result and deterministic pagination endpoints that reject stale plan references
- [x] 7.5 Implement result formatting for condition cards, authorized Java talent cards, plan version, run ID, and page information
- [x] 7.6 Implement distinct API error mappings for empty, unsupported, clarification, denied, model error, dependency error, cancelled, and superseded states
- [x] 7.7 Add SSE progress delivery if selected for V1, otherwise document and implement the polling contract

## 8. Verification and Delivery

- [x] 8.1 Add unit tests for domain validation, patch application, routing, clarification answers, request compilation, and error mapping
- [x] 8.2 Add integration tests using fake LLM and Java servers for the complete conversation-to-result flow
- [x] 8.3 Add security tests proving clients and model output cannot set operator identity, unmask clues, expand page limits, or inject unsupported Java fields
- [x] 8.4 Add evaluation cases for representative Chinese recruiter utterances, ambiguous requests, casual interruptions, and unsupported requirements
- [x] 8.5 Add structured logs and metrics for run stage, parse outcome, clarification rate, Java latency, cancellation, empty results, and failures
- [x] 8.6 Document local setup, environment variables, database migration, test commands, Java contract assumptions, and the V1 capability boundary
- [x] 8.7 Run OpenSpec validation and the full automated test suite before enabling the feature flag in a non-production environment
