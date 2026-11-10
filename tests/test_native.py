"""Run actual production native CLI phases only with a closed stub PATH."""

import io
import json
from pathlib import Path
import plistlib
import shutil
import sys
from unittest import mock

import yaml

from native_support import ROOT, NativeFixture, cwd, native
from helper_support import GitFixture, source


class NativeTests(NativeFixture):
    def test_selective_cleanup_and_repeated_build_preserve_original_siblings(self):
        protected = (
            "build/UDP.build/Default/historical", "build/XCBuildData/build.db",
            "test/plugins/sibling", "test/Plugins/Default/keep",
            native.BUNDLE / "Contents/QuickLook/Thumbnail.png",
            native.BUNDLE / "Contents/Resources/custom.txt",
            native.WINDOWS_BINARY, "lib/windows64/jsoncpp.lib",
        )
        for path in protected:
            self.write(path)
        self.write(native.DIRECTORIES[0] / "Default/UDP.build/Objects-normal/arm64/C_TEXT.o", b"stale")
        self.write(native.XCODE_DATA / "build.db", b"stale")
        self.phase("build")
        self.phase("build")
        for path in protected:
            self.assertEqual((self.root / path).read_bytes(), b"retained")
        self.phase("verify")
        self.assertEqual([x[0] for x in self.calls()].count("xcodebuild"), 2)

    def test_all_cleanup_targets_prevalidated_before_first_delete_and_restored_positive(self):
        early = native.MAC_FILES[0]
        late = native.XCODE_DATA / "build.db"
        cases = ("file-is-dir", "dir-is-file", "unreadable", "link", "dangling",
                 "nested-git", "unexpected", "fifo", "ancestor-link", "descendant-dir")
        for case in cases:
            with self.subTest(case=case):
                self.populated()
                self.write(late, b"late retained")
                early_path = self.root / early
                late_path = self.root / late
                restore = lambda: None
                if case == "file-is-dir":
                    late_path.unlink()
                    late_path.mkdir()
                elif case == "dir-is-file":
                    shutil.rmtree(self.root / native.XCODE_DATA)
                    self.write(native.XCODE_DATA, b"late retained")
                elif case == "unreadable":
                    late_path.chmod(0)
                    restore = lambda: late_path.chmod(0o644)
                elif case in ("link", "dangling"):
                    late_path.unlink()
                    late_path.symlink_to(early_path if case == "link" else self.root / "absent")
                elif case == "nested-git":
                    self.write(native.DIRECTORIES[0] / ".git", b"gitdir: forbidden")
                elif case == "unexpected":
                    self.write(native.XCODE_DATA / "build.db-evil")
                elif case == "fifo":
                    import os
                    late_path.unlink()
                    os.mkfifo(late_path)
                elif case == "ancestor-link":
                    parent = self.root / native.XCODE_DATA
                    parent.rename(self.root / "moved-data")
                    parent.symlink_to(self.root / "moved-data", target_is_directory=True)
                else:
                    self.write(native.DIRECTORIES[0] / "Default/UDP.build/Objects-normal/arm64/C_TEXT.o")
                    leaf = self.root / native.DIRECTORIES[0] / "Default/UDP.build/Objects-normal/arm64/C_TEXT.o"
                    leaf.unlink()
                    leaf.mkdir()
                self.log.unlink(missing_ok=True)
                self.phase("build", success=False)
                self.assertEqual(early_path.read_bytes(), b"fresh " + str(early).encode())
                self.assert_no_native()
                restore()
                if case not in ("file-is-dir", "link", "dangling", "fifo", "dir-is-file"):
                    self.assertEqual(late_path.read_bytes(), b"late retained")
                for directory in (*native.DIRECTORIES, native.XCODE_DATA):
                    target = self.root / directory
                    if target.is_symlink() or target.is_file() or (target.exists() and not target.is_dir()):
                        target.unlink()
                    elif target.exists():
                        shutil.rmtree(target)
                self.phase("build")
                self.assertEqual(early_path.read_bytes(), b"fresh native")

    def test_inaccessible_late_directory_and_unwritable_parent_precede_any_deletion(self):
        early = self.write(native.MAC_FILES[0], b"earlier")
        late = self.write(native.XCODE_DATA / "build.db", b"later")
        for mode in (0, 0o555):
            with self.subTest(mode=mode):
                late.parent.chmod(mode)
                try:
                    self.phase("build", success=False)
                    self.assertEqual(early.read_bytes(), b"earlier")
                    self.assert_no_native()
                finally:
                    late.parent.chmod(0o755)
                self.assertEqual(late.read_bytes(), b"later")
        self.phase("build")

    def test_tracked_intermediate_is_not_deleted(self):
        early = self.write(native.MAC_FILES[0], b"early")
        late = self.write(native.DIRECTORIES[0] / "Default/UDP.build/PkgInfo", b"indexed")
        self.git("add", str(late.relative_to(self.root)))
        self.phase("build", success=False)
        self.assertEqual(early.read_bytes(), b"early")
        self.assertEqual(late.read_bytes(), b"indexed")
        self.assert_no_native()
        self.git("commit", "--quiet", "-m", "selected intermediate input")
        self.git("rm", "--cached", "--quiet", "--", str(late.relative_to(self.root)))
        self.phase("build", success=False)
        self.assertEqual(early.read_bytes(), b"early")
        self.assertEqual(late.read_bytes(), b"indexed")
        self.assert_no_native()

    def test_narrow_intermediate_classifier_including_empty_directory_families(self):
        yes = (
            native.XCODE_DATA / "build.db", native.XCODE_DATA / "build.db-wal",
            native.XCODE_DATA / "build.db-shm",
            native.XCODE_DATA / ("1" * 32 + ".xcbuilddata/build-request.json"),
            native.DIRECTORIES[0] / "Default/UDP.build/Objects-normal/arm64/C_TEXT.o",
            native.DIRECTORIES[0] / "Default/UDP.build/Objects-normal/x86_64/Binary/UDP",
        )
        no = (
            "build/XCBuildData/build.db", native.XCODE_DATA / "build.db-evil",
            native.XCODE_DATA / "evil.xcbuilddata/source.cpp",
            native.XCODE_DATA / "unexpected-source.cpp",
            "test/Plugins/XCBuildData-evil/build.db",
            native.DIRECTORIES[0] / "Default/UDP.build/JavaClasses/arbitrary.class",
            native.DIRECTORIES[0] / "DerivedSources/unexpected-source.cpp",
            native.DIRECTORIES[0] / "Default/UDP.build/Objects-normal/arm64/source.cpp",
        )
        for path in yes:
            self.assertTrue(native.generated(str(path)), path)
        for path in no:
            self.assertFalse(native.generated(str(path)), path)
        self.write(native.DIRECTORIES[0] / "Default/UDP.build/JavaClasses/arbitrary.class")
        self.phase("build", success=False)
        self.assert_no_native()

    def test_exact_lipo_tokens_require_both_but_permit_original_extra_architectures(self):
        self.phase("build")
        for architectures in ("arm64", "x86_64", "notarm64 x86_64", "arm64 x86_64evil"):
            self.phase("verify", success=False, ARCHS=architectures)
        self.phase("verify", ARCHS="arm64 x86_64 i386")
        self.phase("verify", success=False, FAIL_TOOL="lipo")

    def test_unsigned_gate_then_full_build_merge_sign_package_order(self):
        self.phase("build")
        self.phase("verify")
        self.write(native.DOWNLOADS[0], b"downloaded fresh")
        self.phase("merge-windows")
        self.phase("sign")
        self.phase("package")
        self.assertEqual((self.root / native.WINDOWS_BINARY).read_bytes(), b"downloaded fresh")
        self.assertEqual((self.root / "UDP-2.1.3.zip").read_bytes(), b"zip")
        self.assertEqual((self.root / "UDP-2.1.3.dmg").read_bytes(), b"dmg")
        calls = self.calls()
        self.assertEqual(sum(c[:3] == ["xcrun", "notarytool", "submit"] for c in calls), 2)
        self.assertTrue(any(c[:3] == ["xcrun", "stapler", "staple"] for c in calls))
        self.assertFalse(any(c[0] == "gh" for c in calls))
        self.assertEqual((self.root / "github.env").read_text().splitlines()[-2:],
                         ["ZIP_PATH=UDP-2.1.3.zip", "DMG_PATH=UDP-2.1.3.dmg"])

    def test_each_packaged_leaf_missing_empty_directory_samebytes_link_before_any_native(self):
        for leaf in native.FILES:
            for mutation in ("missing", "empty", "directory", "samebytes-link"):
                with self.subTest(leaf=leaf, mutation=mutation):
                    self.populated()
                    path = self.root / leaf
                    data = path.read_bytes()
                    path.unlink()
                    if mutation == "empty":
                        path.write_bytes(b"")
                    elif mutation == "directory":
                        path.mkdir()
                    elif mutation == "samebytes-link":
                        destination = self.write("samebytes", data)
                        path.symlink_to(destination)
                    self.log.unlink(missing_ok=True)
                    self.phase("package", success=False)
                    self.assert_no_native()
                    if path.is_symlink():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                    path.write_bytes(data)
                    with cwd(self.root), mock.patch.dict(sys.modules, {"source_version": mock.Mock()}):
                        native.verify_resources()
                    self.assertEqual(path.read_bytes(), data)

    def test_exact_source_resources_and_download_equality_precede_package_tools(self):
        for leaf in (native.BUNDLE / "Contents/Resources/constants.xlf",
                     native.BUNDLE / "Contents/Resources/manifest.json",
                     native.WINDOWS_BINARY, native.DOWNLOADS[0]):
            self.populated()
            self.write(leaf, b"corrupted")
            self.phase("package", success=False)
            self.assert_no_native()

    def test_strict_notary_json_exit_and_staple_sign_failures(self):
        malformed = ('{"status":"Rejected"}', '{"status":"Accepted","status":"Accepted"}',
                     '{"status":"Accepted","n":NaN}', '{"status":"Accepted","n":1e999}',
                     '["Accepted"]', 'not json', '{"status":"Accepted"} trailing')
        for response in malformed:
            with self.assertRaises((ValueError, TypeError)):
                native.accepted(io.StringIO(response))
        native.accepted(io.StringIO('{"status":"Accepted"}'))
        for env in ({"NOTARY_JSON": '{"status":"Rejected"}'},
                    {"NOTARY_EXIT": "17"}, {"FAIL_TOOL": "xcrun"},
                    {"FAIL_TOOL": "codesign"}, {"STAPLE_EXIT": "19"}):
            self.populated()
            for name in ("UDP-2.1.3.zip", "UDP-2.1.3.dmg"):
                (self.root / name).unlink(missing_ok=True)
            self.log.unlink(missing_ok=True)
            self.phase("package", success=False, **env)
            self.assertFalse(any(c[0] == "gh" for c in self.calls()))

    def test_merge_prevalidates_download_and_destination_types_before_any_copy(self):
        for case in ("missing", "empty", "directory", "link", "ancestor-link"):
            self.populated()
            source = self.root / native.DOWNLOADS[0]
            destination = self.root / native.WINDOWS_BINARY
            retained = destination.read_bytes()
            if case == "missing":
                source.unlink()
            elif case == "empty":
                source.write_bytes(b"")
            elif case == "directory":
                source.unlink()
                source.mkdir()
            elif case == "link":
                source.unlink()
                source.symlink_to(destination)
            else:
                parent = source.parent
                parent.rename(self.root / "download-moved")
                parent.symlink_to(self.root / "download-moved", target_is_directory=True)
            self.phase("merge-windows", success=False)
            self.assertEqual(destination.read_bytes(), retained)
            self.assert_no_native()
            if source.parent.is_symlink():
                source.parent.unlink()
            elif source.is_symlink() or source.is_file():
                source.unlink()
            elif source.exists():
                source.rmdir()
        self.write(native.DOWNLOADS[0], b"fresh downloaded")
        self.phase("merge-windows")
        self.assertEqual((self.root / native.WINDOWS_BINARY).read_bytes(), b"fresh downloaded")

    def test_credential_phases_use_only_closed_stub_path_and_fake_values(self):
        self.phase("import-certificate")
        self.phase("store-credentials")
        self.assertEqual((self.root / "runner/certificate.p12").read_bytes(),
                         b"offline fake certificate")

    def credential_steps(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
        steps = workflow["jobs"]["build-macos"]["steps"]
        names = ("import Developer ID certificate", "store notarytool credentials")
        selected = [next(step for step in steps if step.get("name") == name) for name in names]
        self.assertEqual(set(selected[0]["env"]), {"CERT_BASE64", "CERT_PASSWORD", "KEYCHAIN_PASSWORD"})
        self.assertEqual(set(selected[1]["env"]), {"APPLE_ID", "TEAM_ID", "APP_PASSWORD"})
        for step in selected:
            self.assertNotIn("${{", step["run"])
            self.assertTrue(all(self.env[name] == "offline" for name in step["env"]))
        return selected

    def test_actual_workflow_credential_steps_execute_closed_path_and_export_keychain(self):
        imported, stored = self.credential_steps()
        self.log.unlink(missing_ok=True)
        self.script(imported["run"])
        keychain = str(self.root / "runner/build.keychain-db")
        certificate = str(self.root / "runner/certificate.p12")
        exported = Path(self.env["GITHUB_ENV"]).read_text()
        self.assertEqual(exported, "KEYCHAIN_PATH=" + keychain + "\n")
        self.assertEqual(Path(certificate).read_bytes(), b"offline fake certificate")
        self.script(stored["run"], KEYCHAIN_PATH=keychain)
        self.assertEqual(self.calls(), [
            ["base64", "--decode", "-o", certificate],
            ["security", "create-keychain", "-p", "offline", keychain],
            ["security", "set-keychain-settings", "-lut", "21600", keychain],
            ["security", "unlock-keychain", "-p", "offline", keychain],
            ["security", "import", certificate, "-P", "offline", "-A", "-t", "cert",
             "-f", "pkcs12", "-k", keychain],
            ["security", "list-keychain", "-d", "user", "-s", keychain, "login.keychain"],
            ["security", "set-key-partition-list", "-S", "apple-tool:,apple:,codesign:",
             "-s", "-k", "offline", keychain],
            ["xcrun", "notarytool", "store-credentials", "notarytool-profile",
             "--apple-id", "offline", "--team-id", "offline", "--password", "offline",
             "--keychain", keychain],
        ])

    def test_actual_workflow_credential_tool_failures_are_fatal_without_following_calls(self):
        imported, stored = self.credential_steps()
        for tool, expected in (("base64", ["base64"]), ("security", ["base64", "security"])):
            self.log.unlink(missing_ok=True)
            self.script(imported["run"], success=False, FAIL_TOOL=tool)
            self.assertEqual([call[0] for call in self.calls()], expected)
            self.assertFalse(Path(self.env["GITHUB_ENV"]).exists())
        self.log.unlink(missing_ok=True)
        self.script(stored["run"], success=False, FAIL_TOOL="xcrun")
        self.assertEqual([call[0] for call in self.calls()], ["xcrun"])


class FinalNativeCLITests(GitFixture):
    """Actual release CLI with real Git and GET-only fake API, not a gate mock."""

    def setUp(self):
        super().setUp()
        self.api_log = self.root / "native-final-api.jsonl"
        self.tools = self.root / "closed-path"
        self.tools.mkdir()
        for name in ("git", "python3"):
            (self.tools / name).symlink_to(sys.executable if name == "python3" else shutil.which(name))
        upload_pack = shutil.which("git-upload-pack") or (
            Path(self.git("--exec-path")) / "git-upload-pack")
        (self.tools / "git-upload-pack").symlink_to(upload_pack)
        gh = self.tools / "gh"
        gh.write_text(f"#!{sys.executable}\n" + r'''
import json,os,sys
args=sys.argv[1:]
with open(os.environ["NATIVE_API_LOG"],"a") as f: f.write(json.dumps(args)+"\n")
assert args[:3]==["api","--method","GET"],args
assert args[3].startswith("repos/miyako/4d-plugin-udp/"),args
assert "/releases?per_page=100&page=1" in args[3] or "/git/matching-refs/tags/v" in args[3],args
print("[]")
''')
        gh.chmod(0o755)
        self.env.update(PATH=str(self.tools), GH_TOKEN="offline",
                        GITHUB_REPOSITORY="miyako/4d-plugin-udp",
                        GITHUB_OUTPUT=str(self.root / "native-final-output"),
                        NATIVE_API_LOG=str(self.api_log))
        for leaf in native.FILES:
            target = self.local / leaf
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"tracked original native leaf")
        for name in ("manifest.json", "constants.xlf"):
            (self.local / name).write_bytes(b"source resource " + name.encode())
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "tracked native payload")
        self.sha = self.git("rev-parse", "HEAD")
        self.env["GITHUB_SHA"] = self.sha
        version = source.read(self.local)
        self.fresh = {path: b"rebuilt " + str(path).encode() for path in native.FILES}
        source_plist = source.load_plist((self.local / source.PLIST).read_bytes())
        built = {source.SHORT: version}
        if source.BUILD in source_plist:
            built[source.BUILD] = version
        self.fresh[native.BUNDLE / "Contents/Info.plist"] = plistlib.dumps(built, fmt=plistlib.FMT_BINARY)
        self.fresh[native.BUNDLE / "Contents/Resources" / source.LOCALIZED] = source.text(
            self.local / source.LOCALIZED).encode("utf-16")
        for name in ("manifest.json", "constants.xlf"):
            self.fresh[native.BUNDLE / "Contents/Resources" / name] = (self.local / name).read_bytes()
        self.fresh[native.DOWNLOADS[0]] = self.fresh[native.WINDOWS_BINARY]
        self.fresh[native.XCODE_DATA / "build.db"] = b"fresh native database"
        for relative, data in self.fresh.items():
            path = self.local / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        for name in ("UDP-" + version + ".zip", "UDP-" + version + ".dmg"):
            (self.local / name).write_bytes(b"fresh package")

    def final(self, success):
        result = self.cli(".github/scripts/release.py", "check", "--sha", self.sha)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def assert_all_fresh(self):
        for path, data in self.fresh.items():
            self.assertEqual((self.local / path).read_bytes(), data, str(path))

    def test_actual_cli_every_packaged_leaf_negative_precedes_api_restored_positive_retains_bytes(self):
        for leaf in native.FILES:
            for mutation in ("missing", "empty", "directory", "samebytes-link"):
                with self.subTest(leaf=leaf, mutation=mutation):
                    self.api_log.unlink(missing_ok=True)
                    target = self.local / leaf
                    saved = target.read_bytes()
                    target.unlink()
                    if mutation == "empty":
                        target.write_bytes(b"")
                    elif mutation == "directory":
                        target.mkdir()
                    elif mutation == "samebytes-link":
                        outside = self.root / "samebytes-native-leaf"
                        outside.write_bytes(saved)
                        target.symlink_to(outside)
                    self.final(False)
                    self.assertFalse(self.api_log.exists(), "Native failure reached API")
                    if target.is_symlink():
                        target.unlink()
                    elif target.is_dir():
                        target.rmdir()
                    target.write_bytes(saved)
                    self.final(True)
                    self.assert_all_fresh()
                    calls = [json.loads(line) for line in self.api_log.read_text().splitlines()]
                    self.assertEqual(len(calls), 2)
                    self.assertTrue(all(call[:3] == ["api", "--method", "GET"] for call in calls))

    def test_actual_cli_source_resources_download_equality_and_narrow_database_names(self):
        for relative in (
            native.BUNDLE / "Contents/Resources/constants.xlf",
            native.BUNDLE / "Contents/Resources/manifest.json",
            native.DOWNLOADS[0], native.WINDOWS_BINARY,
        ):
            target = self.local / relative
            saved = target.read_bytes()
            self.api_log.unlink(missing_ok=True)
            target.write_bytes(b"late substitution")
            self.final(False)
            self.assertFalse(self.api_log.exists())
            target.write_bytes(saved)
            self.final(True)
            self.assert_all_fresh()
        for relative in (
            native.XCODE_DATA / "unexpected-source.cpp", native.XCODE_DATA / "build.db-evil",
            native.XCODE_DATA / "evil.xcbuilddata/build-request.json",
            Path("test/Plugins/XCBuildData-evil/build.db"),
            native.DIRECTORIES[0] / "Default/UDP.build/JavaClasses/arbitrary.class",
        ):
            self.api_log.unlink(missing_ok=True)
            target = self.local / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"unexpected retained bytes")
            self.final(False)
            self.assertFalse(self.api_log.exists())
            self.assertEqual(target.read_bytes(), b"unexpected retained bytes")
            target.unlink()
            parent = target.parent
            while parent != self.local and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
            self.final(True)
            self.assert_all_fresh()
