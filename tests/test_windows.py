"""Exact original CMD, selective PowerShell cleanup, and literal vcxproj output."""

import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

from native_support import INTAKE, MSBUILD, PWSH, ROOT, NativeFixture, native


class WindowsTests(NativeFixture):
    def powershell(self, phase, success=True, prefix=""):
        self.assertTrue(PWSH, "PowerShell required for offline native regression harness")
        script = "$ErrorActionPreference='Stop'\n" + prefix + (
            f"\n& ./.github/scripts/windows.ps1 -Phase {phase}\n")
        result = subprocess.run(
            [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            cwd=self.root, env=self.env, text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def test_original_cmd_verbatim_and_exact_project_provenance(self):
        original = subprocess.check_output(
            [self.env["REAL_GIT"], "show", INTAKE + ":.github/workflows/release.yml"],
            cwd=ROOT, text=True,
        )
        self.assertIn("          " + MSBUILD + "\n", original)
        current = (ROOT / ".github/workflows/release.yml").read_text()
        self.assertIn("          " + MSBUILD + "\n", current)
        document = ET.parse(ROOT / "UDP.vcxproj")
        ns = {"m": "http://schemas.microsoft.com/developer/msbuild/2003"}
        output = [node.text for node in document.findall(".//m:OutDir", ns)
                  if node.attrib.get("Condition") == "'$(Configuration)|$(Platform)'=='Release|x64'"]
        self.assertEqual(output, [
            "$(ProjectDir)test\\plugins\\$(ProjectName).bundle\\contents\\windows64\\"])
        script = (ROOT / ".github/scripts/windows.ps1").read_text()
        self.assertIn("$output = 'test/plugins/UDP.bundle/contents/windows64/UDP.4DX'", script)
        self.assertNotIn("SilentlyContinue", script)
        self.assertEqual(re.findall(r"catch\s*\[([^]]+)\]", script),
                         ["System.Management.Automation.ItemNotFoundException"])
        self.assertNotIn("msbuild", script.lower())

    def test_selective_cleanup_and_optional_absence_preserve_mac_and_siblings(self):
        early = self.write(native.WINDOWS_BINARY, b"old executable")
        self.write("Objs/Release/C_TEXT.obj", b"old intermediate")
        protected = (
            native.MAC_FILES[0], "Objs/Debug/C_TEXT.obj",
            native.BUNDLE / "Contents/QuickLook/Thumbnail.png",
            "test/Plugins/Default/keep", "build/historical",
        )
        for path in protected:
            self.write(path)
        self.powershell("clean")
        self.powershell("clean")
        self.assertFalse(early.exists())
        self.assertFalse((self.root / "Objs/Release").exists())
        for path in protected:
            self.assertEqual((self.root / path).read_bytes(), b"retained")
        self.assert_no_native()

    def test_late_invalid_type_access_link_nested_git_preserves_all_then_positive(self):
        early = self.write(native.WINDOWS_BINARY, b"earlier")
        late = self.write("Objs/Release/C_TEXT.obj", b"later")
        for case in ("directory-is-file", "unreadable", "unreadable-directory",
                     "link", "nested-git", "file-is-dir", "unexpected"):
            with self.subTest(case=case):
                if case == "directory-is-file":
                    shutil.rmtree(late.parent)
                    self.write("Objs/Release", b"later")
                elif case == "unreadable":
                    late.chmod(0)
                elif case == "unreadable-directory":
                    late.parent.chmod(0)
                elif case == "link":
                    late.unlink()
                    late.symlink_to(early)
                elif case == "nested-git":
                    self.write("Objs/Release/.git", b"gitdir: not permitted")
                elif case == "file-is-dir":
                    late.unlink()
                    late.mkdir()
                else:
                    self.write("Objs/Release/source.cpp")
                self.powershell("clean", success=False)
                self.assertEqual(early.read_bytes(), b"earlier")
                self.assert_no_native()
                if case == "unreadable":
                    late.chmod(0o644)
                if case == "unreadable-directory":
                    late.parent.chmod(0o755)
                if case in ("unreadable", "unreadable-directory", "nested-git", "unexpected"):
                    self.assertEqual(late.read_bytes(), b"later")
                parent = self.root / "Objs/Release"
                if parent.is_file():
                    parent.unlink()
                else:
                    shutil.rmtree(parent)
                self.write("Objs/Release/C_TEXT.obj", b"later")
        self.powershell("clean")
        self.assertFalse(early.exists())
        self.assertFalse(late.exists())

    def test_permission_probe_error_not_swallowed_and_no_first_delete(self):
        early = self.write(native.WINDOWS_BINARY, b"earlier")
        late = self.write("Objs/Release/C_TEXT.obj", b"later")
        self.powershell("clean", success=False, prefix=r'''
function Get-Item {
    param([string]$LiteralPath, [switch]$Force, $ErrorAction)
    if ($LiteralPath -like '*C_TEXT.obj') { throw [UnauthorizedAccessException]::new('offline denied') }
    Microsoft.PowerShell.Management\Get-Item -LiteralPath $LiteralPath -Force -ErrorAction Stop
}
''')
        self.assertEqual(early.read_bytes(), b"earlier")
        self.assertEqual(late.read_bytes(), b"later")
        self.assert_no_native()
        self.powershell("clean")

    def test_exact_output_only_no_recursive_search_or_stale_fallback(self):
        self.write("elsewhere/UDP.4DX", b"wrong")
        self.powershell("normalize", success=False)
        source = self.write("test/plugins/UDP.bundle/contents/windows64/UDP.4DX", b"")
        self.powershell("normalize", success=False)
        source.write_bytes(b"fresh x64")
        self.powershell("normalize")
        self.assertEqual(source.read_bytes(), b"fresh x64")
        self.assert_no_native()

    def test_tracked_intermediate_and_symlink_ancestor_are_not_deleted(self):
        early = self.write(native.WINDOWS_BINARY, b"earlier")
        late = self.write("Objs/Release/C_TEXT.obj", b"later")
        self.git("add", "Objs/Release/C_TEXT.obj")
        self.powershell("clean", success=False)
        self.assertEqual(early.read_bytes(), b"earlier")
        self.assertEqual(late.read_bytes(), b"later")
        self.git("commit", "--quiet", "-m", "selected Windows intermediate input")
        self.git("rm", "--cached", "--quiet", "--", "Objs/Release/C_TEXT.obj")
        self.powershell("clean", success=False)
        self.assertEqual(early.read_bytes(), b"earlier")
        self.assertEqual(late.read_bytes(), b"later")
        self.git("reset", "--quiet")
        (self.root / "Objs").rename(self.root / "moved")
        (self.root / "Objs").symlink_to(self.root / "moved", target_is_directory=True)
        self.powershell("clean", success=False)
        self.assertEqual(early.read_bytes(), b"earlier")
        self.assertEqual(late.read_bytes(), b"later")
