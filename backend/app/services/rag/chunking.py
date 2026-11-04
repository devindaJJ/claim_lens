"""Split policy documents into clause-level chunks for retrieval."""

from __future__ import annotations

import re
from dataclasses import dataclass

SECTION_RE = re.compile(r"^SECTION\s+\d+\s*[-–—:]\s*.+$", re.I)
CLAUSE_RE = re.compile(r"^(?P<num>\d+\.\d+)\s+(?P<title>[^.]{2,80})\.")
POLICY_NUMBER_RE = re.compile(r"Policy\s+Number:\s*(?P<v>\S+)", re.I)
TITLE_RE = re.compile(r"^[A-Z][A-Z\s]+POLICY$")


@dataclass(frozen=True)
class Chunk:
    index: int
    section: str  # e.g. "Declarations", "1.1 Collision", "SECTION 2 - EXCLUSIONS"
    group: str  # enclosing section heading
    content: str

    @property
    def embedding_text(self) -> str:
        return f"{self.group}\n{self.content}" if self.group != self.section else self.content


@dataclass(frozen=True)
class ParsedPolicy:
    policy_number: str
    title: str
    chunks: list[Chunk]


class PolicyParseError(ValueError):
    pass


def chunk_policy(text: str) -> ParsedPolicy:
    match = POLICY_NUMBER_RE.search(text)
    if not match:
        raise PolicyParseError("Policy document does not state a policy number")
    policy_number = match.group("v").strip()
    title = next((ln.strip().title() for ln in text.splitlines() if TITLE_RE.match(ln.strip())), policy_number)

    chunks: list[Chunk] = []
    group, section, buffer = "Declarations", "Declarations", []

    def flush() -> None:
        body = " ".join(line.strip() for line in buffer if line.strip())
        if body:
            chunks.append(Chunk(index=len(chunks), section=section, group=group, content=body))
        buffer.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if SECTION_RE.match(line):
            flush()
            group = section = line
            continue
        if clause := CLAUSE_RE.match(line):
            flush()
            section = f"{clause.group('num')} {clause.group('title').strip()}"
        buffer.append(line)
    flush()
    return ParsedPolicy(policy_number=policy_number, title=title, chunks=chunks)
