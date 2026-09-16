"""Fail CI when the domain layer depends on transport or infrastructure."""

from __future__ import annotations

import ast
from pathlib import Path

DOMAIN_ROOT = Path(__file__).resolve().parents[1] / "src" / "app" / "domain"
FORBIDDEN_PREFIXES = (
    "fastapi",
    "starlette",
    "sqlalchemy",
    "src.app.routers",
    "src.app.infrastructure",
)


def imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def main() -> int:
    violations: list[str] = []
    for path in sorted(DOMAIN_ROOT.rglob("*.py")):
        for module in imported_modules(path):
            if module == "__future__":
                continue
            if module.startswith(FORBIDDEN_PREFIXES):
                violations.append(f"{path}: forbidden domain dependency: {module}")

    if violations:
        print("Architecture boundary violations detected:")
        print("\n".join(violations))
        return 1

    print(f"Architecture boundary check passed: {DOMAIN_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
