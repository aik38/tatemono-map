from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]


def repo_path(*parts: str) -> Path:
    return REPO_ROOT.joinpath(*parts)


SRC = repo_path("src")
sys.path.insert(0, str(SRC))
