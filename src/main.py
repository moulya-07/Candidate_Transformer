"""Pipeline entry point."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.confidence.engine import ConfidenceEngine
from src.merge.engine import MergeEngine
from src.parsers.github import GitHubProfileParser
from src.parsers.recruiter_csv import RecruiterCsvParser
from src.projection.config import OutputConfig, load_config
from src.projection.projector import Projector
from src.validator.output_schema import ValidationConfig
from src.validator.validator import OutputValidationError, OutputValidator

logger = logging.getLogger(__name__)

_PROGRESS_MESSAGES = (
    "Loading configuration...",
    "Running Recruiter parser...",
    "Running GitHub parser...",
    "Merging profiles...",
    "Calculating confidence...",
    "Projecting output...",
    "Validating output...",
    "Writing output...",
    "Done.",
)


class PipelineError(Exception):
    """Raised when the pipeline cannot produce output."""


@dataclass(frozen=True)
class RuntimeConfig:
    """Projection and validation configuration loaded from one runtime file."""

    projection: OutputConfig
    validation: ValidationConfig


@dataclass(frozen=True)
class PipelineResult:
    """Successful pipeline execution result."""

    output: dict[str, Any]
    output_path: Path


class Pipeline:
    """Orchestrate the candidate transformation pipeline end to end."""

    def __init__(
        self,
        *,
        csv_parser: RecruiterCsvParser | None = None,
        github_parser: GitHubProfileParser | None = None,
        merge_engine: MergeEngine | None = None,
        confidence_engine: ConfidenceEngine | None = None,
        projector: Projector | None = None,
        validator: OutputValidator | None = None,
    ) -> None:
        self._csv_parser = csv_parser or RecruiterCsvParser()
        self._github_parser = github_parser or GitHubProfileParser()
        self._merge_engine = merge_engine or MergeEngine()
        self._confidence_engine = confidence_engine or ConfidenceEngine()
        self._projector = projector or Projector()
        self._validator = validator or OutputValidator()

    def run(
        self,
        *,
        config_path: Path,
        output_path: Path,
        csv_path: Path | None = None,
        github_username: str | None = None,
        github_json_path: Path | None = None,
    ) -> PipelineResult:
        """Execute all pipeline stages and write validated JSON output."""
        if not _has_any_source(csv_path, github_username, github_json_path):
            raise PipelineError(
                "No input sources supplied. Provide --csv, --github, or --github-json."
            )

        self._log_progress(_PROGRESS_MESSAGES[0])
        runtime_config = load_runtime_config(config_path)

        profiles: list[Any] = []

        if csv_path is not None:
            self._log_progress(_PROGRESS_MESSAGES[1])
            profiles.extend(self._parse_source("Recruiter CSV", lambda: self._csv_parser.parse(csv_path)))

        if github_json_path is not None or github_username is not None:
            self._log_progress(_PROGRESS_MESSAGES[2])
            if github_json_path is not None:
                profiles.extend(
                    self._parse_source(
                        "GitHub JSON",
                        lambda: self._github_parser.parse(github_json_path),
                    )
                )
            if github_username is not None:
                profiles.extend(
                    self._parse_source(
                        "GitHub API",
                        lambda: self._github_parser.parse(github_username),
                    )
                )

        if not profiles:
            raise PipelineError(
                "All supplied input sources failed to produce a canonical profile."
            )

        self._log_progress(_PROGRESS_MESSAGES[3])
        merged = self._merge_engine.merge_profiles(profiles)

        self._log_progress(_PROGRESS_MESSAGES[4])
        scored = self._confidence_engine.calculate(merged)

        self._log_progress(_PROGRESS_MESSAGES[5])
        projected = self._projector.project(scored, runtime_config.projection)

        self._log_progress(_PROGRESS_MESSAGES[6])
        validated = self._validator.validate(projected, runtime_config.validation)

        self._log_progress(_PROGRESS_MESSAGES[7])
        written_path = write_output_json(validated, output_path)

        self._log_progress(_PROGRESS_MESSAGES[8])
        return PipelineResult(output=validated, output_path=written_path)

    def _parse_source(
        self,
        source_name: str,
        parse_callable: Any,
    ) -> list[Any]:
        try:
            profiles = parse_callable()
        except Exception as exc:
            logger.exception("%s parser failed unexpectedly.", source_name)
            self._log_message(f"{source_name} parser failed: {exc}")
            return []

        if not profiles:
            self._log_message(f"{source_name} parser returned no profiles.")
        return profiles

    @staticmethod
    def _log_progress(message: str) -> None:
        print(message)

    @staticmethod
    def _log_message(message: str) -> None:
        logger.warning(message)
        print(message)


def _has_any_source(
    csv_path: Path | None,
    github_username: str | None,
    github_json_path: Path | None,
) -> bool:
    return any(
        (
            csv_path is not None,
            bool(github_username and github_username.strip()),
            github_json_path is not None,
        )
    )


def _to_projection_field(field: dict[str, Any]) -> dict[str, Any]:
    """Strip validation-only keys so projection config loading succeeds."""
    mapping: dict[str, Any] = {"path": field["path"]}
    if "from" in field:
        mapping["from"] = field["from"]
    elif "source" in field:
        mapping["from"] = field["source"]
    if field.get("normalize") is not None:
        mapping["normalize"] = field["normalize"]
    return mapping


def _to_validation_field(field: dict[str, Any]) -> dict[str, Any]:
    """Build a validation field spec from a unified runtime field definition."""
    mapping: dict[str, Any] = {
        "path": field["path"],
        "type": field["type"],
        "required": field.get("required", True),
    }
    if field.get("normalize") is not None:
        mapping["normalize"] = field["normalize"]
    if field.get("item_type") is not None:
        mapping["item_type"] = field["item_type"]
    return mapping


def load_runtime_config(config_path: Path) -> RuntimeConfig:
    """Load projection and validation configuration from a single runtime file."""
    if not config_path.exists():
        raise PipelineError(f"Configuration file not found: {config_path}")

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PipelineError(f"Invalid configuration JSON in {config_path}: {exc}") from exc
    except OSError as exc:
        raise PipelineError(f"Unable to read configuration file {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise PipelineError("Configuration file must contain a JSON object.")

    validation_only_root_keys = frozenset({"allow_extra"})
    projection_only_root_keys = frozenset({"on_missing"})

    try:
        projection_payload = {
            key: value
            for key, value in raw.items()
            if key not in validation_only_root_keys and key != "fields"
        }
        projection_payload["fields"] = [
            _to_projection_field(field)
            for field in raw.get("fields", [])
        ]
        validation_payload = {
            key: value
            for key, value in raw.items()
            if key not in projection_only_root_keys and key != "fields"
        }
        validation_payload["fields"] = [
            _to_validation_field(field)
            for field in raw.get("fields", [])
        ]
        projection = load_config(projection_payload)
        validation = ValidationConfig.model_validate(validation_payload)
    except Exception as exc:
        raise PipelineError(f"Invalid runtime configuration: {exc}") from exc

    return RuntimeConfig(projection=projection, validation=validation)


def write_output_json(output: dict[str, Any], output_path: Path) -> Path:
    """Write pretty-printed UTF-8 JSON, creating parent directories when needed."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(output, indent=2, ensure_ascii=False)
    output_path.write_text(f"{serialized}\n", encoding="utf-8")
    return output_path


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Transform recruiter and GitHub candidate data into validated JSON output.",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        help="Path to recruiter CSV input file.",
    )
    parser.add_argument(
        "--github",
        help="GitHub username to fetch from the GitHub API.",
    )
    parser.add_argument(
        "--github-json",
        type=Path,
        dest="github_json",
        help="Path to a local GitHub profile JSON file.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to runtime output configuration JSON.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to the output JSON file.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_argument_parser().parse_args(argv)

    pipeline = Pipeline()
    try:
        pipeline.run(
            csv_path=args.csv,
            github_username=args.github,
            github_json_path=args.github_json,
            config_path=args.config,
            output_path=args.output,
        )
    except OutputValidationError as exc:
        logger.error("Output validation failed for field '%s': %s", exc.field, exc)
        print(f"Validation failed: {exc}", file=sys.stderr)
        return 1
    except PipelineError as exc:
        logger.error("Pipeline failed: %s", exc)
        print(f"Pipeline failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        logger.exception("Unexpected pipeline failure.")
        print(f"Unexpected pipeline failure: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
