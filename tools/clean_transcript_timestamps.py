"""Remove YouTube timestamp artifacts from a transcript .md file."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import tools._bootstrap  # noqa: F401

TIMESTAMP = re.compile(
    r"\d{1,2}:\d{2}\d{1,2}\s*(?:minutes?(?:, \d+ seconds?)?|seconds?)",
    re.IGNORECASE,
)


def clean(text: str) -> str:
    text = TIMESTAMP.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()

    breaks = [
        r"(Starting with number one,)",
        r"(brings me my second thing\.)",
        r"(Which brings me to the next point,)",
        r"(So brings me)",
        r"(I'll leave you guys with that\.)",
    ]
    for pattern in breaks:
        text = re.sub(rf" {pattern}", r"\n\n\1", text)

    sentences = re.split(r"(?<=[.!?])\s+", text)
    paragraphs: list[str] = []
    chunk: list[str] = []
    for sentence in sentences:
        chunk.append(sentence)
        if len(chunk) >= 4:
            paragraphs.append(" ".join(chunk))
            chunk = []
    if chunk:
        paragraphs.append(" ".join(chunk))

    return "\n\n".join(paragraphs) + "\n"


if __name__ == "__main__":
    path = Path(sys.argv[1])
    path.write_text(clean(path.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Cleaned: {path}")
