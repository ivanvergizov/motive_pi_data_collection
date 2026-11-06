from __future__ import annotations

import csv
from pathlib import Path
from typing import cast, get_args

from motion_app.core.app_types import BodyType

DEFAULT_BODY_TYPE: BodyType = "tetrahedron"
BODY_TYPE_FILE = Path(__file__).resolve().parents[2] / "rigid_body_types.csv"
_VALID_BODY_TYPES = set(get_args(BodyType))


def load_body_type_map(path: str | Path = BODY_TYPE_FILE) -> dict[str, BodyType]:
    config_path = Path(path)
    if not config_path.is_file():
        return {}

    body_types: dict[str, BodyType] = {}
    with config_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != ["rigid_body_name", "body_type"]:
            raise ValueError(
                f"{config_path.name} must have the columns rigid_body_name,body_type."
            )
        for line_number, row in enumerate(reader, start=2):
            body_name = (row.get("rigid_body_name") or "").strip()
            body_type = (row.get("body_type") or "").strip()
            if not body_name and not body_type:
                continue
            if not body_name:
                raise ValueError(f"Missing rigid body name on line {line_number} of {config_path.name}.")
            if body_type not in _VALID_BODY_TYPES:
                choices = ", ".join(sorted(_VALID_BODY_TYPES))
                raise ValueError(
                    f"Unknown body type {body_type!r} on line {line_number} of {config_path.name}. "
                    f"Use one of: {choices}."
                )
            body_types[body_name] = cast(BodyType, body_type)
    return body_types
