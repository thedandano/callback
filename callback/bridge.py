"""Go subprocess bridge for callback.

Handles binary resolution and subprocess execution for the go-apply CLI.
Binary resolution runs at module import time.
"""

import os
import shutil
import subprocess


def _resolve_binary() -> str:
    candidate = os.environ.get("GO_APPLY_BIN")
    if candidate and os.path.isfile(candidate):
        return candidate
    found = shutil.which("go-apply")
    if found is None:
        raise OSError(
            "go-apply binary not found. Set GO_APPLY_BIN environment variable "
            "or ensure go-apply is on PATH."
        )
    return found


# Resolution runs at import time; _BIN is str (raises before assignment if missing)
_BIN: str = _resolve_binary()


class SubprocessError(Exception):
    """Exception raised when subprocess execution fails.

    Attributes:
        cmd: The command that was executed
        returncode: The exit code
        stderr: The stderr output (decoded to string)
    """

    def __init__(self, cmd: list[str], returncode: int, stderr: str):
        self.cmd = cmd
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"Command {cmd} failed with exit code {returncode}: {stderr}")


def run_pdfrender(args: list[str]) -> bytes:
    """Execute go-apply with pdfrender command.

    Args:
        args: Command-line arguments to pass to go-apply

    Returns:
        stdout as bytes on success

    Raises:
        SubprocessError: If the process exits with non-zero code
    """
    cmd = [_BIN] + args
    result = subprocess.run(cmd, capture_output=True, check=False)

    if result.returncode == 0:
        return result.stdout

    raise SubprocessError(cmd=cmd, returncode=result.returncode, stderr=result.stderr.decode())


def run_survival(args: list[str]) -> str:
    """Execute go-apply with survival command.

    Args:
        args: Command-line arguments to pass to go-apply

    Returns:
        stdout as string on success

    Raises:
        SubprocessError: If the process exits with non-zero code
    """
    cmd = [_BIN] + args
    result = subprocess.run(cmd, capture_output=True, check=False)

    if result.returncode == 0:
        return result.stdout.decode()

    raise SubprocessError(cmd=cmd, returncode=result.returncode, stderr=result.stderr.decode())
