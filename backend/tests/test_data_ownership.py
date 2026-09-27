"""Fails if any agent imports data it does not own (CLAUDE.md §1 constraint 2, §7).

Every module in every agent folder is parsed. An agent may import only its own repository
(app.data.repositories.<folder>) and app.data.repositories.reference; Tech may also import the
GitHub client. Nothing in an agent may touch sessions, models, SQL or the platform tables.
"""

import ast
from pathlib import Path

import pytest

AGENTS_DIR = Path(__file__).resolve().parents[1] / "app" / "agents"
REPOSITORIES = "app.data.repositories"
SHARED = {f"{REPOSITORIES}.reference"}
EXTRA_ALLOWED = {"tech": {"app.integrations.github_client"}}
FORBIDDEN_PREFIXES = ("app.data.db", "app.data.models", "sqlalchemy", "app.integrations")
AGENT_FOLDERS = sorted(p.name for p in AGENTS_DIR.iterdir() if (p / "agent.py").exists())


def imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            # `from app.data.repositories import finance` imports a repository too
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def violations(folder: str) -> list[str]:
    allowed = SHARED | {f"{REPOSITORIES}.{folder}"} | EXTRA_ALLOWED.get(folder, set())
    found = []
    for path in sorted((AGENTS_DIR / folder).rglob("*.py")):
        for module in sorted(imported_modules(path)):
            if any(module == a or module.startswith(f"{a}.") for a in allowed):
                continue
            repo = module.startswith(f"{REPOSITORIES}.")
            if repo or module.startswith(FORBIDDEN_PREFIXES):
                found.append(f"{path.relative_to(AGENTS_DIR)} imports {module}")
    return found


def test_agent_folders_discovered():
    assert {"ceo", "finance", "hr", "tech"} <= set(AGENT_FOLDERS)


@pytest.mark.parametrize("folder", AGENT_FOLDERS)
def test_agent_imports_only_owned_data(folder):
    assert violations(folder) == []


def test_checker_catches_cross_department_import(tmp_path, monkeypatch):
    bad = tmp_path / "hr"
    bad.mkdir()
    (bad / "agent.py").write_text("")
    (bad / "tools.py").write_text(
        "from app.data.repositories import finance\nimport app.data.repositories.tech\n"
    )
    monkeypatch.setattr("tests.test_data_ownership.AGENTS_DIR", tmp_path)
    assert len(violations("hr")) == 2
