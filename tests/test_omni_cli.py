from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pytest

from omni_benchmark.omni_cli import (
    OmniCliClient,
    OmniCliError,
    OmniCliSettings,
)


@dataclass(frozen=True)
class Invocation:
    arguments: tuple[str, ...]
    environment: Mapping[str, str]
    stdin: str | None
    timeout_seconds: float


class FakeRunner:
    def __init__(
        self, *, returncode: int = 0, stdout: str = "{}", stderr: str = ""
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.invocations: list[Invocation] = []

    def __call__(
        self,
        arguments: Sequence[str],
        environment: Mapping[str, str],
        stdin: str | None,
        timeout_seconds: float,
    ) -> tuple[int, str, str]:
        self.invocations.append(
            Invocation(tuple(arguments), dict(environment), stdin, timeout_seconds)
        )
        return self.returncode, self.stdout, self.stderr


class ScriptedRunner:
    def __init__(self, responses: list[tuple[int, str, str]]) -> None:
        self.responses = iter(responses)
        self.invocations: list[Invocation] = []

    def __call__(
        self,
        arguments: Sequence[str],
        environment: Mapping[str, str],
        stdin: str | None,
        timeout_seconds: float,
    ) -> tuple[int, str, str]:
        self.invocations.append(
            Invocation(tuple(arguments), dict(environment), stdin, timeout_seconds)
        )
        return next(self.responses)


def _token_environment() -> dict[str, str]:
    return {
        "OMNI_API_TOKEN": "super-secret-token",
        "OMNI_BASE_URL": "https://acme.omniapp.co",
        "OMNI_MODEL_ID": "770e8400-e29b-41d4-a716-446655440002",
    }


def test_settings_reject_url_credentials_and_non_origin_urls() -> None:
    for base_url in (
        "https://user:secret@acme.omniapp.co",
        "https://acme.omniapp.co/path",
        "https://acme.omniapp.co?token=secret",
    ):
        with pytest.raises(OmniCliError, match="origin without credentials"):
            OmniCliSettings.from_environment(
                {**_token_environment(), "OMNI_BASE_URL": base_url}
            )


def test_settings_require_connection_model_and_authentication() -> None:
    with pytest.raises(OmniCliError, match="OMNI_BASE_URL"):
        OmniCliSettings.from_environment({})

    with pytest.raises(OmniCliError, match="OMNI_MODEL_ID"):
        OmniCliSettings.from_environment(
            {"OMNI_BASE_URL": "https://acme.omniapp.co", "OMNI_PROFILE": "benchmark"}
        )

    with pytest.raises(OmniCliError, match="OMNI_PROFILE or OMNI_API_TOKEN"):
        OmniCliSettings.from_environment(
            {
                "OMNI_BASE_URL": "https://acme.omniapp.co",
                "OMNI_MODEL_ID": "model-id",
            }
        )


def test_profile_authentication_does_not_require_a_token() -> None:
    settings = OmniCliSettings.from_environment(
        {
            "OMNI_BASE_URL": "https://acme.omniapp.co",
            "OMNI_MODEL_ID": "model-id",
            "OMNI_PROFILE": "benchmark",
        }
    )

    assert settings.authentication_mode == "profile"
    assert settings.profile == "benchmark"


def test_explicit_profile_settings_defer_origin_to_the_cli_profile() -> None:
    settings = OmniCliSettings.from_profile(
        profile="benchmark",
        model_id="model-id",
        branch_id="branch-id",
    )
    runner = FakeRunner(stdout=json.dumps({"user": {"id": "user-id"}}))
    client = OmniCliClient(settings, runner=runner, environment={})

    client.whoami()

    assert runner.invocations[0].arguments == (
        "omni",
        "--compact",
        "--profile",
        "benchmark",
        "whoami",
        "whoami",
    )


@pytest.mark.parametrize("profile", ["", " "])
def test_explicit_profile_settings_reject_empty_profile(profile: str) -> None:
    with pytest.raises(OmniCliError, match="profile"):
        OmniCliSettings.from_profile(
            profile=profile,
            model_id="model-id",
            branch_id="branch-id",
        )


def test_token_authentication_never_places_secret_in_arguments_or_settings() -> None:
    environment = _token_environment()
    runner = FakeRunner(stdout=json.dumps({"user": {"id": "user-id"}}))
    settings = OmniCliSettings.from_environment(environment)
    client = OmniCliClient(settings, runner=runner, environment=environment)

    response = client.whoami()

    invocation = runner.invocations[0]
    assert response == {"user": {"id": "user-id"}}
    assert "super-secret-token" not in invocation.arguments
    assert invocation.environment["OMNI_API_TOKEN"] == "super-secret-token"
    assert "super-secret-token" not in repr(settings)
    assert "--token" not in invocation.arguments


def test_whoami_retries_http_429_with_bounded_observer_telemetry() -> None:
    environment = _token_environment()
    runner = ScriptedRunner(
        [
            (1, "", '{"error":"throttled","status":429}'),
            (1, "", "request failed with status code 429"),
            (0, json.dumps({"user": {"id": "user-id"}}), ""),
        ]
    )
    waits: list[float] = []
    client = OmniCliClient(
        OmniCliSettings.from_environment(environment),
        runner=runner,
        environment=environment,
        observer_retry_schedule_seconds=(0.25, 0.5),
        sleep=waits.append,
    )

    assert client.whoami() == {"user": {"id": "user-id"}}
    assert len(runner.invocations) == 3
    assert waits == [0.25, 0.5]
    assert client.observer_retry_telemetry() == {
        "observer_retry_count": 2,
        "observer_retry_wait_ms": 750.0,
    }


def test_job_status_retries_http_429_but_result_fetch_remains_single_shot() -> None:
    environment = _token_environment()
    runner = ScriptedRunner(
        [
            (1, "", "request failed with status 429"),
            (0, json.dumps({"state": "COMPLETE"}), ""),
        ]
    )
    waits: list[float] = []
    client = OmniCliClient(
        OmniCliSettings.from_environment(environment),
        runner=runner,
        environment=environment,
        observer_retry_schedule_seconds=(1.0,),
        sleep=waits.append,
    )

    assert client.job_status("job-id") == {"state": "COMPLETE"}
    assert waits == [1.0]
    assert client.observer_retry_telemetry() == {
        "observer_retry_count": 1,
        "observer_retry_wait_ms": 1000.0,
    }


def test_observer_http_429_exhaustion_fails_closed_at_exact_bound() -> None:
    environment = _token_environment()
    runner = ScriptedRunner([(1, "", "HTTP 429") for _ in range(3)])
    waits: list[float] = []
    client = OmniCliClient(
        OmniCliSettings.from_environment(environment),
        runner=runner,
        environment=environment,
        observer_retry_schedule_seconds=(0.25, 0.5),
        sleep=waits.append,
    )

    with pytest.raises(OmniCliError, match="429.*exhausted after 2 retries and 750 ms"):
        client.whoami()

    assert len(runner.invocations) == 3
    assert waits == [0.25, 0.5]
    assert client.observer_retry_telemetry() == {
        "observer_retry_count": 2,
        "observer_retry_wait_ms": 750.0,
    }


def test_non_429_observer_failure_is_not_retried() -> None:
    environment = _token_environment()
    runner = FakeRunner(returncode=1, stderr="request failed with HTTP 503")
    waits: list[float] = []
    client = OmniCliClient(
        OmniCliSettings.from_environment(environment),
        runner=runner,
        environment=environment,
        observer_retry_schedule_seconds=(0.25, 0.5),
        sleep=waits.append,
    )

    with pytest.raises(OmniCliError, match="503"):
        client.job_status("job-id")

    assert len(runner.invocations) == 1
    assert waits == []
    assert client.observer_retry_telemetry() == {
        "observer_retry_count": 0,
        "observer_retry_wait_ms": 0.0,
    }


@pytest.mark.parametrize(
    "operation",
    [
        lambda client: client.list_models(),
        lambda client: client.read_semantic_model(),
        lambda client: client.submit_job("Public benchmark question"),
        lambda client: client.job_result("job-id"),
        lambda client: client.plan_query({"fields": ["answers.value"]}),
        lambda client: client.run_query_json({"fields": ["answers.value"]}),
    ],
)
def test_operations_outside_observer_allowlist_remain_single_shot(operation) -> None:
    environment = _token_environment()
    runner = FakeRunner(returncode=1, stderr="request failed with HTTP 429")
    waits: list[float] = []
    client = OmniCliClient(
        OmniCliSettings.from_environment(environment),
        runner=runner,
        environment=environment,
        observer_retry_schedule_seconds=(0.25, 0.5),
        sleep=waits.append,
    )

    with pytest.raises(OmniCliError, match="429"):
        operation(client)

    assert len(runner.invocations) == 1
    assert waits == []


def test_profile_is_passed_without_mutating_global_cli_configuration() -> None:
    environment = {
        "OMNI_BASE_URL": "https://acme.omniapp.co",
        "OMNI_MODEL_ID": "model-id",
        "OMNI_PROFILE": "benchmark",
    }
    runner = FakeRunner(stdout=json.dumps({"records": []}))
    client = OmniCliClient(
        OmniCliSettings.from_environment(environment),
        runner=runner,
        environment=environment,
    )

    client.list_models()

    arguments = runner.invocations[0].arguments
    assert arguments == (
        "omni",
        "--compact",
        "--base-url",
        "https://acme.omniapp.co",
        "--profile",
        "benchmark",
        "models",
        "list",
        "--modelkind",
        "SHARED",
    )


def test_semantic_model_readback_uses_exact_model_branch_and_extension_mode() -> None:
    environment = {
        **_token_environment(),
        "OMNI_BRANCH_ID": "branch-id",
    }
    runner = FakeRunner(
        stdout=json.dumps({"files": {"orders.view": "label: Orders\n"}})
    )
    client = OmniCliClient(
        OmniCliSettings.from_environment(environment),
        runner=runner,
        environment=environment,
    )

    files = client.read_semantic_model()

    assert files == {"orders.view": "label: Orders\n"}
    assert runner.invocations[0].arguments[-7:] == (
        "models",
        "yaml-get",
        environment["OMNI_MODEL_ID"],
        "--branchid",
        "branch-id",
        "--mode",
        "extension",
    )


def test_semantic_model_readback_rejects_malformed_files() -> None:
    environment = _token_environment()
    client = OmniCliClient(
        OmniCliSettings.from_environment(environment),
        runner=FakeRunner(stdout=json.dumps({"files": {"orders.view": 7}})),
        environment=environment,
    )

    with pytest.raises(OmniCliError, match="readback files"):
        client.read_semantic_model()


def test_cli_errors_redact_exact_secret_values() -> None:
    environment = _token_environment()
    runner = FakeRunner(
        returncode=1,
        stderr="request failed with credential super-secret-token",
    )
    client = OmniCliClient(
        OmniCliSettings.from_environment(environment),
        runner=runner,
        environment=environment,
    )

    with pytest.raises(OmniCliError) as captured:
        client.whoami()

    assert "super-secret-token" not in str(captured.value)
    assert "[REDACTED]" in str(captured.value)


def test_cli_forwards_only_required_environment_and_redacts_other_secrets() -> None:
    environment = {
        **_token_environment(),
        "AWS_SECRET_ACCESS_KEY": "unrelated-cloud-secret",
        "PATH": "/usr/bin",
        "PGPASSWORD": "database-secret",
    }
    runner = FakeRunner(
        returncode=1,
        stderr="unrelated-cloud-secret and database-secret must not escape",
    )
    client = OmniCliClient(
        OmniCliSettings.from_environment(environment),
        runner=runner,
        environment=environment,
    )

    with pytest.raises(OmniCliError) as captured:
        client.whoami()

    forwarded = runner.invocations[0].environment
    assert set(forwarded) == {"OMNI_API_TOKEN", "PATH"}
    assert "unrelated-cloud-secret" not in str(captured.value)
    assert "database-secret" not in str(captured.value)


def test_cli_redacts_forwarded_proxy_credentials_from_errors() -> None:
    proxy = "http://benchmark:live-password@proxy.example:8080"
    environment = {**_token_environment(), "HTTPS_PROXY": proxy}
    runner = FakeRunner(returncode=1, stderr=f"proxy failed: {proxy}")
    client = OmniCliClient(
        OmniCliSettings.from_environment(environment),
        runner=runner,
        environment=environment,
    )

    with pytest.raises(OmniCliError) as captured:
        client.whoami()

    assert runner.invocations[0].environment["HTTPS_PROXY"] == proxy
    assert proxy not in str(captured.value)


def test_cli_redacts_forwarded_proxy_password_component_from_errors() -> None:
    proxy = "https://proxy-user:proxy%2Fpassword@proxy.example"
    environment = {**_token_environment(), "HTTPS_PROXY": proxy}
    runner = FakeRunner(
        returncode=1,
        stderr="proxy rejected proxy-user proxy/password proxy%2Fpassword",
    )
    client = OmniCliClient(
        OmniCliSettings.from_environment(environment),
        runner=runner,
        environment=environment,
    )

    with pytest.raises(OmniCliError) as captured:
        client.whoami()

    detail = str(captured.value)
    assert "proxy-user" not in detail
    assert "proxy/password" not in detail
    assert "proxy%2Fpassword" not in detail


def test_cli_rejects_non_json_success_output() -> None:
    environment = _token_environment()
    client = OmniCliClient(
        OmniCliSettings.from_environment(environment),
        runner=FakeRunner(stdout="not-json"),
        environment=environment,
    )

    with pytest.raises(OmniCliError, match="valid JSON"):
        client.whoami()


def test_job_submission_uses_json_stdin_not_command_arguments() -> None:
    environment = {**_token_environment(), "OMNI_BRANCH_ID": "branch-id"}
    runner = FakeRunner(stdout=json.dumps({"id": "job-id"}))
    client = OmniCliClient(
        OmniCliSettings.from_environment(environment),
        runner=runner,
        environment=environment,
    )
    question = "Revenue by month; do not treat punctuation as a shell command"

    client.submit_job(question)

    arguments = runner.invocations[0].arguments
    assert arguments[-4:] == (
        "ai",
        "job-submit",
        "--body",
        "-",
    )
    assert question not in arguments
    assert json.loads(runner.invocations[0].stdin or "") == {
        "branchId": "branch-id",
        "modelId": "770e8400-e29b-41d4-a716-446655440002",
        "progressWebhookEnabled": False,
        "prompt": question,
    }


def test_job_submission_rejects_question_containing_live_credential() -> None:
    environment = _token_environment()
    runner = FakeRunner(stdout=json.dumps({"id": "job-id"}))
    client = OmniCliClient(
        OmniCliSettings.from_environment(environment),
        runner=runner,
        environment=environment,
    )

    with pytest.raises(OmniCliError, match="question contains"):
        client.submit_job("Public-looking prompt with super-secret-token")

    assert runner.invocations == []


def test_successful_provider_payload_is_not_rewritten() -> None:
    environment = _token_environment()
    payload = {
        "sql": "SELECT * FROM config WHERE api_key='fixture-value'",
        "rows": [["fixture-value"]],
    }
    client = OmniCliClient(
        OmniCliSettings.from_environment(environment),
        runner=FakeRunner(stdout=json.dumps(payload)),
        environment=environment,
    )

    assert client.job_result("job-id") == payload


def test_typed_query_rerun_uses_uncached_raw_json_and_preserves_types() -> None:
    environment = {**_token_environment(), "OMNI_BRANCH_ID": "branch-id"}
    typed_rows = [
        {
            "answer": 42,
            "enabled": True,
            "note": None,
            "reported_on": "2026-08-27",
            "metadata": {"items": [1, None]},
        }
    ]
    runner = FakeRunner(stdout=json.dumps(typed_rows))
    client = OmniCliClient(
        OmniCliSettings.from_environment(environment),
        runner=runner,
        environment=environment,
    )

    result = client.run_query_json({"fields": ["answers.value"], "table": "answers"})

    invocation = runner.invocations[0]
    assert invocation.arguments[-4:] == ("query", "run", "--body", "-")
    assert json.loads(invocation.stdin or "") == {
        "branchId": "branch-id",
        "cache": "SkipCache",
        "formatResults": False,
        "query": {
            "fields": ["answers.value"],
            "modelId": "770e8400-e29b-41d4-a716-446655440002",
            "table": "answers",
        },
        "resultType": "json",
    }
    assert result == typed_rows
    assert result[0]["answer"] == 42
    assert result[0]["enabled"] is True
    assert result[0]["note"] is None
    # JSON has no date scalar; preserve the provider string without guessing a type.
    assert result[0]["reported_on"] == "2026-08-27"


def test_query_plan_uses_plan_only_ndjson_and_returns_one_planned_job() -> None:
    environment = {**_token_environment(), "OMNI_BRANCH_ID": "branch-id"}
    plan = {
        "job_id": "job-1",
        "query": {"model_job": {"fields": ["answers.value"]}},
        "status": "PLANNED",
        "summary": {
            "fields": {"answers.value": {"data_type": "NUMBER"}},
            "invalid_calculations": {},
            "missing_fields": [],
        },
    }
    runner = FakeRunner(
        stdout="\n".join(
            json.dumps(value)
            for value in (
                {"jobs_submitted": {"job-1": "result-1"}},
                plan,
                {"remaining_job_ids": [], "timed_out": "false"},
            )
        )
    )
    client = OmniCliClient(
        OmniCliSettings.from_environment(environment),
        runner=runner,
        environment=environment,
    )

    result = client.plan_query({"fields": ["answers.value"], "table": "answers"})

    invocation = runner.invocations[0]
    assert result == plan
    assert invocation.arguments[-4:] == ("query", "run", "--body", "-")
    assert json.loads(invocation.stdin or "") == {
        "branchId": "branch-id",
        "cache": "SkipRequery",
        "planOnly": True,
        "query": {
            "fields": ["answers.value"],
            "modelId": "770e8400-e29b-41d4-a716-446655440002",
            "table": "answers",
        },
    }


@pytest.mark.parametrize(
    "stdout",
    [
        '{"jobs_submitted":{"job-1":null}}\n'
        '{"job_id":"job-1","status":"COMPLETE"}\n'
        '{"remaining_job_ids":[],"timed_out":"false"}',
        '{"jobs_submitted":{"job-1":null}}\n'
        '{"job_id":"job-1","status":"PLANNED"}\n'
        '{"remaining_job_ids":["job-1"],"timed_out":"true"}',
        '{"jobs_submitted":{"job-1":null}}\nnot-json\n'
        '{"remaining_job_ids":[],"timed_out":"false"}',
    ],
)
def test_query_plan_rejects_non_planned_pending_or_malformed_stream(
    stdout: str,
) -> None:
    environment = _token_environment()
    client = OmniCliClient(
        OmniCliSettings.from_environment(environment),
        runner=FakeRunner(stdout=stdout),
        environment=environment,
    )

    with pytest.raises(OmniCliError):
        client.plan_query({"fields": ["answers.value"]})


def test_typed_query_rerun_rejects_model_mismatch_or_non_row_array() -> None:
    environment = _token_environment()
    runner = FakeRunner(stdout='{"answer":42}')
    client = OmniCliClient(
        OmniCliSettings.from_environment(environment),
        runner=runner,
        environment=environment,
    )

    with pytest.raises(OmniCliError, match="modelId"):
        client.run_query_json(
            {"modelId": "different-model", "fields": ["answers.value"]}
        )
    with pytest.raises(OmniCliError, match="array of row objects"):
        client.run_query_json({"fields": ["answers.value"]})

    assert len(runner.invocations) == 1


def test_status_and_result_commands_are_read_only_json_calls() -> None:
    environment = _token_environment()
    runner = FakeRunner(stdout=json.dumps({"state": "COMPLETE"}))
    client = OmniCliClient(
        OmniCliSettings.from_environment(environment),
        runner=runner,
        environment=environment,
    )

    client.job_status("job-id")
    client.job_result("job-id")

    commands = [invocation.arguments[-3:] for invocation in runner.invocations]
    assert commands == [
        ("ai", "job-status", "job-id"),
        ("ai", "job-result", "job-id"),
    ]


@pytest.mark.parametrize("method_name", ["job_status", "job_result"])
def test_job_identifier_cannot_inject_cli_options(method_name: str) -> None:
    environment = _token_environment()
    runner = FakeRunner(stdout=json.dumps({"state": "COMPLETE"}))
    client = OmniCliClient(
        OmniCliSettings.from_environment(environment),
        runner=runner,
        environment=environment,
    )

    with pytest.raises(OmniCliError, match="job_id must be a bounded identifier"):
        getattr(client, method_name)("--help")

    assert runner.invocations == []


def test_credit_usage_reads_named_memberships_over_json_stdin() -> None:
    environment = _token_environment()
    payload = {
        "periodEnd": 1788220800000,
        "periodStart": 1785542400000,
        "users": [
            {
                "creditsUsed": 635.297481375,
                "userId": "595a871e-e5a9-46b7-a208-f8920da67263",
            }
        ],
    }
    runner = FakeRunner(stdout=json.dumps(payload))
    client = OmniCliClient(
        OmniCliSettings.from_environment(environment),
        runner=runner,
        environment=environment,
    )

    assert client.credit_usage(["595a871e-e5a9-46b7-a208-f8920da67263"]) == payload

    invocation = runner.invocations[0]
    assert invocation.arguments[-4:] == (
        "ai",
        "credit-usage-users-read",
        "--body",
        "-",
    )
    assert json.loads(invocation.stdin or "") == {
        "userIds": ["595a871e-e5a9-46b7-a208-f8920da67263"]
    }


def test_credit_usage_retries_a_throttled_read_and_keeps_its_stdin() -> None:
    environment = _token_environment()
    payload = {
        "periodEnd": 1788220800000,
        "periodStart": 1785542400000,
        "users": [
            {"creditsUsed": 1.0, "userId": "595a871e-e5a9-46b7-a208-f8920da67263"}
        ],
    }
    runner = ScriptedRunner(
        [(1, "", "HTTP 429 too many requests"), (0, json.dumps(payload), "")]
    )
    client = OmniCliClient(
        OmniCliSettings.from_environment(environment),
        runner=runner,
        environment=environment,
        observer_retry_schedule_seconds=(0.01,),
        sleep=lambda _: None,
    )

    assert client.credit_usage(["595a871e-e5a9-46b7-a208-f8920da67263"]) == payload

    assert [json.loads(call.stdin or "") for call in runner.invocations] == [
        {"userIds": ["595a871e-e5a9-46b7-a208-f8920da67263"]}
    ] * 2
    assert client.observer_retry_telemetry()["observer_retry_count"] == 1


@pytest.mark.parametrize(
    "user_ids",
    [
        [],
        "595a871e-e5a9-46b7-a208-f8920da67263",
        ["not-a-membership-id"],
        [None],
        ["595A871E-E5A9-46B7-A208-F8920DA67263"],
        [
            "595a871e-e5a9-46b7-a208-f8920da67263",
            "595a871e-e5a9-46b7-a208-f8920da67263",
        ],
    ],
)
def test_credit_usage_refuses_identities_it_cannot_bill(user_ids: object) -> None:
    environment = _token_environment()
    runner = FakeRunner()
    client = OmniCliClient(
        OmniCliSettings.from_environment(environment),
        runner=runner,
        environment=environment,
    )

    with pytest.raises(OmniCliError, match="membership ID"):
        client.credit_usage(user_ids)  # type: ignore[arg-type]

    assert runner.invocations == []
