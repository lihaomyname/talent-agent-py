## ADDED Requirements

### Requirement: V1 supported search dimensions
The system SHALL represent only candidate name, candidate position, minimum education, work years, company, school, expected work location, current location, and school-level labels as executable V1 search conditions.

#### Scenario: Parse a complete supported request
- **WHEN** the user requests a named Java backend candidate with a minimum degree, work-year range, company, school, location, and school-level label
- **THEN** the system produces a draft containing the corresponding supported dimensions without adding unmentioned conditions

#### Scenario: Candidate position is not recruitment-position matching
- **WHEN** the user specifies “Java 后端” as the candidate position
- **THEN** the plan records candidate resume position text and does not create a recruitment `positionId`, job profile, or person-to-job score

### Requirement: Explicit condition semantics
The system SHALL retain scopes and range semantics needed to distinguish current from historical position or company, current from expected location, minimum education, and bounded or one-sided work years.

#### Scenario: Current position only
- **WHEN** the user says “只看当前职位是 Java 后端”
- **THEN** the plan records position `Java 后端` with scope `CURRENT`

#### Scenario: Historical company allowed
- **WHEN** the user says “在网易工作过”
- **THEN** the plan records company `网易` with current-or-history scope unless later clarification establishes a narrower scope

#### Scenario: Minimum education
- **WHEN** the user says “本科及以上”
- **THEN** the plan records a minimum-degree semantic value of bachelor without requiring the LLM to produce the Java code

#### Scenario: Work-year range
- **WHEN** the user says “3到5年工作经验”
- **THEN** the plan records minimum 3 and maximum 5 work years

### Requirement: Structured model output
The system SHALL require LLM parsing and patching responses to conform to versioned Pydantic schemas that reject unknown fields and unbounded free-form tool parameters.

#### Scenario: Valid structured draft
- **WHEN** the model returns a draft that conforms to the current schema
- **THEN** the system proceeds to deterministic validation and entity resolution

#### Scenario: Invalid model output
- **WHEN** the model returns malformed output or fields outside the schema and the allowed repair attempt fails
- **THEN** the system returns `MODEL_ERROR`, does not save a partial plan, and does not execute talent search

### Requirement: Business identifiers are resolved outside the LLM
The system SHALL send human-language entities to the Java resolution port and SHALL use only Java-returned codes or identifiers in executable search requests.

#### Scenario: Resolve degree and location
- **WHEN** a valid draft contains bachelor and Hangzhou
- **THEN** the service obtains the current degree and city identifiers from the business integration rather than accepting identifiers invented by the model

#### Scenario: Ambiguous entity resolution
- **WHEN** Java returns multiple valid entities for a company, school, city, or label name
- **THEN** the system records a blocking ambiguity and requests the user to choose before search execution

### Requirement: Unsupported conditions are never silently dropped
The system SHALL retain detected unsupported requirements separately from executable conditions and SHALL require an explicit user decision before ignoring a user-stated hard condition.

#### Scenario: Unsupported project experience
- **WHEN** the user requires payment-system project experience
- **THEN** the system reports that V1 cannot directly filter the condition and asks whether to remove or restate it

#### Scenario: User chooses to ignore unsupported condition
- **WHEN** the user explicitly chooses to ignore a previously reported unsupported condition
- **THEN** the system removes it from the blocking set, records the decision, and proceeds with the remaining supported conditions

### Requirement: Immutable plan versions
The system SHALL persist each accepted complete SearchPlan as a new immutable version and SHALL identify which message sequence has been applied.

#### Scenario: Initial executable plan
- **WHEN** a validated and resolved first search has no blocking issues
- **THEN** the system saves SearchPlan version 1 with its source message sequence before executing search

#### Scenario: Later plan modification
- **WHEN** a valid PlanPatch changes an existing plan
- **THEN** the system saves a new version and retains the previous version as history

### Requirement: PlanPatch preserves unmentioned conditions
The system SHALL apply explicit add, replace, remove, and reset operations to the current plan and SHALL preserve all conditions not addressed by the patch.

#### Scenario: Replace years and add current city
- **WHEN** the user changes work years to at least five and adds current city Shanghai
- **THEN** the system changes those fields and preserves existing name, degree, company, school, and school-level conditions

#### Scenario: Reset all conditions
- **WHEN** the user explicitly asks to clear the search and start over
- **THEN** the system creates a new empty plan state before interpreting the new request

### Requirement: Deterministic plan validation
The system SHALL validate supported fields, scopes, ranges, value counts, string lengths, conflicts, and required clarifications in application code before compiling any Java search request.

#### Scenario: Invalid work-year range
- **WHEN** a draft has a minimum work year greater than its maximum
- **THEN** the system rejects the draft or asks for correction and does not call the Java talent search

#### Scenario: Conflicting location interpretation
- **WHEN** a location cannot be assigned to current or expected location from the user's wording
- **THEN** the system requests clarification rather than populating both fields or guessing one

