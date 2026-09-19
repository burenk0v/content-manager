from __future__ import annotations

import ast
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PythonQualityIssue:
    code: str
    message: str


@dataclass(frozen=True)
class PythonQualityReport:
    checked: bool
    valid: bool
    issues: tuple[PythonQualityIssue, ...] = ()


_PYTHON_FENCE_RE = re.compile(r"```(?:python|py)\s*\n(.*?)```", re.IGNORECASE | re.DOTALL)


def extract_python_blocks(text: str) -> list[str]:
    return [match.strip() for match in _PYTHON_FENCE_RE.findall(text or "") if match.strip()]


def validate_python_code(code: str) -> PythonQualityReport:
    source = (code or "").strip()
    if not source:
        return PythonQualityReport(checked=True, valid=False, issues=(
            PythonQualityIssue("empty", "Python code block is empty"),
        ))

    try:
        ast.parse(source)
    except SyntaxError as exc:
        location = f" at line {exc.lineno}" if exc.lineno else ""
        return PythonQualityReport(
            checked=True,
            valid=False,
            issues=(PythonQualityIssue("syntax_error", f"Python syntax error{location}: {exc.msg}"),),
        )

    return PythonQualityReport(checked=True, valid=True)


def validate_post(text: str) -> PythonQualityReport:
    blocks = extract_python_blocks(text)
    if not blocks:
        return PythonQualityReport(checked=False, valid=True)

    issues: list[PythonQualityIssue] = []
    for index, block in enumerate(blocks, start=1):
        report = validate_python_code(block)
        issues.extend(
            PythonQualityIssue(issue.code, f"Python block {index}: {issue.message}")
            for issue in report.issues
        )

    return PythonQualityReport(
        checked=True,
        valid=not issues,
        issues=tuple(issues),
    )


def format_quality_failure(report: PythonQualityReport) -> str:
    return "; ".join(f"{issue.code}: {issue.message}" for issue in report.issues)
