## ADDED Requirements

### Requirement: Authorized conversation sessions
The system SHALL create talent-search sessions for authenticated users and SHALL associate every message, run, plan, clarification, and result with its owning session and user context.

#### Scenario: Create a session
- **WHEN** an authenticated recruiter opens natural-language talent search
- **THEN** the system creates an empty session with no current SearchPlan and returns a session identifier

#### Scenario: Reject access to another user's session
- **WHEN** a user submits a message or reads results for a session they do not own
- **THEN** the system rejects the request without exposing session content or candidate information

### Requirement: Idempotent message acceptance
The system SHALL persist each accepted message with an ordered sequence and SHALL use the client message identifier to avoid executing the same submission more than once.

#### Scenario: Duplicate message submission
- **WHEN** the client retries a message using the same client message identifier
- **THEN** the system returns the existing message and run reference without invoking the LLM or Java search again

### Requirement: Message routing
The system SHALL classify an incoming message as casual chat, status query, stop control, page action, clarification answer, new search, search patch, or unknown before deciding whether to run the search workflow.

#### Scenario: Casual greeting during a search
- **WHEN** the user sends “你好” or equivalent casual conversation while a search run is active
- **THEN** the system replies without cancelling or modifying the active search run

#### Scenario: Search modification during a search
- **WHEN** the user sends a message that changes an active search condition
- **THEN** the system supersedes the active run and starts a replacement run that incorporates the change

#### Scenario: Unknown message intent
- **WHEN** the router cannot determine whether the message changes the search
- **THEN** the system asks the user to clarify their intent and does not silently change the current SearchPlan

### Requirement: Multi-turn conversation memory
The system SHALL preserve confirmed search conditions across turns through the current versioned SearchPlan and SHALL provide only the necessary current plan, pending clarification, and unapplied messages to the model.

#### Scenario: Modify one condition
- **WHEN** the current plan contains position, city, education, and work years and the user says “把杭州改成上海”
- **THEN** the new plan replaces only the city and preserves the unmentioned position, education, and work-year conditions

#### Scenario: Start a new search explicitly
- **WHEN** the user explicitly asks to start over with a different kind of candidate
- **THEN** the system creates a new plan from the new search request instead of treating every field as an addition to the previous plan

### Requirement: Clarification cards
The system SHALL stop search execution when a blocking ambiguity or unsupported condition requires a user decision and SHALL return a structured clarification card with a stable question identifier and allowed answers.

#### Scenario: Ambiguous location
- **WHEN** a user specifies “杭州” without indicating current residence or expected work location
- **THEN** the system returns choices for current residence and expected work location and does not execute the talent search

#### Scenario: Structured clarification answer
- **WHEN** the user submits a valid card answer containing the pending question identifier and an allowed value
- **THEN** the system applies the answer without another LLM call and continues plan creation

#### Scenario: Unrelated message while clarification is pending
- **WHEN** a clarification is pending and the user sends casual conversation
- **THEN** the system retains the pending clarification and does not treat the casual message as its answer

### Requirement: Lightweight run interruption
The system SHALL attempt to cancel an active asynchronous run when a new search, search modification, or stop control requires interruption. It SHALL allow an already-started database save to complete and SHALL continue replacement work from the latest committed plan.

#### Scenario: Interrupt during model parsing
- **WHEN** the user changes the search while the LLM parsing node is running
- **THEN** the system attempts to cancel the old task, marks the old run superseded, and starts a replacement run with all still-relevant unapplied messages

#### Scenario: Interrupt during plan save
- **WHEN** the user changes the search after the old run has begun saving a SearchPlan
- **THEN** the old save may finish and the replacement run reads that plan before applying the new change

#### Scenario: Explicit stop
- **WHEN** the user says to stop the search
- **THEN** the system attempts to cancel the active task, marks the run cancelled, and does not automatically start another search

### Requirement: Active result visibility
The system SHALL identify all progress and result events by run identifier, and the client SHALL display search results only for its current active run.

#### Scenario: Late result from superseded run
- **WHEN** a Java response arrives after its run has been superseded
- **THEN** the old result is not displayed over the current run's state or result

### Requirement: Observable run status
The system SHALL expose the current run stage and terminal status without requiring another full search-planning model call.

#### Scenario: Ask for progress
- **WHEN** a user asks for current progress while a run is active
- **THEN** the system returns the persisted or in-memory run stage and keeps the run active

