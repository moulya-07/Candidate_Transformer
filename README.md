# Multi-Source Candidate Data Transformer

A backend data transformation pipeline that ingests candidate information from multiple sources, normalizes and merges conflicting values, tracks provenance, calculates confidence, and produces configurable JSON output.

 It is a deterministic, production-oriented data pipeline built with clean architecture and separation of concerns.

## Overview

```
Input Sources
      ↓
Source Parser
      ↓
Canonical Model
      ↓
Normalizer
      ↓
Merge Engine
      ↓
Confidence Engine
      ↓
Projection Layer
      ↓
Schema Validator
      ↓
Output JSON
```

Each stage has a single responsibility. The canonical profile is the internal source of truth and is never modified by output configuration.

## Supported Sources

| Source        | Type          | Status      |
|---------------|---------------|-------------|
| Recruiter CSV | Structured    | Implemented    |
| GitHub Profile| Unstructured  | Implemented   |
| ATS JSON      | Structured    | Future      |
| LinkedIn      | Unstructured  | Future      |
| Resume        | Unstructured  | Future      |
| Recruiter Notes | Unstructured | Future    |

New sources can be added by implementing a parser adapter without changing existing pipeline stages.

## Project Structure

```
candidate-transformer/
├── config/              # Runtime output and pipeline configuration
├── input/               # Sample or local input files (CSV, etc.)
├── output/              # Generated JSON output (gitignored contents)
├── src/
│   ├── models/          # Canonical domain models (Pydantic)
│   ├── parsers/         # Source-specific parsers → partial canonical profiles
│   ├── normalizers/     # Field-level normalization rules
│   ├── merge/           # Deterministic merge engine and policies
│   ├── confidence/      # Per-source and overall confidence scoring
│   ├── projection/      # Canonical → configured output transformation
│   ├── validator/       # Output schema validation
│   ├── utils/           # Shared logging, errors, helpers
│   └── main.py          # Pipeline entry point
└── tests/               # Unit and integration tests
```

## Requirements

- Python 3.11+
- See `requirements.txt` for dependencies

## Installation


git clone <repository-url>
cd candidate-transformer

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```



```bash
python -m src.main --help
```

## Configuration

<!-- TODO: Document output projection config schema -->

Output shape is controlled at runtime via configuration in `config/`. Supported options:

- Field selection
- Field renaming
- Optional provenance inclusion
- Optional confidence inclusion
- Missing field behavior: `null`, `omit`, or `error`

## Merge Policy

Deterministic priority: **Recruiter CSV > GitHub**

| Field            | Rule                          |
|------------------|-------------------------------|
| Full Name        | Prefer recruiter              |
| Emails           | Union + deduplicate           |
| Phones           | Union + deduplicate           |
| Skills           | Union + canonicalize          |
| Experience       | Merge unique records          |
| Education        | Merge unique records          |
| Headline         | Prefer recruiter              |
| Location         | Prefer recruiter              |

## Source Confidence

| Source        | Confidence |
|---------------|------------|
| Recruiter CSV | 0.95       |
| GitHub        | 0.80       |

## Development

```bash
pytest
```

## Design Principles

- Clean architecture with one responsibility per module
- Canonical model independent of output configuration
- Deterministic merge and normalization
- Graceful error handling (log warnings, never crash on bad input)
- Extensible parser interface for new data sources




