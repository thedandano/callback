"""Setuptools hooks for local pi-apply builds."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


def _package_version() -> str:
    with Path("pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    return data["project"]["version"]


def _build_version() -> str:
    return os.environ.get("PI_APPLY_BUILD_VERSION") or _package_version()


class BuildPy(_build_py):
    """Generate build metadata inside the wheel build directory."""

    def run(self) -> None:
        super().run()
        target = Path(self.build_lib) / "pi_apply" / "_build_info.py"
        target.write_text(
            "# Generated during package build. Do not edit.\n"
            f"BUILD_VERSION = {_build_version()!r}\n",
            encoding="utf-8",
        )


setup(cmdclass={"build_py": BuildPy})
