"""Integration tests for the candidate transformation pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.main import Pipeline, PipelineError, load_runtime_config
from src.parsers.github import GitHubProfileParser
from src.parsers.recruiter_csv import RecruiterCsvParser
from src.validator.validator import OutputValidationError


@pytest.fixture
def pipeline() -> Pipeline:
    return Pipeline()


def _write_csv(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def _write_config(path: Path, **overrides: object) -> Path:
    config: dict[str, object] = {
        "fields": [
            {"path": "full_name", "type": "string", "required": True},
            {
                "path": "emails",
                "type": "array",
                "item_type": "string",
                "required": False,
            },
            {"path": "headline", "type": "string", "required": False},
            {
                "path": "skills",
                "type": "array",
                "item_type": "string",
                "required": False,
            },
        ],
        "include_confidence": True,
        "include_provenance": False,
        "on_missing": "null",
        "allow_extra": False,
    }
    config.update(overrides)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return path


def _github_payload(**overrides: object) -> dict[str, object]:
    payload = {
        "login": "octocat",
        "name": "The Octocat",
        "email": "octocat@github.com",
        "bio": "GitHub mascot",
        "blog": "https://octocat.blog",
        "html_url": "https://github.com/octocat",
        "location": "San Francisco",
        "company": "GitHub",
    }
    payload.update(overrides)
    return payload


def _write_github_json(path: Path, **profile_overrides: object) -> Path:
    path.write_text(
        json.dumps(
            {
                "profile": _github_payload(**profile_overrides),
                "repos": [{"language": "Python"}, {"language": "Go"}],
            }
        ),
        encoding="utf-8",
    )
    return path


def _mock_github_response(status_code: int, json_data: object) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data
    return response


class TestCsvOnly:
    def test_csv_only_pipeline(self, pipeline: Pipeline, tmp_path: Path) -> None:
        csv_path = _write_csv(
            tmp_path / "candidates.csv",
            "name,email,phone,current_company,title,location\n"
            "Jane Doe,jane@example.com,+1 555 0100,Acme Corp,Engineer,San Francisco\n",
        )
        config_path = _write_config(tmp_path / "config.json")
        output_path = tmp_path / "output" / "result.json"

        result = pipeline.run(
            csv_path=csv_path,
            config_path=config_path,
            output_path=output_path,
        )

        assert result.output_path == output_path
        assert result.output["full_name"] == "Jane Doe"
        assert result.output["emails"] == ["jane@example.com"]
        assert result.output["headline"] == "Engineer at Acme Corp"
        assert "overall_confidence" in result.output
        assert output_path.exists()


class TestGitHubOnly:
    def test_github_json_only_pipeline(
        self, pipeline: Pipeline, tmp_path: Path
    ) -> None:
        github_json = _write_github_json(tmp_path / "github.json")
        config_path = _write_config(tmp_path / "config.json")
        output_path = tmp_path / "result.json"

        result = pipeline.run(
            github_json_path=github_json,
            config_path=config_path,
            output_path=output_path,
        )

        assert result.output["full_name"] == "The Octocat"
        assert result.output["emails"] == ["octocat@github.com"]
        assert result.output["skills"] == ["Python", "Go"]
        assert output_path.read_text(encoding="utf-8").startswith("{\n")

    def test_github_username_pipeline(
        self, pipeline: Pipeline, tmp_path: Path
    ) -> None:
        config_path = _write_config(tmp_path / "config.json")
        output_path = tmp_path / "result.json"
        github_parser = GitHubProfileParser(session=requests.Session())
        pipeline = Pipeline(github_parser=github_parser)

        profile = _github_payload()
        repos = [{"language": "Rust"}]

        with patch.object(
            github_parser._session,
            "get",
            side_effect=[
                _mock_github_response(200, profile),
                _mock_github_response(200, repos),
            ],
        ):
            result = pipeline.run(
                github_username="octocat",
                config_path=config_path,
                output_path=output_path,
            )

        assert result.output["full_name"] == "The Octocat"
        assert result.output["skills"] == ["Rust"]


class TestCsvAndGitHub:
    def test_csv_and_github_merge(
        self, pipeline: Pipeline, tmp_path: Path
    ) -> None:
        csv_path = _write_csv(
            tmp_path / "candidates.csv",
            "name,email,phone,current_company,title,location\n"
            "Jane Doe,jane@example.com,,Acme Corp,Engineer,San Francisco\n",
        )
        github_json = _write_github_json(
            tmp_path / "github.json",
            name="The Octocat",
            email="octocat@github.com",
        )
        config_path = _write_config(tmp_path / "config.json")
        output_path = tmp_path / "result.json"

        result = pipeline.run(
            csv_path=csv_path,
            github_json_path=github_json,
            config_path=config_path,
            output_path=output_path,
        )

        assert result.output["full_name"] == "Jane Doe"
        assert "jane@example.com" in result.output["emails"]
        assert "octocat@github.com" in result.output["emails"]
        assert "Python" in result.output["skills"]


class TestNoInput:
    def test_no_input_raises(self, pipeline: Pipeline, tmp_path: Path) -> None:
        config_path = _write_config(tmp_path / "config.json")
        output_path = tmp_path / "result.json"

        with pytest.raises(PipelineError, match="No input sources supplied"):
            pipeline.run(
                config_path=config_path,
                output_path=output_path,
            )


class TestParserFailure:
    def test_csv_failure_github_success(
        self, pipeline: Pipeline, tmp_path: Path
    ) -> None:
        missing_csv = tmp_path / "missing.csv"
        github_json = _write_github_json(tmp_path / "github.json")
        config_path = _write_config(tmp_path / "config.json")
        output_path = tmp_path / "result.json"

        result = pipeline.run(
            csv_path=missing_csv,
            github_json_path=github_json,
            config_path=config_path,
            output_path=output_path,
        )

        assert result.output["full_name"] == "The Octocat"
        assert output_path.exists()

    def test_all_sources_fail(self, pipeline: Pipeline, tmp_path: Path) -> None:
        config_path = _write_config(tmp_path / "config.json")
        output_path = tmp_path / "result.json"

        with pytest.raises(PipelineError, match="All supplied input sources failed"):
            pipeline.run(
                csv_path=tmp_path / "missing.csv",
                github_json_path=tmp_path / "missing.json",
                config_path=config_path,
                output_path=output_path,
            )

    def test_unexpected_parser_exception_is_recovered(
        self, tmp_path: Path
    ) -> None:
        csv_parser = RecruiterCsvParser()
        github_json = _write_github_json(tmp_path / "github.json")
        config_path = _write_config(tmp_path / "config.json")
        output_path = tmp_path / "result.json"
        pipeline = Pipeline(csv_parser=csv_parser)

        with patch.object(
            csv_parser,
            "parse",
            side_effect=RuntimeError("boom"),
        ):
            result = pipeline.run(
                csv_path=tmp_path / "candidates.csv",
                github_json_path=github_json,
                config_path=config_path,
                output_path=output_path,
            )

        assert result.output["full_name"] == "The Octocat"


class TestValidationFailure:
    def test_validation_failure_raises(
        self, pipeline: Pipeline, tmp_path: Path
    ) -> None:
        csv_path = _write_csv(
            tmp_path / "candidates.csv",
            "name,email,phone,current_company,title,location\n"
            "Jane Doe,jane@example.com,,Acme Corp,Engineer,San Francisco\n",
        )
        config_path = _write_config(
            tmp_path / "config.json",
            fields=[
                {"path": "full_name", "type": "number", "required": True},
            ],
        )
        output_path = tmp_path / "result.json"

        with pytest.raises(OutputValidationError) as exc_info:
            pipeline.run(
                csv_path=csv_path,
                config_path=config_path,
                output_path=output_path,
            )

        assert exc_info.value.field == "full_name"
        assert not output_path.exists()


class TestOutputFile:
    def test_output_file_created_with_utf8_pretty_json(
        self, pipeline: Pipeline, tmp_path: Path
    ) -> None:
        csv_path = _write_csv(
            tmp_path / "candidates.csv",
            "name,email,phone,current_company,title,location\n"
            "Renée Müller,renée@example.com,,Acme Corp,Engineer,Zürich\n",
        )
        config_path = _write_config(tmp_path / "config.json")
        output_path = tmp_path / "nested" / "dir" / "result.json"

        pipeline.run(
            csv_path=csv_path,
            config_path=config_path,
            output_path=output_path,
        )

        content = output_path.read_text(encoding="utf-8")
        parsed = json.loads(content)
        assert parsed["full_name"] == "Renée Müller"
        assert content.startswith("{\n")
        assert "Renée Müller" in content


class TestConfigurationLoading:
    def test_load_runtime_config_splits_projection_and_validation(
        self, tmp_path: Path
    ) -> None:
        config_path = _write_config(
            tmp_path / "config.json",
            fields=[
                {
                    "path": "primary_email",
                    "from": "emails[0]",
                    "type": "string",
                    "required": False,
                    "normalize": "email",
                }
            ],
        )

        runtime = load_runtime_config(config_path)

        assert runtime.projection.fields[0].path == "primary_email"
        assert runtime.projection.fields[0].source_path == "emails[0]"
        assert runtime.projection.fields[0].normalize == "email"
        assert runtime.validation.fields[0].type == "string"

    def test_missing_config_raises(self, tmp_path: Path) -> None:
        with pytest.raises(PipelineError, match="Configuration file not found"):
            load_runtime_config(tmp_path / "missing.json")

    def test_invalid_config_json_raises(self, tmp_path: Path) -> None:
        bad_config = tmp_path / "bad.json"
        bad_config.write_text("{not-json", encoding="utf-8")

        with pytest.raises(PipelineError, match="Invalid configuration JSON"):
            load_runtime_config(bad_config)
