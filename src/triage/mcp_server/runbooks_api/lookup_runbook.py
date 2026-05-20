"""runbooks_api_lookup_runbook — surface alarm-specific procedures.

Read-only tool that maps an alarm name to a runbook in `runbooks/<slug>.md`.
The agent calls this as step 0 of every investigation. If a runbook matches,
the agent follows the numbered Steps for the alarm class; if it returns
`found: false`, the agent falls back to general principles in AGENT.md
(per spec §3.11.2, ~3 corpus scenarios ship runbook-less by design).

Lookup key: the `**Alarm trigger:** <name1>, <name2>` field defined by the
`/add-runbook` skill scaffold. Case-sensitive exact match, comma-separated
list supported per the skill spec.

Runbook source dir resolution order:
  1. `TRIAGE_RUNBOOKS_DIR` env var (used by tests + local dev).
  2. `/app/runbooks/` (the container path the Dockerfile COPYs into).
  3. `<repo root>/runbooks/` (resolved by walking up from this file's path).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from triage.mcp_server.server import mcp
from triage.shared.errors import RunbooksApiError
from triage.shared.otel import tool_span

TOOL_ID = "runbooks_api_lookup_runbook"

_SECTION_HEADERS = ("Prerequisites", "Steps", "Rollback", "Escalation")
_ALARM_TRIGGER_PATTERN = re.compile(r"^\*\*Alarm trigger:\*\*\s*(.+?)\s*$", re.MULTILINE)


class RunbookSections(BaseModel):
    prerequisites: str | None = Field(default=None)
    steps: str | None = Field(default=None)
    rollback: str | None = Field(default=None)
    escalation: str | None = Field(default=None)


def _runbooks_dir() -> Path:
    override = os.environ.get("TRIAGE_RUNBOOKS_DIR")
    if override:
        return Path(override)
    container_path = Path("/app/runbooks")
    if container_path.is_dir():
        return container_path
    # Repo root: src/triage/mcp_server/runbooks_api/lookup_runbook.py → ../../../../runbooks
    repo_root = Path(__file__).resolve().parents[4]
    return repo_root / "runbooks"


def _parse_alarm_triggers(text: str) -> list[str]:
    match = _ALARM_TRIGGER_PATTERN.search(text)
    if not match:
        return []
    return [name.strip() for name in match.group(1).split(",") if name.strip()]


def _parse_sections(text: str) -> RunbookSections:
    """Slice the file by H2 headers into named sections.

    The `/add-runbook` skill scaffold pins H2 as the section boundary; the
    parser splits on `^## <Header>$` and stops at the next H2 or EOF.
    """
    sections: dict[str, str] = {}
    h2_positions: list[tuple[int, str]] = []
    for m in re.finditer(r"^##\s+(.+?)\s*$", text, flags=re.MULTILINE):
        h2_positions.append((m.start(), m.group(1).strip()))
    for idx, (start, header) in enumerate(h2_positions):
        end = h2_positions[idx + 1][0] if idx + 1 < len(h2_positions) else len(text)
        body_start = text.find("\n", start) + 1
        sections[header] = text[body_start:end].strip()
    return RunbookSections(
        prerequisites=sections.get("Prerequisites"),
        steps=sections.get("Steps"),
        rollback=sections.get("Rollback"),
        escalation=sections.get("Escalation"),
    )


def _build_index(directory: Path) -> dict[str, Path]:
    """Map each alarm trigger to the runbook file that owns it.

    A single file may declare multiple comma-separated triggers; each lands
    as its own index entry pointing back at the same file.
    """
    if not directory.is_dir():
        return {}
    index: dict[str, Path] = {}
    for md_path in sorted(directory.glob("*.md")):
        text = md_path.read_text(encoding="utf-8")
        for trigger in _parse_alarm_triggers(text):
            if trigger in index and index[trigger] != md_path:
                raise RunbooksApiError(
                    f"Duplicate alarm trigger {trigger!r} in {md_path.name} "
                    f"and {index[trigger].name}",
                    code="DuplicateAlarmTrigger",
                    details={"trigger": trigger},
                )
            index[trigger] = md_path
    return index


@mcp.tool(
    name=TOOL_ID,
    description=(
        "Look up the operational runbook for a CloudWatch alarm by name. "
        "Read-only. Returns the parsed Prerequisites / Steps / Rollback / "
        "Escalation sections if a runbook's `**Alarm trigger:**` field matches "
        "the given alarm name (case-sensitive, exact). If no runbook matches, "
        "returns `found: false` plus the list of available runbook triggers — "
        "the agent should then fall back to general investigation principles "
        "from its system prompt. Call this as step 0 of every alarm "
        "investigation."
    ),
)
def runbooks_api_lookup_runbook(alarm_name: str) -> dict[str, Any]:
    directory = _runbooks_dir()
    with tool_span(TOOL_ID, alarm_name=alarm_name, runbooks_dir=str(directory)) as span:
        index = _build_index(directory)
        match_path = index.get(alarm_name)
        if match_path is None:
            span.set_attribute("found", False)
            return {
                "found": False,
                "alarm_name": alarm_name,
                "available_runbooks": sorted(index.keys()),
            }
        content = match_path.read_text(encoding="utf-8")
        sections = _parse_sections(content)
        span.set_attribute("found", True)
        span.set_attribute("runbook_slug", match_path.stem)
        return {
            "found": True,
            "alarm_name": alarm_name,
            "slug": match_path.stem,
            "content": content,
            "sections": sections.model_dump(exclude_none=True),
        }
