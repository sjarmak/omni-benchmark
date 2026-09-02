-- Benchmark telemetry database schema (docs/telemetry-db-plan.md).
-- Idempotent: every statement may be re-applied against an existing database.
-- Table bodies follow a fixed layout that schema.py parses: one column per
-- line as "<name> <type>[ NOT NULL]," and a final "PRIMARY KEY (...)" line.

CREATE SCHEMA IF NOT EXISTS telemetry;

CREATE TABLE IF NOT EXISTS telemetry.load_run (
    load_id text NOT NULL,
    started_at timestamptz,
    finished_at timestamptz,
    source_manifests jsonb,
    row_counts jsonb,
    loader_version text,
    system_commit text,
    PRIMARY KEY (load_id)
);

CREATE TABLE IF NOT EXISTS telemetry.run (
    run_id text NOT NULL,
    cohort_id text,
    condition text,
    arm text,
    repetition int,
    scope text,
    partition text,
    model_name text,
    model_provider text,
    model_version text,
    system_commit text,
    semantic_model_ref text,
    semantic_model_sha256 text,
    started_at timestamptz,
    finished_at timestamptz,
    question_count int,
    manifest jsonb,
    PRIMARY KEY (run_id)
);

CREATE TABLE IF NOT EXISTS telemetry.question (
    instance_id text NOT NULL,
    database text,
    partition text,
    category text,
    high_level boolean,
    question text,
    public_fields jsonb,
    PRIMARY KEY (instance_id)
);

CREATE TABLE IF NOT EXISTS telemetry.deployment (
    deployment_id text NOT NULL,
    database text NOT NULL,
    connection_id text,
    branch_id text,
    branch_name text,
    file_count int,
    failure_stage text,
    failure_detail text,
    file_sha256 jsonb,
    PRIMARY KEY (deployment_id, database)
);

CREATE TABLE IF NOT EXISTS telemetry.attempt (
    attempt_id text NOT NULL,
    generation_record_sha256 text NOT NULL,
    run_id text,
    instance_id text,
    database text,
    condition text,
    arm text,
    repetition int,
    partition text,
    started_at timestamptz,
    finished_at timestamptz,
    latency_ms float8,
    model_name text,
    model_provider text,
    input_tokens bigint,
    output_tokens bigint,
    total_tokens bigint,
    token_source text,
    cost_usd numeric,
    cost_source text,
    cost_unavailable_reason text,
    generation_outcome text,
    execution_status text,
    failure_origin text,
    terminal_failure_class text,
    harness_failure text,
    generated_sql text,
    generated_query text,
    query_unavailable_reason text,
    tool_call_count int,
    tool_calls_by_name jsonb,
    database_query_count int,
    retry_count int,
    validation_attempt_count int,
    actual_result_status text,
    actual_result_hash text,
    trace_captured boolean,
    trace_truncated boolean,
    trace_degraded_reason text,
    telemetry_unavailable jsonb,
    artifact_dir text,
    generation_record jsonb,
    PRIMARY KEY (attempt_id, generation_record_sha256)
);

CREATE TABLE IF NOT EXISTS telemetry.score (
    attempt_id text NOT NULL,
    generation_record_sha256 text NOT NULL,
    scorer text NOT NULL,
    scorer_version text,
    outcome text,
    status text,
    failure_category text,
    score_artifact_sha256 text,
    PRIMARY KEY (attempt_id, generation_record_sha256, scorer)
);

CREATE TABLE IF NOT EXISTS telemetry.trace_event (
    attempt_id text NOT NULL,
    generation_record_sha256 text NOT NULL,
    seq int NOT NULL,
    timestamp timestamptz,
    component text,
    event_type text,
    tool_name text,
    status text,
    failure_class text,
    duration_ms float8,
    elapsed_ms float8,
    input_tokens bigint,
    output_tokens bigint,
    model text,
    provider text,
    retry_delta int,
    tool_call_delta int,
    database_query_delta int,
    validation_attempt_delta int,
    metadata_sha256 text,
    PRIMARY KEY (attempt_id, generation_record_sha256, seq)
);

CREATE TABLE IF NOT EXISTS telemetry.action_evidence (
    attempt_id text NOT NULL,
    generation_record_sha256 text NOT NULL,
    trace_seq int NOT NULL,
    tool_name text,
    retrieval_query text,
    retrieved_public_ids jsonb,
    exploratory_sql text,
    PRIMARY KEY (attempt_id, generation_record_sha256, trace_seq)
);

CREATE TABLE IF NOT EXISTS telemetry.sealed_aggregate (
    run_id text NOT NULL,
    scorer text NOT NULL,
    condition text NOT NULL,
    report jsonb,
    correct int,
    wrong_answer int,
    refused_or_error int,
    mean_accuracy numeric,
    pass_3_rate numeric,
    wrong_rate numeric,
    refused_or_error_rate numeric,
    error_rate numeric,
    correctness_flip_rate numeric,
    scoreable_attempts int,
    PRIMARY KEY (run_id, scorer, condition)
);

CREATE TABLE IF NOT EXISTS telemetry.attempt_label (
    label_id text NOT NULL,
    attempt_id text,
    generation_record_sha256 text,
    taxonomy_version text,
    category text,
    labeler text,
    rationale text,
    created_at timestamptz,
    pass_id text,
    PRIMARY KEY (label_id)
);

CREATE INDEX IF NOT EXISTS attempt_run_id_idx
    ON telemetry.attempt (run_id);
CREATE INDEX IF NOT EXISTS attempt_instance_id_idx
    ON telemetry.attempt (instance_id);
CREATE INDEX IF NOT EXISTS attempt_condition_arm_idx
    ON telemetry.attempt (condition, arm);
CREATE INDEX IF NOT EXISTS score_scorer_outcome_idx
    ON telemetry.score (scorer, outcome);
CREATE INDEX IF NOT EXISTS trace_event_attempt_id_idx
    ON telemetry.trace_event (attempt_id);
CREATE INDEX IF NOT EXISTS attempt_label_attempt_id_idx
    ON telemetry.attempt_label (attempt_id);

CREATE OR REPLACE VIEW telemetry.attempt_label_latest AS
SELECT DISTINCT ON (attempt_id, generation_record_sha256, labeler, taxonomy_version)
    label_id,
    attempt_id,
    generation_record_sha256,
    taxonomy_version,
    category,
    labeler,
    rationale,
    created_at,
    pass_id
FROM telemetry.attempt_label
ORDER BY
    attempt_id,
    generation_record_sha256,
    labeler,
    taxonomy_version,
    created_at DESC,
    label_id DESC;

CREATE OR REPLACE VIEW telemetry.attempt_scored AS
SELECT
    attempt.*,
    official.scorer_version AS official_scorer_version,
    official.outcome AS official_outcome,
    official.status AS official_status,
    official.failure_category AS official_failure_category,
    sensitivity.scorer_version AS sensitivity_scorer_version,
    sensitivity.outcome AS sensitivity_outcome,
    sensitivity.status AS sensitivity_status,
    sensitivity.failure_category AS sensitivity_failure_category,
    run.cohort_id AS run_cohort_id,
    run.scope AS run_scope,
    run.model_version AS run_model_version,
    run.system_commit AS run_system_commit,
    run.semantic_model_ref AS run_semantic_model_ref,
    run.semantic_model_sha256 AS run_semantic_model_sha256
FROM telemetry.attempt AS attempt
LEFT JOIN telemetry.score AS official
    ON official.attempt_id = attempt.attempt_id
    AND official.generation_record_sha256 = attempt.generation_record_sha256
    AND official.scorer = 'official_soft_ex'
LEFT JOIN telemetry.score AS sensitivity
    ON sensitivity.attempt_id = attempt.attempt_id
    AND sensitivity.generation_record_sha256 = attempt.generation_record_sha256
    AND sensitivity.scorer = 'sensitivity'
LEFT JOIN telemetry.run AS run
    ON run.run_id = attempt.run_id;

-- Matched dev-A comparison frame. A question belongs to a scorer's frame when
-- that scorer returned a verdict for it in every one of the five compared arms
-- (C1-C5). Accuracy compared across arms must be read on this frame; per-arm
-- denominators differ because the arms did not all run the same questions and
-- because 18 questions are unscorable from a gold-side benchmark defect.
CREATE OR REPLACE VIEW telemetry.dev_a_frame AS
WITH scored AS (
    SELECT attempt.instance_id, attempt.arm, score.scorer, score.outcome
    FROM telemetry.attempt AS attempt
    JOIN telemetry.score AS score
        ON score.attempt_id = attempt.attempt_id
        AND score.generation_record_sha256 = attempt.generation_record_sha256
    WHERE attempt.partition = 'dev-a'
        AND attempt.arm IN ('C1', 'C2', 'C3', 'C4', 'C5')
)
SELECT
    instance_id,
    count(DISTINCT arm) FILTER (
        WHERE scorer = 'official_soft_ex' AND outcome IS NOT NULL
    ) = 5 AS in_official_frame,
    count(DISTINCT arm) FILTER (
        WHERE scorer = 'sensitivity' AND outcome IS NOT NULL
    ) = 5 AS in_sensitivity_frame
FROM scored
GROUP BY instance_id;
