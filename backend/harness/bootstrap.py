#!/usr/bin/env python3
"""Prepare one project-owned Python environment for the Harness and its Skills."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import subprocess
import sys


class BootstrapError(RuntimeError):
    pass


def clean_environment(root: Path) -> dict[str, str]:
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith("PIP_") and key not in {"PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"}
    }
    # pip honors this even with --isolated: global, user and venv pip.ini targets
    # must not redirect installation away from this project's interpreter.
    env.update({
        "PIP_CONFIG_FILE": os.devnull,
        "PYTHONNOUSERSITE": "1",
        "MPLBACKEND": "Agg",
        "MPLCONFIGDIR": str(root / ".run/harness-runtime/matplotlib"),
        "XDG_CACHE_HOME": str(root / ".run/harness-runtime/cache"),
    })
    return env


def run(command: list[str], root: Path, env: dict[str, str], label: str, timeout: int | None = None) -> str:
    try:
        result = subprocess.run(command, cwd=root, env=env, text=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise BootstrapError(f"{label}超时（{timeout} 秒）") from error
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-8000:]
        raise BootstrapError(f"{label}失败（退出码 {result.returncode}）：\n{detail}")
    return result.stdout


def requirement_roots(root: Path) -> list[Path]:
    sources = []
    base = root / "requirements-harness.txt"
    if base.is_file():
        sources.append(base)
    for name in ("skills", ".agents/skills", ".dsh/skills"):
        directory = root / name
        if not directory.is_dir():
            continue
        for skill in sorted(directory.iterdir()):
            if skill.is_dir() and (skill / "SKILL.md").is_file():
                requirements = skill / "requirements.txt"
                if not requirements.is_file():
                    requirements = skill / "scripts/requirements.txt"
                if requirements.is_file():
                    sources.append(requirements)
    return sorted(set(path.resolve() for path in sources))


def requirement_contents(sources: list[Path]) -> dict[str, str]:
    """Hash local -r/-c includes too; pip itself remains the requirements parser."""
    contents: dict[str, str] = {}

    def visit(source: Path) -> None:
        source = source.resolve()
        if str(source) in contents:
            return
        try:
            text = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise BootstrapError(f"无法读取依赖清单 {source}：{error}") from error
        contents[str(source)] = text
        logical_lines = text.replace("\\\r\n", "").replace("\\\n", "").splitlines()
        for line in logical_lines:
            stripped = line.strip()
            # Ordinary package specifiers can contain shell-special characters;
            # inspect only include directives, leaving all other syntax to pip.
            if not stripped.startswith(("-r", "-c", "--requirement", "--constraint")):
                continue
            try:
                tokens = shlex.split(stripped, comments=True)
            except ValueError as error:
                raise BootstrapError(f"依赖引用语法错误 {source}：{line}") from error
            if not tokens:
                continue
            first = tokens[0]
            if first in {"-r", "-c", "--requirement", "--constraint"}:
                target = tokens[1] if len(tokens) > 1 else ""
            elif first.startswith(("--requirement=", "--constraint=")):
                target = first.split("=", 1)[1]
            elif first.startswith(("-r", "-c")) and not first.startswith("--"):
                target = first[2:].lstrip("=")
            else:
                continue
            if not target or "://" in target:
                raise BootstrapError(f"依赖引用必须是可读取的本地文件 {source}：{line}")
            visit(source.parent / os.path.expandvars(target))

    for source in sources:
        visit(source)
    return contents


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@contextmanager
def project_lock(cache: Path):
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / "bootstrap.lock").open("a") as handle:
        # Kernel-owned locks are released on process exit, including a crash.
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


ENVIRONMENT_REPORT = """
import importlib.metadata, json, re, sys
normalize = lambda name: re.sub(r'[-_.]+', '-', name).lower()
print(json.dumps({'prefix': sys.prefix, 'version': sys.version, 'installed': sorted(
    [normalize(d.metadata['Name']), d.version] for d in importlib.metadata.distributions()
    if d.metadata.get('Name'))}))
"""


def bootstrap(root: Path, force: bool = False) -> dict:
    root = root.resolve()
    if not root.is_dir():
        raise BootstrapError(f"项目目录不存在：{root}")
    if sys.version_info < (3, 11):
        raise BootstrapError("Harness 需要 Python >=3.11")
    cache = root / ".run/harness-runtime"
    venv = root / ".venv"
    python = venv / "bin/python"
    marker = cache / "python-dependencies.json"
    pending = cache / "python-dependencies.pending"
    env = clean_environment(root)
    with project_lock(cache):
        (root / "skills").mkdir(exist_ok=True)
        sources = requirement_roots(root)
        contents = requirement_contents(sources)
        if not (venv / "pyvenv.cfg").is_file():
            print(f"[python] 创建项目虚拟环境：{venv}", flush=True)
            run([sys.executable, "-I", "-m", "venv", str(venv)], root, env, "创建虚拟环境")
        if not python.is_file() or not os.access(python, os.X_OK):
            raise BootstrapError(f"项目虚拟环境解释器不可用：{python}")
        env.update({"VIRTUAL_ENV": str(venv), "PATH": str(python.parent) + os.pathsep + env.get("PATH", "")})

        def report() -> dict:
            state = json.loads(run([str(python), "-I", "-c", ENVIRONMENT_REPORT], root, env, "检查虚拟环境"))
            if Path(state["prefix"]).resolve() != venv.resolve():
                raise BootstrapError(f"解释器未指向项目虚拟环境：{state['prefix']}")
            return state

        state = report()
        configuration = digest({
            "requirements": contents,
            "python": state["version"],
            "venv": (venv / "pyvenv.cfg").read_text(),
            "platform": platform.platform(),
        })
        installed = digest(state["installed"])
        try:
            previous = json.loads(marker.read_text())
        except (OSError, ValueError):
            previous = {}
        if not force and not pending.exists() and previous.get("configuration") == configuration and previous.get("installed") == installed:
            print(f"[python] 依赖已就绪，跳过安装（{len(sources)} 份清单）", flush=True)
            return {**previous, "skipped": True}

        pip = [str(python), "-I", "-m", "pip", "--isolated", "--disable-pip-version-check"]
        requirement_args = [argument for source in sources for argument in ("-r", str(source))]
        names = "\n".join(f"  {source}" for source in sources) or "  无额外依赖"
        print(f"[python] 统一检查并安装 {len(sources)} 份依赖清单", flush=True)
        # Preserve the old success marker but never skip a failed or interrupted
        # attempt, even if --force failed before installed versions changed.
        pending.write_text("initialization in progress; retry until successful\n")
        try:
            if sources:
                # Solve all Skills together before changing packages. Incompatible
                # pins fail during this dry run and leave the old environment intact.
                install = [*pip, "install", "--prefix", str(venv), "--no-user", *requirement_args]
                run([*install, "--dry-run"], root, env, "依赖求解")
                run(install, root, env, "安装依赖")
            run([*pip, "check"], root, env, "依赖一致性检查")
            run([str(python), "-I", "-c", "import importlib.util; exec('import matplotlib.pyplot' if importlib.util.find_spec('matplotlib') else '')"], root, env, "初始化绘图缓存", timeout=120)
        except BootstrapError as error:
            raise BootstrapError(f"{error}\n相关依赖清单：\n{names}\n未更新依赖成功标记；修复清单或网络后再次运行会重试。") from error
        state = report()
        outcome = {"configuration": configuration, "installed": digest(state["installed"]), "requirements": sorted(contents), "python": str(python)}
        temporary = marker.with_suffix(".tmp")
        temporary.write_text(json.dumps(outcome, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(marker)
        pending.unlink()
        print(f"[python] 项目依赖已就绪：{python}", flush=True)
        return {**outcome, "skipped": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--force", action="store_true", help="即使清单未变也重新检查依赖")
    args = parser.parse_args()
    try:
        bootstrap(args.root, args.force)
    except (BootstrapError, OSError) as error:
        print(f"[python] {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
