"""Independent workflow shape and original native-policy invariants."""

import unittest

from helper_support import ROOT, original
import yaml


def load(name, *, intake=False):
    path = ".github/workflows/" + name
    raw = original(path) if intake else (ROOT / path).read_bytes()
    return yaml.load(raw, Loader=yaml.BaseLoader)


def named(workflow, job, name):
    return next(step for step in workflow["jobs"][job]["steps"] if step.get("name") == name)


class WorkflowTests(unittest.TestCase):
    def test_exact_two_independent_manual_workflows_and_required_bump_choice(self):
        self.assertEqual(sorted(path.name for path in (ROOT / ".github/workflows").glob("*")),
                         ["bump-version.yml", "release.yml"])
        bump, build = load("bump-version.yml"), load("release.yml")
        for workflow in (bump, build):
            self.assertEqual(set(workflow["on"]), {"workflow_dispatch"})
            self.assertEqual(workflow["permissions"], {"contents": "write"})
            for job in workflow["jobs"].values():
                for step in job["steps"]:
                    if step.get("uses", "").startswith("actions/checkout@"):
                        self.assertEqual(step["with"]["ref"], "${{ github.sha }}")
        self.assertEqual(build["name"], "Build")
        self.assertIn(build["on"]["workflow_dispatch"], ("", None))
        mode = bump["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(set(mode), {"mode"})
        self.assertEqual(mode["mode"], {
            "type": "choice", "description": "Semantic version bump",
            "options": ["patch", "minor", "major"], "default": "patch", "required": "true"})
        self.assertEqual(set(bump["jobs"]), {"bump"})
        commands = "\n".join(step.get("run", "") for step in bump["jobs"]["bump"]["steps"])
        self.assertIn('python3 .github/scripts/bump.py "$MODE" --sha "$EVENT_SHA" --ref "$EVENT_REF"',
                      commands)
        for forbidden in ("xcodebuild", "msbuild", "release.py", "gh workflow", "git tag"):
            self.assertNotIn(forbidden, commands)

    def test_constant_cross_ref_publication_lock_and_no_new_branch_restriction(self):
        workflow = load("release.yml")
        self.assertEqual(workflow["concurrency"],
                         {"group": "publish-udp", "cancel-in-progress": "false"})
        self.assertEqual(set(workflow["jobs"]), {"version", "build-windows", "build-macos"})
        self.assertEqual(workflow["jobs"]["build-windows"]["needs"], "version")
        self.assertEqual(workflow["jobs"]["build-macos"]["needs"], ["version", "build-windows"])
        for job in workflow["jobs"].values():
            self.assertNotIn("if", job)
            for step in job["steps"]:
                self.assertNotIn("if", step)
        self.assertNotIn("softprops", (ROOT / ".github/workflows/release.yml").read_text())

    def test_original_runners_cmd_artifact_and_credential_steps_preserved(self):
        old, new = load("release.yml", intake=True), load("release.yml")
        for job in old["jobs"]:
            self.assertEqual(new["jobs"][job]["runs-on"], old["jobs"][job]["runs-on"])
        for job, name in (
                ("build-windows", "setup MSBuild"), ("build-windows", "build x64"),
                ("build-windows", "upload windows binaries"),
                ("build-macos", "download windows binaries"),
                ("build-macos", "import Developer ID certificate"),
                ("build-macos", "store notarytool credentials")):
            self.assertEqual(named(new, job, name), named(old, job, name))
        self.assertEqual(new["env"]["PRODUCT_NAME"], "UDP")
        self.assertEqual(new["env"]["MACOS_DEPLOYMENT_TARGET"], "11.0")
        self.assertEqual(new["env"]["BASE_DIR"], "test")

    def test_checkout_scoped_git_config_inherited_before_all_build_jobs(self):
        workflow = load("release.yml")
        expected = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.autocrlf",
                    "GIT_CONFIG_VALUE_0": "false"}
        for job in workflow["jobs"].values():
            for step in job["steps"]:
                if step.get("uses", "").startswith("actions/checkout@"):
                    inherited = {**workflow["env"], **job.get("env", {}), **step.get("env", {})}
                    self.assertEqual({key: inherited[key] for key in expected}, expected)
        raw = (ROOT / ".github/workflows/release.yml").read_text()
        self.assertNotIn("git config --global", raw)
        self.assertNotIn("inputs.", raw)

    def test_authenticated_source_preflight_before_every_native_or_credential_step(self):
        workflow = load("release.yml")
        for name, job in workflow["jobs"].items():
            preflights = [index for index, step in enumerate(job["steps"])
                          if "release.py preflight" in step.get("run", "")]
            self.assertEqual(len(preflights), 1)
            preflight = job["steps"][preflights[0]]
            self.assertEqual(preflight["env"]["GH_TOKEN"], "${{ github.token }}")
            for index, step in enumerate(job["steps"]):
                if step.get("name") in ("setup MSBuild", "import Developer ID certificate",
                                        "store notarytool credentials") \
                        or "native." in step.get("run", "") or "windows.ps1" in step.get("run", ""):
                    self.assertLess(preflights[0], index, (name, step))
        final = workflow["jobs"]["build-macos"]["steps"][-1]
        self.assertIn("release.py publish", final["run"])
        self.assertEqual(final["env"]["GH_TOKEN"], "${{ github.token }}")
        self.assertIn('"UDP-${VERSION}.zip" "UDP-${VERSION}.dmg"', final["run"])
