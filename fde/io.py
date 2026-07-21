from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    text = json.dumps(
        data, indent=2, ensure_ascii=False,
        default=lambda obj: obj.model_dump(mode="json") if isinstance(obj, BaseModel) else str(obj),
    )
    atomic_write_text(path, text + "\n")


def load_model(path: Path, model: type[T]) -> T:
    return model.model_validate(read_json(path))


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def versioned_path(directory: Path, stem: str, suffix: str, version: int) -> Path:
    return directory / f"{stem}_v{version:02d}{suffix}"


def safe_copy(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination
