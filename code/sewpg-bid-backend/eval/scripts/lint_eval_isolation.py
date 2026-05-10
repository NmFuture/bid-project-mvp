from __future__ import annotations

import argparse
import ast
from pathlib import Path


FORBIDDEN_EVAL_IMPORT_PREFIXES = ("app", "opencode")
FORBIDDEN_PRODUCTION_IMPORT_PREFIXES = ("eval",)
PRODUCTION_DIR_NAMES = ("app", "opencode")


def lint_isolation(repo_root: Path) -> list[str]:
    errors: list[str] = []
    eval_dir = repo_root / "eval"
    for path in _python_files(eval_dir):
        errors.extend(_lint_forbidden_imports(path, FORBIDDEN_EVAL_IMPORT_PREFIXES, "eval code"))

    for name in PRODUCTION_DIR_NAMES:
        prod_dir = repo_root / name
        for path in _python_files(prod_dir):
            errors.extend(_lint_forbidden_imports(path, FORBIDDEN_PRODUCTION_IMPORT_PREFIXES, f"{name} code"))
    return errors


def _python_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [path for path in root.rglob("*.py") if "__pycache__" not in path.parts]


def _lint_forbidden_imports(path: Path, prefixes: tuple[str, ...], label: str) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return [f"{path}: syntax error: {exc}"]
    errors: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _matches_prefix(alias.name, prefixes):
                    errors.append(f"{path}:{node.lineno}: {label} imports forbidden module {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if _matches_prefix(module, prefixes):
                errors.append(f"{path}:{node.lineno}: {label} imports forbidden module {module}")
    return errors


def _matches_prefix(module: str, prefixes: tuple[str, ...]) -> bool:
    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in prefixes)


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint eval/skill physical isolation.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()

    errors = lint_isolation(args.repo_root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("eval isolation lint passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
