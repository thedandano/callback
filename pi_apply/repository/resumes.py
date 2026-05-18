import os
import shutil
from pathlib import Path

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".text", ".markdown"}


class ResumeNotFoundError(Exception):
    pass


def data_dir() -> Path:
    if "XDG_DATA_HOME" in os.environ:
        return Path(os.environ["XDG_DATA_HOME"]) / "pi-apply" / "inputs"
    return Path.home() / ".local" / "share" / "pi-apply" / "inputs"


def save_resume(label: str, path: str) -> str:
    source = Path(path)
    dest_dir = data_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest_path = dest_dir / f"{label}{source.suffix}"
    shutil.copy2(source, dest_path)
    return str(dest_path)


def get_resume(label: str) -> str:
    dest_dir = data_dir()
    if not dest_dir.exists():
        raise ResumeNotFoundError(f"Resume '{label}' not found")

    for ext in SUPPORTED_EXTENSIONS:
        candidate = dest_dir / f"{label}{ext}"
        if candidate.exists():
            return str(candidate)

    raise ResumeNotFoundError(f"Resume '{label}' not found")


def list_resumes() -> list[str]:
    dest_dir = data_dir()
    if not dest_dir.exists():
        return []

    labels = set()
    for ext in SUPPORTED_EXTENSIONS:
        for file in dest_dir.glob(f"*{ext}"):
            labels.add(file.stem)
    return sorted(labels)


def clear_resumes() -> None:
    dest_dir = data_dir()
    if not dest_dir.exists():
        return
    for ext in SUPPORTED_EXTENSIONS:
        for file in dest_dir.glob(f"*{ext}"):
            file.unlink()
