import os
import shutil
from pathlib import Path

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".text", ".markdown"}


class ResumeNotFoundError(Exception):
    pass


def data_dir() -> Path:
    if "XDG_DATA_HOME" in os.environ:
        return Path(os.environ["XDG_DATA_HOME"]) / "callback" / "inputs"
    return Path.home() / ".local" / "share" / "callback" / "inputs"


def save_resume(label: str, path: str) -> str:
    source = Path(path)
    dest_dir = data_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest_path = dest_dir / f"{label}{source.suffix}"
    shutil.copy2(source, dest_path)
    return str(dest_path)


def replace_resume(label: str, path: str) -> str:
    """Stage a copy of the replacement resume before clearing the registry.

    Copies the source to a `.staging` file first (ignored by list_resumes/
    clear_resumes since it is outside SUPPORTED_EXTENSIONS) so a copy failure,
    or the source being the currently registered file, never destroys the
    working resume.
    """
    source = Path(path)
    dest_dir = data_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)

    staged = dest_dir / f"{label}{source.suffix}.staging"
    try:
        shutil.copy2(source, staged)
    except OSError:
        staged.unlink(missing_ok=True)
        raise

    clear_resumes()
    dest_path = dest_dir / f"{label}{source.suffix}"
    staged.replace(dest_path)
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
