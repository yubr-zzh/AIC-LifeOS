"""Replace a JSON state file without exposing a partially written document."""

import json
import os
import time
import uuid
from pathlib import Path


def write_json(path: Path, data) -> None:
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        for attempt in range(6):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                # Windows can briefly lock a newly written file while indexing it.
                time.sleep(0.01 * (2 ** attempt))
    finally:
        temporary.unlink(missing_ok=True)
