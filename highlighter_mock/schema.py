"""The vocabulary of the Highlighter data: allowed values, field lists, limits, paths.

Shared by the API (for validation) and the MCP server (for tool descriptions), so
both always agree on what values are valid.
"""

from pathlib import Path

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_FLAGS_PATH = DEFAULT_DATA_DIR / "runtime" / "flags.jsonl"

CATEGORIES = ("hazard", "issue", "asset")
SEVERITIES = ("low", "medium", "high", "critical", "info")
STATUSES = ("open", "acknowledged", "resolved", "dismissed", "n/a")
FLAG_PRIORITIES = ("low", "medium", "high")

ALL_FIELDS = (
    "id", "site_id", "observed_at", "source_id", "source_type", "category", "type",
    "severity", "confidence", "status", "acknowledged_at", "resolved_at", "image_ref",
)
# Returned unless the caller asks for specific fields. Leaves out image_ref,
# source_id and acknowledged_at to keep responses (and model tokens) small.
DEFAULT_FIELDS = (
    "id", "site_id", "observed_at", "source_type", "category", "type",
    "severity", "confidence", "status", "resolved_at",
)

DEFAULT_LIMIT = 200
MAX_LIMIT = 1000
MAX_REASON_LEN = 500
