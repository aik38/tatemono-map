import shutil
import subprocess
from pathlib import Path


def _pwsh() -> str | None:
    return shutil.which("pwsh")


def test_mvp_refresh_help_smoke() -> None:
    pwsh = _pwsh()
    if not pwsh:
        import pytest

        pytest.skip("pwsh not found")

    script = Path("scripts/mvp_refresh.ps1")
    result = subprocess.run(
        [pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-?"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "RepoPath" in result.stdout
    assert "CreateMissingSafe" in result.stdout


def test_run_mvp_doctor_help_smoke() -> None:
    pwsh = _pwsh()
    if not pwsh:
        import pytest

        pytest.skip("pwsh not found")

    script = Path("scripts/run_mvp_doctor.ps1")
    result = subprocess.run(
        [pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-?"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "RepoPath" in result.stdout
    assert "DbPath" in result.stdout
    assert "UnmatchedFactsPolicy" in result.stdout
