"""Focused developer checks with quiet output; release verification always uses --full."""

import argparse
import ast
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def changed_files():
    tracked = subprocess.check_output(["git", "diff", "HEAD", "--name-only"], cwd=ROOT, text=True)
    new = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, text=True
    )
    return tracked.splitlines() + new.splitlines()


def select_tests(files):
    tests = sorted(ROOT.glob("tests/**/test_*.py"))
    source = ROOT / "src"
    changed = {Path(f).as_posix() for f in files}
    if any(f.startswith("src/") and not (ROOT / f).exists() for f in changed):
        return ["tests"]
    # Shared contracts, UI integration, fixtures and packaging demand the full gate.
    if any(
        not f.startswith(("src/local_pdf_toolkit/converters/", "tests/", "docs/", "benchmarks/"))
        or (f.startswith("tests/") and not Path(f).name.startswith("test_"))
        for f in changed
    ):
        return ["tests"]
    modules = {
        ".".join(p.relative_to(source).with_suffix("").parts): p for p in source.rglob("*.py")
    }
    modules.update({p.stem: p for p in tests})
    cache = {}

    def dependencies(path, seen):
        if path in seen:
            return set()
        seen.add(path)
        if path not in cache:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imports = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(n.name for n in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module)
                    imports.update(node.module + "." + n.name for n in node.names)
            cache[path] = imports
        result = {path.relative_to(ROOT).as_posix()}
        for module in cache[path]:
            if module in modules:
                result.update(dependencies(modules[module], seen))
        return result

    selected = [p.relative_to(ROOT).as_posix() for p in tests if dependencies(p, set()) & changed]
    # Unknown converter changes must not result in a false "nothing to check".
    if not selected and any(f.startswith("src/") for f in changed):
        return ["tests"]
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--files", nargs="+")
    parser.add_argument(
        "--plan", action="store_true", help="Print selected paths without running checks"
    )
    args = parser.parse_args()
    selected = ["tests"] if args.full else select_tests(args.files or changed_files())
    if args.plan:
        print("\n".join(selected) or "No Python tests selected; lint/format still apply.")
        return 0
    log = ROOT / ".check-results.log"
    commands = [
        [sys.executable, "-m", "ruff", "check", "."],
        [sys.executable, "-m", "ruff", "format", "--check", "."],
    ]
    if selected:
        commands.append(
            [sys.executable, "-m", "pytest", *selected, "-q", "--maxfail=3", "--timeout=60"]
        )
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    with log.open("w", encoding="utf-8") as stream:
        for command in commands:
            stream.write(" ".join(command) + "\n")
            stream.flush()
            completed = subprocess.run(
                command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT
            )
            if completed.returncode:
                print("\n".join(log.read_text(encoding="utf-8").splitlines()[-70:]))
                print(f"Full failure log: {log}")
                return completed.returncode
    print("\n".join(log.read_text(encoding="utf-8").splitlines()[-3:]))
    print(f"Checks passed. Full log: {log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
