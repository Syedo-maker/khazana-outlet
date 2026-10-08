"""Versioned prompt registry.

Prompts live in files under ``ai/prompts``, never as string literals inside
feature code. Three reasons, all of which come up in practice:

1. When an output goes wrong in production you need to know exactly which
   prompt text produced it. ``AiOutput`` stores the name and version, and
   those point at an immutable file.
2. Prompt caching is prefix matched, so the cacheable part has to be a stable,
   byte identical block. A file makes that visible; an f string hides it.
3. A prompt change is a reviewable diff rather than a line buried in a
   service method.

File format, ``<name>.v<version>.md``:

    Everything up to the separator is the cacheable system prefix.
    It must not contain anything that varies between calls: no timestamps,
    no identifiers, no counts.

    ---USER---

    The variable part, with {placeholders} filled per call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

SEPARATOR = "---USER---"
PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"
FILENAME_PATTERN = re.compile(r"^(?P<name>[a-z0-9_]+)\.v(?P<version>\d+)\.md$")


@dataclass(frozen=True, slots=True)
class Prompt:
    name: str
    version: int
    # The stable block that is worth caching. See docs/ai-architecture.md
    # lever 1: cached reads are twenty times cheaper than fresh ones.
    system: str
    user_template: str

    def render(self, **values: object) -> str:
        """Fill the variable part.

        ``str.format`` is deliberate rather than a template engine: a prompt
        should be legible as text, and a prompt that needs loops and
        conditionals is a prompt that should be split into two.
        """
        try:
            return self.user_template.format(**values)
        except KeyError as exc:
            raise KeyError(
                f"Prompt {self.name} v{self.version} needs placeholder {exc} "
                "which was not provided."
            ) from exc


class PromptNotFound(LookupError):
    pass


@lru_cache(maxsize=64)
def load(name: str, version: int | None = None) -> Prompt:
    """Load a prompt, defaulting to the highest version on disk.

    Pinning a version is the right choice for a feature whose eval was run
    against that text. Taking the latest is right while iterating.
    """
    candidates = available(name)
    if not candidates:
        raise PromptNotFound(f"No prompt file for {name!r} in {PROMPT_DIR}. Expected {name}.v1.md")
    chosen = max(candidates) if version is None else version
    if chosen not in candidates:
        raise PromptNotFound(f"Prompt {name} has no version {chosen}. Found {sorted(candidates)}.")

    path = PROMPT_DIR / f"{name}.v{chosen}.md"
    raw = path.read_text(encoding="utf-8")

    if SEPARATOR not in raw:
        raise ValueError(
            f"{path.name} has no {SEPARATOR} line. The cacheable system prefix and "
            "the per call part must be separated so caching works."
        )

    system, user_template = raw.split(SEPARATOR, 1)
    return Prompt(
        name=name,
        version=chosen,
        system=system.strip(),
        user_template=user_template.strip(),
    )


def available(name: str) -> set[int]:
    if not PROMPT_DIR.exists():
        return set()
    versions: set[int] = set()
    for path in PROMPT_DIR.iterdir():
        match = FILENAME_PATTERN.match(path.name)
        if match and match.group("name") == name:
            versions.add(int(match.group("version")))
    return versions


def all_prompts() -> dict[str, set[int]]:
    """Every prompt and its versions. Used by the eval runner and the docs."""
    found: dict[str, set[int]] = {}
    if not PROMPT_DIR.exists():
        return found
    for path in sorted(PROMPT_DIR.iterdir()):
        match = FILENAME_PATTERN.match(path.name)
        if match:
            found.setdefault(match.group("name"), set()).add(int(match.group("version")))
    return found
