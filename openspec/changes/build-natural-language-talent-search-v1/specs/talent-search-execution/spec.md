## ADDED Requirements

### Requirement: Narrow V1 Java search request
The system SHALL compile an executable SearchPlan into a narrow Java request containing only the supported search dimensions and server-controlled execution options.

#### Scenario: Compile a supported plan
- **WHEN** a plan contains resolved name, position, degree, years, company, school, current city, and school-level conditions
- **THEN** the compiler maps them to the corresponding Java fields without forwarding unsupported plan content

#### Scenario: Reject unknown tool fields
- **WHEN** an LLM response or external client attempts to supply an additional Java search field
- **THEN** the system rejects or ignores it before the Java call according to the strict request schema and records the validation failure

### Requirement: Server-controlled search policy
The system SHALL control page size, sort type, keyword match type, flow visibility, clue masking, authenticated operator, timeout, and other safety parameters independently of user and model output.

#### Scenario: Model attempts to alter safety parameter
- **WHEN** model output contains an operator identifier, requests unmasked clues, or requests an excessive page size
- **THEN** the system does not propagate those values and uses the configured server policy

### Requirement: Java remains the authorization and search authority
The system SHALL call Java with authenticated service context, and Java SHALL perform final user authorization, dictionary semantics, existing Elasticsearch query construction, and candidate-card masking.

#### Scenario: Authorized talent search
- **WHEN** an authenticated user submits a valid executable plan
- **THEN** Java searches only data visible to that user and returns safe candidate cards

#### Scenario: Java denies access
- **WHEN** Java determines that the effective user cannot perform the search
- **THEN** the system returns `DENIED` without candidate count, cached candidates, or hidden field values

### Requirement: Existing field mappings
The compiler SHALL map minimum degree to `topDegree`, work years to `workYearsMin/workYearsMax`, candidate position to `nowPosition/onlyNowPosition`, company to `nowCompany/onlyNowCompany`, current location to `livePlace`, expected location to `expectWorkPlace`, and school-level constraints to `schoolLevelList/firstDegree` using values resolved by Java.

#### Scenario: Minimum bachelor and three-to-five years
- **WHEN** the resolved plan requires bachelor or above and three to five work years
- **THEN** the Java request uses the resolved bachelor `topDegree` code and sets `workYearsMin=3` and `workYearsMax=5` without sending a synthetic `workYears` array

#### Scenario: Expected location
- **WHEN** a location has scope `EXPECTED_CITY`
- **THEN** the compiler populates `expectWorkPlace` using the Java-resolved representation and does not also populate `livePlace`

### Requirement: Result response reflects executed plan
The system SHALL return the executed plan version, run identifier, safe Java candidate cards, result state, and pagination information. It SHALL not generate candidate-job scores or LLM reranking in V1.

#### Scenario: Successful first page
- **WHEN** Java returns authorized candidates for page one
- **THEN** the system returns those cards in Java's search order with the executed plan version and next-page information

#### Scenario: Empty search
- **WHEN** Java successfully returns no candidates
- **THEN** the system returns `EMPTY`, shows the unchanged executed conditions, and does not automatically relax or rerun them

### Requirement: Deterministic pagination
The system SHALL execute pagination from the current SearchPlan and validated page reference without calling the LLM.

#### Scenario: Read next page
- **WHEN** the user requests the next page using a page reference for the current plan
- **THEN** the system calls Java directly with the same plan and the next server-controlled page position

#### Scenario: Stale page reference
- **WHEN** search conditions have changed since a page reference was issued
- **THEN** the system rejects the stale reference and does not mix results from different plan versions

### Requirement: Distinct dependency and model failures
The system SHALL preserve the difference between empty results, authorization denial, model failure, Java or Elasticsearch dependency failure, cancellation, and supersession.

#### Scenario: Java dependency failure
- **WHEN** Java or Elasticsearch times out or returns an unavailable error
- **THEN** the system returns `DEPENDENCY_ERROR`, retains the confirmed SearchPlan, and does not report that no candidates exist

#### Scenario: Superseded search result
- **WHEN** a search completes after a newer run has replaced it
- **THEN** the system marks or treats the old run as superseded and does not publish its candidates as the active result

