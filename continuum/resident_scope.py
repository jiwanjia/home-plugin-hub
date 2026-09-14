"""Trusted resident scope for one Continuum service instance.

The host resolves this value from the resident registry. Model text and public
tool arguments must never choose it.
"""

import re
from dataclasses import dataclass
from pathlib import Path


_SAFE_SCOPE_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class ResidentScope:
    """Immutable resident identity and its structured-memory namespace."""

    resident_id: str
    memory_namespace: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("resident_id", self.resident_id),
            ("memory_namespace", self.memory_namespace),
        ):
            if not _SAFE_SCOPE_ID.fullmatch(value):
                raise ValueError(
                    f"{field_name} must use safe lowercase resident characters"
                )

    def structured_db_path(self, project_root: str) -> str:
        """Return this resident's local structured-memory database path."""
        root = Path(project_root).resolve()
        database = root / "memory" / "continuum-residents" / (
            f"{self.memory_namespace}.db"
        )
        return str(database)
