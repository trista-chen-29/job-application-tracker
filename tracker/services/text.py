from __future__ import annotations

import re

_PUNCT = re.compile(r"[^a-z0-9+#. ]+")
_SPACES = re.compile(r"\s+")

ALIASES = {
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "golang": "go",
    "node": "nodejs",
    "node.js": "nodejs",
    "react.js": "react",
    "c++": "c++",
    "cpp": "c++",
    "c#": "csharp",
    "swe": "software engineer",
}


def normalize_skill(name: str) -> str:
    text = name.lower().strip()
    text = _PUNCT.sub(" ", text)
    text = _SPACES.sub(" ", text).strip()
    return ALIASES.get(text, text)


def tokenize(text: str) -> set[str]:
    return {token for token in normalize_skill(text).split(" ") if len(token) > 1}


def split_skill_lines(raw: str) -> list[str]:
    parts: list[str] = []
    for line in raw.replace(";", "\n").splitlines():
        for chunk in line.split(","):
            value = chunk.strip(" -•\t")
            if value:
                parts.append(value)
    return parts
