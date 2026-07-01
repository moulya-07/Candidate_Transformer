"""Skill name canonicalization."""

import re

SKILL_ALIASES: dict[str, str] = {
    "py": "Python",
    "python": "Python",
    "python3": "Python",
    "js": "JavaScript",
    "javascript": "JavaScript",
    "nodejs": "Node.js",
    "node.js": "Node.js",
    "node": "Node.js",
    "reactjs": "React",
    "react": "React",
    "docker": "Docker",
}


def normalize_skill(skill: str | None) -> str:
    """Normalize a single skill name to its canonical form.

    Known aliases are mapped case-insensitively. Unknown skills are trimmed
    and returned with collapsed whitespace. Empty input returns an empty string.
    Never raises.
    """
    if skill is None:
        return ""

    cleaned = re.sub(r"\s+", " ", skill.strip())
    if not cleaned:
        return ""

    canonical = SKILL_ALIASES.get(cleaned.lower())
    if canonical is not None:
        return canonical

    return cleaned


def normalize_skill_list(skills: list[str]) -> list[str]:
    """Normalize a list of skills and remove empty or duplicate entries.

    Duplicates are compared case-insensitively after normalization.
    Never raises.
    """
    normalized: list[str] = []
    seen: set[str] = set()

    for skill in skills:
        value = normalize_skill(skill)
        if not value:
            continue

        key = value.casefold()
        if key in seen:
            continue

        seen.add(key)
        normalized.append(value)

    return normalized
