"""Offline contracts: temporary workspaces and locally generated wheels only."""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


BOOTSTRAP = Path(__file__).resolve().parents[1] / "harness/bootstrap.py"


def wheel(directory: Path, name: str, version: str) -> None:
    distribution = name.replace("-", "_")
    info = f"{distribution}-{version}.dist-info"
    files = {
        f"{distribution}/__init__.py": f"VERSION = {version!r}\n".encode(),
        f"{info}/METADATA": f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\nOffline test package.\n".encode(),
        f"{info}/WHEEL": b"Wheel-Version: 1.0\nGenerator: unittest\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    record = io.StringIO()
    writer = csv.writer(record, lineterminator="\n")
    for filename, data in files.items():
        encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        writer.writerow([filename, "sha256=" + encoded, len(data)])
    writer.writerow([f"{info}/RECORD", "", ""])
    files[f"{info}/RECORD"] = record.getvalue().encode()
    with zipfile.ZipFile(directory / f"{distribution}-{version}-py3-none-any.whl", "w") as archive:
        for filename, data in files.items():
            archive.writestr(filename, data)


class BootstrapContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ocean-bootstrap-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "workspace"
        self.root.mkdir()
        self.wheels = Path(self.temporary.name) / "wheels"
        self.wheels.mkdir()
        for name in ("harness-probe", "harness-extra"):
            for version in ("1.0.0", "2.0.0"):
                wheel(self.wheels, name, version)
        (self.root / "requirements-harness.txt").write_text(
            f"--no-index\n--find-links {self.wheels}\nharness-probe==1.0.0\n"
        )
        self.marker = self.root / ".run/harness-runtime/python-dependencies.json"
        self.python = self.root / ".venv/bin/python"

    def start(self, *, success=True, force=False, env=None):
        command = [sys.executable, "-I", str(BOOTSTRAP), "--root", str(self.root)]
        if force:
            command.append("--force")
        result = subprocess.run(command, text=True, capture_output=True, env=env, timeout=90)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def versions(self):
        script = "import importlib.metadata as m,json; print(json.dumps({d.metadata['Name']:d.version for d in m.distributions()}))"
        return json.loads(subprocess.check_output([str(self.python), "-I", "-c", script], text=True))

    def skill(self, name, requirements=None, directory="skills"):
        skill = self.root / directory / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Offline test.\n---\nRun the local script.\n")
        if requirements is not None:
            (skill / "requirements.txt").write_text(requirements)
        return skill

    def test_cold_start_creates_project_venv_and_skips_repeated_start(self):
        self.assertFalse(self.python.exists())
        self.start()
        self.assertEqual(self.versions()["harness-probe"], "1.0.0")
        prefix = subprocess.check_output([str(self.python), "-I", "-c", "import sys;print(sys.prefix)"], text=True).strip()
        self.assertEqual(Path(prefix).resolve(), (self.root / ".venv").resolve())
        marker = self.marker.read_bytes()
        repeated = self.start()
        self.assertIn("跳过安装", repeated.stdout)
        self.assertEqual(self.marker.read_bytes(), marker)

    def test_new_skill_automatically_installs_its_dependency(self):
        self.start()
        self.skill("added", "harness-extra==1.0.0\n")
        result = self.start()
        self.assertNotIn("跳过安装", result.stdout)
        self.assertEqual(self.versions()["harness-extra"], "1.0.0")
        self.assertIn("跳过安装", self.start().stdout)

    def test_scripts_requirements_fallback_installs_and_refreshes(self):
        skill = self.skill("scripts-only")
        requirements = skill / "scripts/requirements.txt"
        requirements.parent.mkdir()
        requirements.write_text("harness-extra==1.0.0\n")
        self.start()
        self.assertEqual(self.versions()["harness-extra"], "1.0.0")
        original = self.marker.read_bytes()
        manifest = json.loads(original)
        self.assertIn(str(requirements.resolve()), manifest["requirements"])
        requirements.write_text("harness-extra==2.0.0\n")
        self.start()
        self.assertEqual(self.versions()["harness-extra"], "2.0.0")
        self.assertNotEqual(self.marker.read_bytes(), original)
        self.assertIn("跳过安装", self.start().stdout)

    def test_root_requirements_precede_scripts_fallback(self):
        skill = self.skill("root-first", "harness-extra==1.0.0\n")
        fallback = skill / "scripts/requirements.txt"
        fallback.parent.mkdir()
        # Installing both files would be an unsatisfiable conflict.
        fallback.write_text("harness-extra==2.0.0\n")
        self.start()
        self.assertEqual(self.versions()["harness-extra"], "1.0.0")
        original = self.marker.read_bytes()
        self.assertNotIn(str(fallback.resolve()), json.loads(original)["requirements"])
        fallback.write_text("impossible-test-package==999\n")
        self.assertIn("跳过安装", self.start().stdout)
        self.assertEqual(self.marker.read_bytes(), original)
        # Removing the root manifest activates the fallback on the next start.
        (skill / "requirements.txt").unlink()
        fallback.write_text("harness-extra==2.0.0\n")
        self.start()
        self.assertEqual(self.versions()["harness-extra"], "2.0.0")
        self.assertIn(str(fallback.resolve()), json.loads(self.marker.read_text())["requirements"])

    def test_nested_scripts_requirements_change_triggers_new_solve(self):
        skill = self.skill("scripts-nested")
        requirements = skill / "scripts/requirements.txt"
        nested = skill / "scripts/dependencies/runtime.txt"
        nested.parent.mkdir(parents=True)
        requirements.write_text("-r dependencies/runtime.txt\n")
        nested.write_text("harness-extra==1.0.0\n")
        self.start()
        original = self.marker.read_bytes()
        self.assertIn(str(nested.resolve()), json.loads(original)["requirements"])
        nested.write_text("harness-extra==2.0.0\n")
        self.start()
        self.assertEqual(self.versions()["harness-extra"], "2.0.0")
        self.assertNotEqual(self.marker.read_bytes(), original)

    def test_nested_requirements_change_triggers_new_solve(self):
        skill = self.skill("nested", "-r requirements/runtime.txt\n")
        nested = skill / "requirements/runtime.txt"
        nested.parent.mkdir()
        nested.write_text("harness-extra==1.0.0\n")
        self.start()
        marker = self.marker.read_bytes()
        nested.write_text("harness-extra==2.0.0\n")
        self.start()
        self.assertEqual(self.versions()["harness-extra"], "2.0.0")
        self.assertNotEqual(self.marker.read_bytes(), marker)

    def test_nested_constraint_change_triggers_new_solve(self):
        skill = self.skill("constrained", "harness-extra\n-c constraints.txt\n")
        constraint = skill / "constraints.txt"
        constraint.write_text("harness-extra==1.0.0\n")
        self.start()
        constraint.write_text("harness-extra==2.0.0\n")
        self.start()
        self.assertEqual(self.versions()["harness-extra"], "2.0.0")

    def test_conflicting_skills_do_not_mutate_existing_packages_or_marker(self):
        self.start()
        original = self.marker.read_bytes()
        versions = self.versions()
        self.skill("conflict", "harness-probe==2.0.0\n")
        result = self.start(success=False)
        self.assertIn("依赖求解失败", result.stderr)
        self.assertIn("conflict/requirements.txt", result.stderr)
        self.assertEqual(self.versions(), versions)
        self.assertEqual(self.marker.read_bytes(), original)
        (self.root / "skills/conflict/requirements.txt").write_text("harness-probe==1.0.0\n")
        self.start()

    def test_all_project_skill_roots_and_skill_without_requirements(self):
        self.skill("empty")
        self.skill("agents", "harness-extra==1.0.0\n", ".agents/skills")
        self.skill("dsh", "harness-probe==1.0.0\n", ".dsh/skills")
        # An arbitrary requirements file without a Skill is not an install source.
        ignored = self.root / "skills/not-a-skill"
        ignored.mkdir()
        (ignored / "requirements.txt").write_text("impossible-test-package==999\n")
        self.start()
        self.assertEqual(self.versions()["harness-extra"], "1.0.0")
        manifest = json.loads(self.marker.read_text())
        self.assertEqual(len(manifest["requirements"]), 3)

    def test_external_python_and_pip_targets_cannot_redirect_installs(self):
        outside = Path(self.temporary.name) / "must-not-install-here"
        env = dict(os.environ, PYTHONHOME="/does-not-exist", PYTHONPATH="/other/python/packages", VIRTUAL_ENV="/other/venv", PIP_TARGET=str(outside), PIP_PREFIX=str(outside), PIP_USER="1")
        self.start(env=env)
        self.assertFalse(outside.exists())
        self.assertEqual(self.versions()["harness-probe"], "1.0.0")

    def test_installed_package_drift_reinstalls_missing_requirement(self):
        self.start()
        subprocess.check_call([str(self.python), "-I", "-m", "pip", "--isolated", "--disable-pip-version-check", "uninstall", "-y", "harness-probe"], stdout=subprocess.DEVNULL)
        result = self.start()
        self.assertNotIn("跳过安装", result.stdout)
        self.assertEqual(self.versions()["harness-probe"], "1.0.0")

    def test_force_rechecks_dependencies(self):
        self.start()
        result = self.start(force=True)
        self.assertNotIn("跳过安装", result.stdout)
        self.assertIn("统一检查并安装", result.stdout)

    def test_failed_force_attempt_retries_without_changing_success_marker(self):
        self.start()
        original = self.marker.read_bytes()
        pip_main = Path(subprocess.check_output(
            [str(self.python), "-I", "-c", "import pip; from pathlib import Path; print(Path(pip.__file__).with_name('__main__.py'))"], text=True
        ).strip())
        original_program = pip_main.read_bytes()
        pip_main.write_text("raise SystemExit(42)\n")
        self.start(force=True, success=False)
        self.assertEqual(self.marker.read_bytes(), original)
        self.assertTrue(self.marker.with_suffix(".pending").exists())
        pip_main.write_bytes(original_program)
        retry = self.start()
        self.assertNotIn("跳过安装", retry.stdout)
        self.assertFalse(self.marker.with_suffix(".pending").exists())
        self.assertIn("跳过安装", self.start().stdout)

    def test_missing_nested_file_reports_path_without_success_marker(self):
        skill = self.skill("missing", "-r missing.txt\n")
        result = self.start(success=False)
        self.assertIn(str(skill / "missing.txt"), result.stderr)
        self.assertFalse(self.marker.exists())

    def test_empty_requirements_still_initializes_a_usable_venv(self):
        (self.root / "requirements-harness.txt").unlink()
        self.skill("instructions-only")
        self.start()
        self.assertTrue(self.python.exists())
        self.assertEqual(json.loads(self.marker.read_text())["requirements"], [])
        self.assertIn("跳过安装", self.start().stdout)

    def test_parallel_starts_share_one_successful_initialization(self):
        command = [sys.executable, "-I", str(BOOTSTRAP), "--root", str(self.root)]
        children = [subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        results = [child.communicate(timeout=90) for child in children]
        for child, (stdout, stderr) in zip(children, results):
            self.assertEqual(child.returncode, 0, stdout + stderr)
        self.assertEqual(sum("创建项目虚拟环境" in output for output, _ in results), 1)
        self.assertEqual(sum("跳过安装" in output for output, _ in results), 1)
        self.assertEqual(self.versions()["harness-probe"], "1.0.0")


if __name__ == "__main__":
    unittest.main()
