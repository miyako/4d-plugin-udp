"""Fail-closed API matrices and actual CLI publication against fake gh and real Git."""

import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
from unittest.mock import patch

from helper_support import Fixture, GitFixture, ROOT, source
from native_support import STUB as NATIVE_STUB
import native
import release
import yaml


TAG, SHA = "v3.2.1", "a" * 40
REPO = release.REPOSITORY
BASE = "repos/" + REPO
UPLOAD = f"https://uploads.github.com/repos/{REPO}/releases/789/assets"


def entry(identifier=1, tag="v9.8.7", draft=False):
    return {"id": identifier, "tag_name": tag, "draft": draft, "prerelease": False}


def ref(tag=TAG, sha=SHA, kind="commit"):
    return {"ref": "refs/tags/" + tag, "object": {"sha": sha, "type": kind}}


class API:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def api(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if not self.replies:
            raise AssertionError("Unexpected API call")
        response = self.replies.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class AvailabilityTests(GitFixture):
    def available(self, api, tag):
        with patch.object(release.repository, "run", side_effect=lambda *args: self.git(*args[1:])):
            return release.available(api, tag)

    def test_all_pages_drafts_prefix_tags_and_exact_occupancy(self):
        pages = [[entry(i + 1) for i in range(100)], [entry(101)], [], []]
        api = API(pages)
        self.assertEqual(len(self.available(api, TAG)), 101)
        self.assertEqual([call[0][1] for call in api.calls], [
            f"{BASE}/releases?per_page=100&page=1",
            f"{BASE}/releases?per_page=100&page=2",
            f"{BASE}/releases?per_page=100&page=3",
            f"{BASE}/git/matching-refs/tags/{TAG}",
        ])
        for draft in (False, True):
            with self.assertRaises(ValueError):
                self.available(API([[entry(1)], [entry(2, TAG, draft)], [], []]), TAG)
        with self.assertRaises(ValueError):
            self.available(API([[], [ref()]]), TAG)
        self.available(API([[], [ref(TAG + "0"), ref(TAG + "-rc1")]]), TAG)

    def test_every_read_error_malformed_pages_duplicate_ids_refs_fail_closed(self):
        malformed = [None, {}, "[]", [None], [{}], [entry(True)], [entry(0)],
                     [dict(entry(), tag_name="")], [dict(entry(), draft="false")],
                     [dict(entry(), prerelease=None)], [entry(i) for i in range(1, 102)]]
        for prefix in ([], [[entry(1)]]):
            for bad in malformed + [ValueError("404/auth/network")]:
                api = API(prefix + [bad])
                with self.assertRaises(ValueError):
                    self.available(api, TAG)
                self.assertEqual(len(api.calls), len(prefix) + 1)
        for pages in ([[entry(1), entry(1)]], [[entry(1)], [entry(1)]]):
            with self.assertRaisesRegex(ValueError, "Duplicate release ID"):
                self.available(API(pages), TAG)
        for bad in (None, {}, [None], [{}], [ref(kind="blob")], [ref(sha="short")],
                    [ref("vother")], [ref(TAG + "0"), ref(TAG + "0")]):
            with self.assertRaises(ValueError):
                self.available(API([[], bad]), TAG)
        for tag in ("v01.2.3", "v1.02.3", "v1.2", "1.2.3", "v1.2.3-rc", TAG + "\n", None):
            api = API([])
            with self.assertRaises(ValueError):
                self.available(api, tag)
            self.assertEqual(api.calls, [])

    def test_exact_remote_tag_advertisement_absence_occupancy_and_transport_errors(self):
        with patch.object(release.repository, "run", return_value="") as run:
            self.assertIsNone(release.remote_tag(TAG))
            self.assertEqual(run.call_args.args,
                             ("git", "ls-remote", "--refs", "origin", "refs/tags/" + TAG))
        with patch.object(release.repository, "run", return_value=SHA + "\trefs/tags/" + TAG):
            self.assertEqual(release.remote_tag(TAG), SHA)
            with self.assertRaisesRegex(ValueError, "advertisement"):
                release.available(API([[], []]), TAG)
        for result in ("broken", SHA + "\trefs/tags/" + TAG + "0",
                       SHA + "\trefs/tags/" + TAG + "\n" + SHA + "\trefs/tags/" + TAG):
            with patch.object(release.repository, "run", return_value=result):
                with self.assertRaises(ValueError):
                    release.remote_tag(TAG)
        with patch.object(release.repository, "run",
                          side_effect=subprocess.CalledProcessError(128, ["git", "ls-remote"])):
            with self.assertRaises(subprocess.CalledProcessError):
                release.available(API([[], []]), TAG)

    def test_transport_explicit_methods_payload_encoding_no_retry_or_ambient_calls(self):
        api = release.GitHub()
        with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 0, '{"id":7}', "")) as run:
            self.assertEqual(api.api("POST", BASE + "/releases", {"draft": False}), {"id": 7})
            args, kwargs = run.call_args
            self.assertEqual(args[0][:5], ["gh", "api", "--method", "POST", BASE + "/releases"])
            self.assertEqual(json.loads(kwargs["input"]), {"draft": False})
            self.assertIn("X-GitHub-Api-Version: 2022-11-28", args[0])
            api.api("POST", UPLOAD, asset=Path("UDP-3.2.1.zip"))
            self.assertIn("Content-Type: application/octet-stream", run.call_args.args[0])
        for code, output in ((1, "[]"), (0, "invalid"), (0, '{"id":1,"id":2}'),
                             (0, "[NaN]"), (0, "[Infinity]"), (0, "[1e999]")):
            with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess(
                    [], code, output, "offline failure")) as run:
                with self.assertRaises(ValueError):
                    api.api("GET", BASE + "/releases")
                self.assertEqual(run.call_count, 1)


GH_STUB = r'''#!PYTHON
import json, os, pathlib, subprocess, sys
args = sys.argv[1:]
method, endpoint = args[args.index("--method")+1], args[args.index("--method")+2]
payload = json.load(sys.stdin) if "--input" in args and args[args.index("--input")+1] == "-" else None
with open(os.environ["GH_LOG"], "a") as out:
    out.write(json.dumps({"method":method,"endpoint":endpoint,"payload":payload})+"\n")
state_path = pathlib.Path(os.environ["GH_STATE"])
state = json.loads(state_path.read_text())
mode = os.environ.get("GH_MODE", "")
repo = "miyako/4d-plugin-udp"
upload = "https://uploads.github.com/repos/"+repo+"/releases/789/assets"
if method == "GET" and "/releases?" in endpoint:
    page = int(endpoint.rsplit("page=",1)[1])
    if mode == "later-error" and page == 2:
        sys.exit("HTTP 404")
    result = state.get("pages", [[]])[page-1] if page <= len(state.get("pages",[[]])) else []
elif method == "GET" and "/matching-refs/" in endpoint:
    result = state.get("refs", [])
elif method == "POST" and endpoint.endswith("/git/refs"):
    stage = "tag"
    if mode in ("same-tag-race", "different-tag-race"):
        state["tag"] = payload["sha"] if mode == "same-tag-race" else "b"*40
        state_path.write_text(json.dumps(state))
        if mode == "same-tag-race":
            subprocess.run(["git", "--git-dir", os.environ["GH_BARE_ORIGIN"],
                            "update-ref", payload["ref"], payload["sha"]], check=True)
        sys.exit("HTTP 422 occupied")
    state["tag"] = payload["sha"]
    state["tag_name"] = payload["ref"]
    state_path.write_text(json.dumps(state))
    subprocess.run(["git", "--git-dir", os.environ["GH_BARE_ORIGIN"],
                    "update-ref", payload["ref"], payload["sha"]], check=True)
    if mode == "tag-error":
        sys.exit("HTTP 500 response lost")
    result = {"ref":payload["ref"],"object":{"sha":payload["sha"],"type":"commit"}}
    if mode == "bad-tag":
        result["object"]["sha"] = "b"*40
elif method == "GET" and "/git/ref/tags/" in endpoint:
    stage = "verify"
    if mode == "verify-error":
        sys.exit("HTTP 403")
    result = {"ref":state["tag_name"],"object":{"sha":state["tag"],"type":"commit"}}
    if mode == "bad-verify":
        result["object"]["type"] = "tag"
elif method == "POST" and endpoint.endswith("/releases"):
    stage = "release"
    state["release"] = payload
    state_path.write_text(json.dumps(state))
    if mode == "release-error":
        sys.exit("HTTP 422 response lost")
    result = dict(payload, id=789, upload_url=upload+"{?name,label}")
    if mode == "bad-release":
        result["id"] = True
    elif mode == "reused-id":
        result["id"] = 1
    elif mode == "bad-upload-url":
        result["upload_url"] = "https://invalid.example/assets"
elif method == "POST" and endpoint.startswith(upload+"?name="):
    stage = "upload"
    path = pathlib.Path(args[args.index("--input")+1])
    state.setdefault("uploaded",[]).append(path.name)
    state_path.write_text(json.dumps(state))
    if mode == "upload-"+path.suffix[1:]:
        sys.exit("HTTP 500 response lost")
    result = {"id":45,"name":path.name.replace(" ","."),"size":path.stat().st_size,"state":"uploaded"}
    if mode == "bad-upload":
        result["size"] = True
else:
    sys.exit("UNSTUBBED API OPERATION: "+str(args))
if os.environ.get("GH_OVERRIDE_STAGE") and os.environ["GH_OVERRIDE_STAGE"] == locals().get("stage"):
    result = json.loads(os.environ["GH_OVERRIDE_JSON"])
print(json.dumps(result))
'''


class PublicationCLITests(GitFixture):
    def setUp(self):
        super().setUp()
        self.version = source.read(self.local)
        self.tag = "v" + self.version
        self.output = self.root / "output"
        self.state = self.root / "state.json"
        self.log = self.root / "gh.jsonl"
        self.state.write_text("{}")
        self.tools = self.root / "closed-path"
        self.tools.mkdir()
        for name in ("git", "python3"):
            (self.tools / name).symlink_to(sys.executable if name == "python3" else shutil.which(name))
        upload_pack = shutil.which("git-upload-pack") or (
            Path(subprocess.check_output(["git", "--exec-path"], text=True).strip()) / "git-upload-pack")
        (self.tools / "git-upload-pack").symlink_to(upload_pack)
        fake = self.tools / "gh"
        fake.write_text(GH_STUB.replace("PYTHON", sys.executable))
        fake.chmod(0o755)
        self.env.update(PATH=str(self.tools), GH_TOKEN="offline-fixture-token",
                        GITHUB_REPOSITORY=REPO, GITHUB_OUTPUT=str(self.output),
                        GH_STATE=str(self.state), GH_LOG=str(self.log),
                        GH_BARE_ORIGIN=str(self.bare))
        self.protected = ("native.cpp", "manifest.json", "constants.xlf", ".gitignore",
                          "test/Plugins/UDP.bundle/Contents/Resources/other.dat",
                          "test/Plugins/UDP.bundle/Contents/QuickLook/Thumbnail.png",
                          "test/Plugins/UDP.bundle/Contents/MacOS/runtime.dylib")
        for path in self.protected:
            target = self.local / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(
                b"ignored-source.cpp\nbuild/*\ntest/Plugins/XCBuildData/\n"
                if path == ".gitignore" else b"protected")
        self.generated = tuple(str(path) for path in native.FILES)
        for path in self.generated:
            target = self.local / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"original generated output")
        self.git("add", "-f", ".")
        self.git("commit", "--quiet", "-m", "force-track actual generated native output paths")
        self.sha = self.git("rev-parse", "HEAD")
        self.env["GITHUB_SHA"] = self.sha
        self.git("--git-dir=" + str(self.bare), "fetch", "--quiet", "--no-tags",
                 str(self.local), self.sha)
        self.baseline = {path: (self.local / path).read_bytes()
                         for path in self.protected + tuple(map(str, source.SOURCE_PATHS))}
        self.assertTrue(set(self.generated) <= set(self.git("ls-files").splitlines()))

    def command(self, name, *, mode="", assets=None, extra_env=None):
        args = [name, "--sha", self.sha]
        if name == "publish":
            args.extend(release.asset_names(self.version) if assets is None else assets)
        return self.cli(".github/scripts/release.py", *args,
                        env={**self.env, "GH_MODE": mode, **(extra_env or {})})

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def reset_api(self, state=None):
        self.state.write_text(json.dumps(state or {}))
        self.log.unlink(missing_ok=True)
        self.git("--git-dir=" + str(self.bare), "update-ref", "-d", "refs/tags/" + self.tag)

    def build(self):
        data = {
            self.generated[0]: b"fresh native executable",
            self.generated[1]: plistlib.dumps({source.SHORT: self.version}, fmt=plistlib.FMT_BINARY),
            self.generated[2]: source.text(self.local / source.LOCALIZED).encode("utf-16"),
            str(native.MAC_FILES[-1]): b"fresh signature bytes",
            str(native.FILES[-1]): b"fresh Windows executable",
            "winbuild/UDP.4DX": b"fresh Windows executable",
            "test/Plugins/XCBuildData/build.db": b"fresh Xcode build database",
            "test/Plugins/XCBuildData/build.db-wal": b"fresh Xcode write-ahead log",
            "test/Plugins/XCBuildData/build.db-shm": b"fresh Xcode shared memory",
            "test/Plugins/XCBuildData/0123456789abcdef0123456789abcdef.xcbuilddata/build-request.json":
                b"fresh Xcode request",
            "test/Plugins/UDP.build/Default/UDP.build/UDP.hmap": b"fresh intermediate",
        }
        data.update({path: (self.local / Path(path).name).read_bytes()
                     for path in map(str, native.MAC_FILES[3:-1])})
        for path, raw in data.items():
            target = self.local / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        for path in release.asset_names(self.version):
            (self.local / path).write_bytes(b"fresh package")
        return data

    def test_actual_cli_clean_preflight_then_tracked_native_dirt_publish_retains_exact_bytes(self):
        canonical = "miyako/4d-plugin-udp"
        self.assertEqual(release.REPOSITORY, canonical)
        result = self.command("preflight", extra_env={"GITHUB_REPOSITORY": canonical})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.output.read_text(), f"version={self.version}\ntag={self.tag}\n")
        expected = self.build()
        self.assertNotEqual(self.command("preflight").returncode, 0)
        self.reset_api()
        self.assertEqual(self.command("check").returncode, 0)
        self.assertEqual(self.command("publish", extra_env={
            "GITHUB_REPOSITORY": canonical}).returncode, 0)
        for path, raw in expected.items():
            self.assertEqual((self.local / path).read_bytes(), raw)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.sha)
        self.assertTrue(self.git("status", "--porcelain"))
        calls = self.calls()
        self.assertEqual([call["method"] for call in calls],
                         ["GET", "GET", "GET", "GET", "POST", "GET", "POST", "POST", "POST"])
        self.assertEqual(calls[4]["payload"]["sha"], self.sha)
        self.assertEqual(calls[6]["payload"], {
            "tag_name": self.tag, "name": self.tag, "target_commitish": self.sha,
            "draft": False, "prerelease": False, "body": "", "generate_release_notes": False,
        })
        self.assertTrue(all(call["endpoint"].startswith(UPLOAD + "?name=UDP-")
                            for call in calls[-2:]))

    def test_extracted_native_workflow_real_metadata_without_bytecode_environment_then_publish(self):
        generated = self.build()
        self.assertEqual((self.local / ".github/scripts/source_version.py").read_bytes(),
                         (ROOT / ".github/scripts/source_version.py").read_bytes())
        workflow = yaml.load((ROOT / ".github/workflows/release.yml").read_text(),
                             Loader=yaml.BaseLoader)
        self.assertNotIn("PYTHONDONTWRITEBYTECODE", workflow["env"])
        for name in ("bash", "grep", "head", "sed"):
            (self.tools / name).symlink_to("/bin/bash" if name == "bash" else shutil.which(name))
        for name in ("lipo", "security", "codesign", "ditto", "hdiutil", "xcrun"):
            tool = self.tools / name
            tool.write_text(NATIVE_STUB.replace("PYTHON", sys.executable))
            tool.chmod(0o755)
        native_log = self.root / "native.jsonl"
        env = {**self.env, **workflow["env"], "NATIVE_LOG": str(native_log),
               "GITHUB_ENV": str(self.root / "github.env"), "VERSION": self.version,
               "KEYCHAIN_PATH": str(self.root / "offline.keychain")}
        for key in ("PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX", "PYTHONPATH",
                    "PYTHONHOME", "PYTHONSTARTUP"):
            env.pop(key, None)
        probe = subprocess.run(
            [str(self.tools / "python3"), "-c",
             "import json,sys;print(json.dumps([sys.dont_write_bytecode,"
             "sys.flags.dont_write_bytecode,sys.orig_argv]))"],
            cwd=self.local, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        setting, flag, argv = json.loads(probe.stdout)
        self.assertIs(setting, False)
        self.assertEqual(flag, 0)
        self.assertNotIn("-B", argv)
        for name in release.asset_names(self.version):
            (self.local / name).unlink()
        for name in ("verify universal binary", "merge Windows binaries into the bundle",
                     "codesign", "package, notarize & staple"):
            step = next(s for s in workflow["jobs"]["build-macos"]["steps"]
                        if s.get("name") == name)
            self.assertNotIn("PYTHONDONTWRITEBYTECODE", step.get("env", {}))
            result = subprocess.run(
                ["/bin/bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
                cwd=self.local, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(self.local.rglob("__pycache__")), [])
            self.assertEqual(list(self.local.rglob("*.pyc")), [])
            self.assertEqual(self.calls(), [])
        retained = {str(path.relative_to(self.local)): path.read_bytes()
                    for path in (self.local / native.BUNDLE).rglob("*") if path.is_file()}
        retained.update({name: (self.local / name).read_bytes()
                         for name in (*generated, *release.asset_names(self.version))})
        result = subprocess.run(
            [str(self.tools / "python3"), ".github/scripts/release.py", "publish",
             "--sha", self.sha, *release.asset_names(self.version)],
            cwd=self.local, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.calls())
        self.assertEqual(list(self.local.rglob("__pycache__")), [])
        self.assertEqual(list(self.local.rglob("*.pyc")), [])
        for name, raw in retained.items():
            self.assertEqual((self.local / name).read_bytes(), raw)
        for name, raw in self.baseline.items():
            self.assertEqual((self.local / name).read_bytes(), raw)
        calls = [json.loads(line) for line in native_log.read_text().splitlines()]
        self.assertEqual(sum(call[:3] == ["xcrun", "notarytool", "submit"]
                             for call in calls), 2)
        self.assertTrue(any(call[:3] == ["xcrun", "stapler", "staple"] for call in calls))

    def test_actual_cli_ignored_xcode_database_retained_without_relaxing_source_guards(self):
        self.assertEqual(self.command("preflight").returncode, 0)
        self.reset_api()
        relative = "test/Plugins/XCBuildData/build.db"
        database = self.local / relative
        database.parent.mkdir(parents=True)
        database.write_bytes(b"stale initial database")
        self.assertEqual(self.git("check-ignore", "--", relative), relative)
        self.assertNotEqual(self.command("preflight").returncode, 0)
        self.assertEqual(self.calls(), [])
        database.unlink()

        expected = self.build()
        for path in ("build/unexpected-source.cpp", "test/Plugins/XCBuildData/unexpected-source.cpp",
                     "test/Plugins/XCBuildData/build.db-evil",
                     "test/Plugins/XCBuildData/evil.xcbuilddata/build-request.json"):
            unexpected = self.local / path
            unexpected.parent.mkdir(parents=True, exist_ok=True)
            unexpected.write_bytes(b"ignored source is not a generated database")
            self.assertEqual(self.git("check-ignore", "--", path), path)
            self.assertNotEqual(self.command("publish").returncode, 0)
            self.assertEqual(self.calls(), [])
            unexpected.unlink()
            if unexpected.parent.name == "evil.xcbuilddata":
                unexpected.parent.rmdir()
        config = self.local / ".gitignore"
        config.write_bytes(self.baseline[".gitignore"] + b"unexpected-config\n")
        self.git("add", "--", ".gitignore")
        config.write_bytes(self.baseline[".gitignore"])
        self.assertNotEqual(self.command("publish").returncode, 0)
        self.assertEqual(self.calls(), [])
        self.git("add", "--", ".gitignore")

        result = self.command("publish")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(database.read_bytes(), expected[relative])
        self.assertEqual(self.git("check-ignore", "--", relative), relative)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.sha)
        for path, raw in self.baseline.items():
            self.assertEqual((self.local / path).read_bytes(), raw)
        for path, raw in expected.items():
            self.assertEqual((self.local / path).read_bytes(), raw)

    def test_each_source_config_staged_unstaged_reversed_hidden_flag_fails_before_api(self):
        self.build()
        for path in self.baseline:
            for stage in ("unstaged", "staged", "reversed", "assume-unchanged", "skip-worktree"):
                with self.subTest(path=path, stage=stage):
                    self.reset_api()
                    target = self.local / path
                    if stage in ("assume-unchanged", "skip-worktree"):
                        self.git("update-index", "--" + stage, "--", path)
                    target.write_bytes(self.baseline[path] + b" altered")
                    if stage in ("staged", "reversed"):
                        self.git("add", "--", path)
                    if stage == "reversed":
                        target.write_bytes(self.baseline[path])
                    result = self.command("publish")
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertEqual(self.calls(), [], result.stderr)
                    if stage in ("assume-unchanged", "skip-worktree"):
                        self.git("update-index", "--no-" + stage, "--", path)
                    target.write_bytes(self.baseline[path])
                    self.git("add", "--", path)

    def test_head_source_version_wrong_repo_and_explicit_auth_fail_before_api(self):
        self.build()
        for env in ({"GH_TOKEN": ""}, {"GH_TOKEN": " ", "GITHUB_TOKEN": "\t"},
                    {"GITHUB_REPOSITORY": "miyako/4d-plugin-uti"},
                    {"GITHUB_REPOSITORY": "miyako/4d-plugin-UDP"},
                    {"GITHUB_REPOSITORY": "owner/other"}, {"GITHUB_SHA": "b" * 40}):
            result = self.command("publish", extra_env=env)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.calls(), [])
        self.git("commit", "--quiet", "--allow-empty", "-m", "changed HEAD")
        result = self.command("publish")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_hidden_index_flags_fail_even_when_bytes_match_selected(self):
        for flag in ("assume-unchanged", "skip-worktree"):
            self.git("update-index", "--" + flag, "--", "native.cpp")
            self.assertNotEqual(self.command("preflight").returncode, 0)
            self.assertEqual(self.calls(), [])
            self.git("update-index", "--no-" + flag, "--", "native.cpp")
        self.build()
        for flag in ("assume-unchanged", "skip-worktree"):
            self.git("update-index", "--" + flag, "--", self.generated[0])
            self.assertNotEqual(self.command("publish").returncode, 0)
            self.assertEqual(self.calls(), [])
            self.git("update-index", "--no-" + flag, "--", self.generated[0])

    def test_actual_fsmonitor_H_under_v_h_under_f_source_and_final_cli_fail_before_api(self):
        for operation, path in (("preflight", "native.cpp"), ("publish", self.generated[0])):
            self.git("config", "core.fsmonitor", "true")
            if operation == "publish":
                self.build()
            self.git("update-index", "--fsmonitor-valid", "--", path)
            self.assertEqual(self.git("ls-files", "-v", "--", path), "H " + path)
            self.assertEqual(self.git("ls-files", "-f", "--", path), "h " + path)
            result = self.command(operation)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Hidden index/stat flags", result.stderr)
            self.assertEqual(self.calls(), [])
            self.git("config", "core.fsmonitor", "false")
            self.git("update-index", "--no-fsmonitor-valid", "--",
                     *self.git("ls-files").splitlines())
            result = self.command("preflight" if operation == "preflight" else "check")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(self.calls())
            self.reset_api()

    def windows_checkout(self):
        self.git("config", "core.filemode", "false")
        self.git("update-index", "--chmod=+x", "--", "native.cpp",
                 *map(str, source.SOURCE_PATHS))
        self.git("commit", "--quiet", "-m", "committed executable fixture")
        self.sha = self.git("rev-parse", "HEAD")
        self.env["GITHUB_SHA"] = self.sha
        self.git("--git-dir=" + str(self.bare), "fetch", "--quiet", "--no-tags",
                 str(self.local), self.sha)
        for record in self.git("ls-files", "--stage").splitlines():
            if record.startswith("100755 "):
                (self.local / record.split("\t")[1]).chmod(0o644)
        self.bootstrap = self.root / "windows-cli.py"
        self.bootstrap.write_text('''
import os
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace
sys.path.insert(0, str(Path(".github/scripts").resolve()))
import repository
repository.sys = SimpleNamespace(platform=os.environ["TEST_PLATFORM"])
if os.environ.get("TEST_REPARSE"):
    original = Path.lstat
    def lstat(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if str(path) == os.environ["TEST_REPARSE"]:
            return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x400)
        return result
    Path.lstat = lstat
sys.argv = [".github/scripts/release.py", "preflight", "--sha", os.environ["GITHUB_SHA"]]
runpy.run_path(sys.argv[0], run_name="__main__")
''')

    def windows_preflight(self, *, platform="win32", reparse=""):
        return subprocess.run(
            [sys.executable, str(self.bootstrap)], cwd=self.local,
            env={**self.env, "TEST_PLATFORM": platform, "TEST_REPARSE": reparse},
            capture_output=True, text=True, timeout=60)

    def test_windows_only_regular_mode_tolerance_and_raw_index_type_reparse_matrix(self):
        self.windows_checkout()
        self.assert_windows_matrix()

    def assert_windows_matrix(self, global_fixture=None):
        def positive():
            result = self.windows_preflight()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(self.calls()), 2)
            self.reset_api()
            if global_fixture:
                path, raw = global_fixture
                self.assertEqual(path.read_bytes(), raw)

        result = self.windows_preflight()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls()), 2)
        for path in ("native.cpp", ".github/hooks/pre-push", *map(str, source.SOURCE_PATHS)):
            self.assertTrue(self.git("ls-files", "--stage", "--", path).startswith("100755 "))
            self.assertFalse((self.local / path).stat().st_mode & 0o111)
        self.reset_api()
        for platform in ("darwin", "linux"):
            self.assertNotEqual(self.windows_preflight(platform=platform).returncode, 0)
            self.assertEqual(self.calls(), [])
            positive()
        target = self.local / "native.cpp"
        raw = target.read_bytes()
        for kind in ("raw", "staged", "reversed", "indexmode",
                     "assume-unchanged", "skip-worktree", "fsmonitor-valid"):
            with self.subTest(kind=kind):
                if kind == "indexmode":
                    self.git("update-index", "--chmod=-x", "--", "native.cpp")
                elif kind in ("assume-unchanged", "skip-worktree", "fsmonitor-valid"):
                    if kind == "fsmonitor-valid":
                        self.git("config", "core.fsmonitor", "true")
                    self.git("update-index", "--" + kind, "--", "native.cpp")
                    if kind == "fsmonitor-valid":
                        self.assertEqual(self.git("ls-files", "-v", "--", "native.cpp"),
                                         "H native.cpp")
                        self.assertEqual(self.git("ls-files", "-f", "--", "native.cpp"),
                                         "h native.cpp")
                else:
                    target.write_bytes(raw + b" altered")
                    if kind in ("staged", "reversed"):
                        self.git("add", "--", "native.cpp")
                    if kind == "reversed":
                        target.write_bytes(raw)
                self.assertNotEqual(self.windows_preflight().returncode, 0)
                self.assertEqual(self.calls(), [])
                if kind == "fsmonitor-valid":
                    self.git("config", "core.fsmonitor", "false")
                    self.git("update-index", "--no-fsmonitor-valid", "--",
                             *self.git("ls-files").splitlines())
                elif kind in ("assume-unchanged", "skip-worktree"):
                    self.git("update-index", "--no-" + kind, "--", "native.cpp")
                target.write_bytes(raw)
                self.git("add", "--", "native.cpp")
                self.git("update-index", "--chmod=+x", "--", "native.cpp")
                positive()
        outside = self.root / "same-bytes.cpp"
        outside.write_bytes(raw)
        target.unlink()
        target.symlink_to(outside)
        self.assertNotEqual(self.windows_preflight().returncode, 0)
        self.assertEqual(self.calls(), [])
        target.unlink()
        target.write_bytes(raw)
        positive()
        target.unlink()
        target.mkdir()
        self.assertNotEqual(self.windows_preflight().returncode, 0)
        self.assertEqual(self.calls(), [])
        target.rmdir()
        target.write_bytes(raw)
        positive()
        for reparse in ("native.cpp", ".github"):
            self.assertNotEqual(self.windows_preflight(reparse=reparse).returncode, 0)
            self.assertEqual(self.calls(), [])
            positive()

    def test_actual_clone_hostile_fixture_global_before_checkout_false_and_late_negative(self):
        self.windows_checkout()
        ending = self.local / "line-endings.txt"
        ending.write_bytes(b"first\nsecond\n")
        self.git("add", "--", ending.name)
        self.git("commit", "--quiet", "-m", "LF clone fixture")
        self.sha = self.git("rev-parse", "HEAD")
        self.env["GITHUB_SHA"] = self.sha
        host = self.root / "host.gitconfig"
        raw = b"[core]\n\tautocrlf = true\n"
        host.write_bytes(raw)
        scoped = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.autocrlf",
                  "GIT_CONFIG_VALUE_0": "false"}
        original_local, original_env = self.local, self.env
        selected = self.git("ls-tree", "-r", "-z", self.sha, "--")
        for before in (False, True):
            checkout = self.root / ("scoped-clone" if before else "host-clone")
            environment = {**original_env, "GIT_CONFIG_GLOBAL": str(host),
                           **(scoped if before else {})}
            result = subprocess.run(
                ["git", "clone", "--quiet", "--no-tags", "--no-hardlinks",
                 str(original_local), str(checkout)], env=environment,
                capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.local, self.env = checkout, {**environment, **scoped}
            self.assertEqual(self.git("ls-tree", "-r", "-z", "HEAD", "--"), selected)
            self.git("config", "core.filemode", "false")
            for record in self.git("ls-files", "--stage").splitlines():
                if record.startswith("100755 "):
                    (checkout / record.split("\t")[1]).chmod(0o644)
            for record in selected.split("\0"):
                if not record:
                    continue
                metadata, path = record.split("\t")
                mode, kind, oid = metadata.split()
                self.assertEqual(self.git("ls-files", "--stage", "--", path),
                                 f"{mode} {oid} 0\t{path}")
                if before:
                    self.assertEqual((checkout / path).read_bytes(),
                                     subprocess.check_output(
                                         ["git", "cat-file", "blob", oid],
                                         cwd=checkout, env=self.env))
            self.assertEqual((checkout / ending.name).read_bytes(),
                             b"first\nsecond\n" if before else b"first\r\nsecond\r\n")
            result = self.windows_preflight()
            if before:
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len(self.calls()), 2)
            else:
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.calls(), [])
            self.log.unlink(missing_ok=True)
            self.assertEqual(host.read_bytes(), raw)
            if before:
                self.assert_windows_matrix(global_fixture=(host, raw))
                self.assertEqual(host.read_bytes(), raw)
        self.local, self.env = original_local, original_env

    def test_extracted_windows_source_preflight_actual_cli_inherits_workflow_checkout_config(self):
        self.windows_checkout()
        workflow = yaml.load((ROOT / ".github/workflows/release.yml").read_text(),
                             Loader=yaml.BaseLoader)
        step = next(step for step in workflow["jobs"]["build-windows"]["steps"]
                    if "release.py preflight" in step.get("run", ""))
        self.assertEqual(step["shell"], "bash")
        self.assertEqual(step["env"]["GH_TOKEN"], "${{ github.token }}")
        python = self.tools / "python3"
        python.unlink()
        python.write_text(
            f"#!{sys.executable}\nimport os,sys\n"
            f"os.execv({sys.executable!r}, [{sys.executable!r}, {str(self.bootstrap)!r}])\n")
        python.chmod(0o755)
        env = {**self.env, **workflow["env"], "TEST_PLATFORM": "win32", "TEST_REPARSE": ""}
        args = ["/bin/bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]]
        result = subprocess.run(args, cwd=self.local, env=env,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls()), 2)
        self.log.unlink()
        (self.local / "native.cpp").write_bytes(b"raw mutation")
        result = subprocess.run(args, cwd=self.local, env=env,
                                capture_output=True, text=True, timeout=60)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_generated_index_reversal_and_generated_symlinks_fail_before_api(self):
        self.build()
        target = self.local / self.generated[0]
        fresh = target.read_bytes()
        self.git("add", "--", self.generated[0])
        target.write_bytes(b"original generated output")
        self.assertNotEqual(self.command("publish").returncode, 0)
        self.assertEqual(self.calls(), [])
        self.git("restore", "--staged", "--", self.generated[0])
        target.write_bytes(fresh)
        external = self.root / "external-generated"
        external.write_bytes(fresh)
        target.unlink()
        target.symlink_to(external)
        self.assertNotEqual(self.command("publish").returncode, 0)
        self.assertEqual(self.calls(), [])
        target.unlink()
        target.write_bytes(fresh)
        directory = self.local / "test/Plugins/XCBuildData"
        (directory / "external-link").symlink_to(external)
        self.assertNotEqual(self.command("publish").returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_final_builtin_metadata_drift_missing_or_invalid_fails_before_api(self):
        self.build()
        for path in self.generated[1:3]:
            target = self.local / path
            saved = target.read_bytes()
            for raw in (None, b"", plistlib.dumps({source.SHORT: "900.800.700"})):
                with self.subTest(path=path, raw=raw):
                    if raw is None:
                        target.unlink()
                    else:
                        target.write_bytes(raw)
                    result = self.command("publish")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(self.calls(), [])
                    target.write_bytes(saved)

    def test_final_copied_resource_drift_fails_before_api(self):
        self.build()
        for name in ("manifest.json", "constants.xlf"):
            target = self.local / native.BUNDLE / "Contents/Resources" / name
            saved = target.read_bytes()
            target.write_bytes(b"changed after native verification")
            self.assertNotEqual(self.command("publish").returncode, 0)
            self.assertEqual(self.calls(), [])
            target.write_bytes(saved)

    def test_actual_final_cli_all_packaged_leaves_wrong_types_empty_absent_then_restored(self):
        expected = self.build()
        leaves = sorted(path for path in (self.local / native.BUNDLE).rglob("*") if path.is_file())
        self.assertTrue(leaves)
        for target in leaves:
            saved, mode = target.read_bytes(), target.stat().st_mode
            for kind in ("missing", "empty", "directory", "same-bytes-symlink"):
                with self.subTest(path=target.relative_to(self.local), kind=kind):
                    target.unlink()
                    outside = self.root / "same-bytes-packaged-leaf"
                    if kind == "empty":
                        target.write_bytes(b"")
                    elif kind == "directory":
                        target.mkdir()
                    elif kind == "same-bytes-symlink":
                        outside.write_bytes(saved)
                        target.symlink_to(outside)
                    result = self.command("publish")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(self.calls(), [])
                    if target.is_symlink() or target.is_file():
                        target.unlink()
                    elif target.is_dir():
                        target.rmdir()
                    target.write_bytes(saved)
                    target.chmod(mode)
        result = self.command("publish")
        self.assertEqual(result.returncode, 0, result.stderr)
        for path, raw in expected.items():
            self.assertEqual((self.local / path).read_bytes(), raw)

    def test_final_downloaded_windows_mismatch_fails_before_api_then_restored(self):
        self.build()
        downloaded = self.local / "winbuild/UDP.4DX"
        merged = self.local / native.BUNDLE / "Contents/Windows64/UDP.4DX"
        self.assertEqual(downloaded.read_bytes(), merged.read_bytes())
        raw = downloaded.read_bytes()
        downloaded.write_bytes(raw + b" altered artifact")
        result = self.command("publish")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), [])
        downloaded.write_bytes(raw)
        result = self.command("publish")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(downloaded.read_bytes(), raw)
        self.assertEqual(merged.read_bytes(), raw)

    def test_untracked_ignored_source_config_and_unproven_outputs_fail_before_api(self):
        self.build()
        for name in ("injected.cpp", "ignored-source.cpp", "build/other/injected",
                     "test/Plugins/Default/keep", "UDP-wrong.zip"):
            target = self.local / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"untracked source/config")
            self.assertNotEqual(self.command("publish").returncode, 0)
            self.assertEqual(self.calls(), [])
            target.unlink()

    def test_tracked_rename_deletion_type_and_index_modes_fail_before_api(self):
        self.build()
        path = self.protected[0]
        target = self.local / path
        target.rename(target.with_name("renamed.cpp"))
        self.assertNotEqual(self.command("publish").returncode, 0)
        self.assertEqual(self.calls(), [])
        target.with_name("renamed.cpp").rename(target)
        target.unlink()
        self.assertNotEqual(self.command("publish").returncode, 0)
        self.assertEqual(self.calls(), [])
        target.write_bytes(self.baseline[path])
        target.chmod(0o755)
        self.assertNotEqual(self.command("publish").returncode, 0)
        target.chmod(0o644)
        self.git("update-index", "--chmod=+x", "--", path)
        self.assertNotEqual(self.command("publish").returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_same_bytes_behind_a_symlink_directory_are_not_a_clean_checkout(self):
        self.build()
        directory = self.local / "test/Plugins/UDP.bundle/Contents/QuickLook"
        moved = self.root / "symlink-resource"
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
        self.assertNotEqual(self.command("publish").returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_raw_bytes_are_not_hidden_by_a_git_clean_filter(self):
        clean_filter = self.root / "clean-filter.py"
        clean_filter.write_text("import sys\nsys.stdin.buffer.read()\nsys.stdout.buffer.write(b'protected')\n")
        (self.local / ".gitattributes").write_text("native.cpp filter=fixture-mask\n")
        self.git("config", "filter.fixture-mask.clean",
                 f'"{sys.executable}" "{clean_filter}"')
        self.git("add", ".gitattributes")
        self.git("commit", "--quiet", "-m", "selected fixture clean filter")
        self.sha = self.git("rev-parse", "HEAD")
        self.env["GITHUB_SHA"] = self.sha
        self.git("--git-dir=" + str(self.bare), "fetch", "--quiet", "--no-tags",
                 str(self.local), self.sha)
        self.assertEqual(self.command("preflight").returncode, 0)
        self.reset_api()
        self.build()
        (self.local / "native.cpp").write_bytes(b"raw byte mutation masked by clean filter")
        self.assertEqual(self.git("diff", "--name-only", self.sha, "--", "native.cpp"), "")
        result = self.command("publish")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Working source/config differs", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_every_controlled_intermediate_is_allowed_but_siblings_are_not(self):
        self.build()
        result = self.command("check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.reset_api()
        for name in ("test/Plugins/XCBuildData-evil/build.db",
                     "test/Plugins/UDP.build-evil/injected",
                     "test/Plugins/UDP.build/nested/generated",
                     "test/Plugins/Default/UDP.bundle/Contents/Info.plist"):
            target = self.local / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"not a proven output")
            self.assertNotEqual(self.command("check").returncode, 0)
            self.assertEqual(self.calls(), [])
            target.unlink()

    def test_exact_asset_arguments_regular_nonempty_symlink_and_alias_rejection(self):
        self.build()
        names = release.asset_names(self.version)
        bad = ([], names[:1], names + names[:1], list(reversed(names)),
               [names[0], names[0]], [str(self.local / name) for name in names],
               ["nested/" + name for name in names], ["./" + name for name in names])
        for assets in bad:
            with self.subTest(assets=assets):
                self.assertNotEqual(self.command("publish", assets=assets).returncode, 0)
                self.assertEqual(self.calls(), [])
        path = self.local / names[0]
        path.write_bytes(b"")
        self.assertNotEqual(self.command("publish").returncode, 0)
        self.assertEqual(self.calls(), [])
        path.unlink()
        path.symlink_to(names[1])
        self.assertNotEqual(self.command("publish").returncode, 0)
        self.assertEqual(self.calls(), [])
        path.unlink()
        path.mkdir()
        self.assertNotEqual(self.command("publish").returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_late_occupancy_and_later_page_errors_stop_before_any_post(self):
        self.assertEqual(self.command("preflight").returncode, 0)
        self.build()
        for state, mode in (({"pages": [[entry(1, self.tag, True)], []]}, ""),
                            ({"refs": [ref(self.tag, self.sha)]}, ""),
                            ({"pages": [[entry(1)], []]}, "later-error")):
            self.reset_api(state)
            self.assertNotEqual(self.command("publish", mode=mode).returncode, 0)
            self.assertTrue(all(call["method"] == "GET" for call in self.calls()))

    def test_tag_races_and_partial_failure_retention_no_retry_or_rollback(self):
        self.build()
        for mode, count, has_release in (
            ("same-tag-race", 3, False), ("different-tag-race", 3, False),
            ("tag-error", 3, False), ("bad-tag", 3, False),
            ("verify-error", 4, False), ("bad-verify", 4, False),
            ("release-error", 5, True), ("bad-release", 5, True),
            ("bad-upload-url", 5, True), ("upload-zip", 6, True),
            ("bad-upload", 6, True), ("upload-dmg", 7, True),
        ):
            with self.subTest(mode=mode):
                self.reset_api()
                expected = {path: (self.local / path).read_bytes() for path in self.generated}
                result = self.command("publish", mode=mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Manual recovery required", result.stderr)
                self.assertEqual(len(self.calls()), count)
                state = json.loads(self.state.read_text())
                self.assertIn("tag", state)
                self.assertEqual("release" in state, has_release)
                self.assertFalse(any(call["method"] in ("PATCH", "DELETE") for call in self.calls()))
                for path, raw in expected.items():
                    self.assertEqual((self.local / path).read_bytes(), raw)
                if mode == "upload-dmg":
                    self.assertIn(release.asset_names(self.version)[0], state["uploaded"])
                    self.assertIn("release ID 789 retained", result.stderr)

    def test_new_release_id_cannot_be_a_preexisting_release_id(self):
        self.build()
        self.reset_api({"pages": [[entry(1)], []]})
        result = self.command("publish", mode="reused-id")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reused", result.stderr)
        self.assertFalse(any("/assets?name=" in call["endpoint"] for call in self.calls()))

    def test_every_malformed_creation_or_verification_response_retains_state(self):
        self.build()
        proper_ref = ref(self.tag, self.sha)
        proper_release = {
            "id": 789, "tag_name": self.tag, "name": self.tag,
            "target_commitish": self.sha, "draft": False, "prerelease": False,
            "body": "", "upload_url": UPLOAD + "{?name,label}",
        }
        name = release.asset_names(self.version)[0]
        proper_upload = {
            "id": 45, "name": name.replace(" ", "."), "size": (self.local / name).stat().st_size,
            "state": "uploaded",
        }
        ref_variants = [
            None, [], {}, dict(proper_ref, ref="refs/tags/wrong"),
            dict(proper_ref, object={"sha": "short", "type": "commit"}),
            dict(proper_ref, object={"sha": self.sha, "type": "tag"}),
        ]
        release_variants = [
            None, [], {},
            *(dict(proper_release, **{key: value}) for key, value in (
                ("id", True), ("id", 0), ("id", "789"), ("tag_name", "v900.800.700"),
                ("name", "wrong"), ("target_commitish", "b" * 40), ("draft", True),
                ("draft", 0), ("prerelease", True), ("body", "unexpected notes"),
                ("upload_url", "https://invalid.example/assets"),
            )),
        ]
        upload_variants = [
            None, [], {},
            *(dict(proper_upload, **{key: value}) for key, value in (
                ("id", True), ("id", 0), ("name", "wrong"), ("size", True),
                ("size", str(proper_upload["size"])), ("size", 0), ("state", "new"),
            )),
        ]
        for stage, variants, expected_calls in (
            ("tag", ref_variants, 3), ("verify", ref_variants, 4),
            ("release", release_variants, 5), ("upload", upload_variants, 6),
        ):
            for value in variants:
                with self.subTest(stage=stage, value=value):
                    self.reset_api()
                    result = self.command("publish", extra_env={
                        "GH_OVERRIDE_STAGE": stage, "GH_OVERRIDE_JSON": json.dumps(value),
                    })
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("Manual recovery required", result.stderr)
                    self.assertEqual(len(self.calls()), expected_calls)
                    self.assertFalse(any(call["method"] in ("PATCH", "DELETE")
                                         for call in self.calls()))
                    state = json.loads(self.state.read_text())
                    self.assertIn("tag", state)
                    self.assertEqual("release" in state, stage in ("release", "upload"))
