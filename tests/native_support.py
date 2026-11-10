"""Closed-PATH offline native harness; no real Apple, MSBuild or 4D tools."""

import contextlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import native

GIT = shutil.which("git")
BASH = "/bin/bash"
PWSH = shutil.which("pwsh")
INTAKE = "a288635fb05d030cf9faeca7b03a1ea1e0546df8"
MSBUILD = ('msbuild "%PRODUCT_NAME%.sln" /p:Configuration=Release /p:Platform=x64 '
           '/p:PlatformToolset=v143 /p:WindowsTargetPlatformVersion=10.0 /m')


@contextlib.contextmanager
def cwd(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


STUB = r'''#!PYTHON
import json,os,pathlib,shutil,subprocess,sys
tool=pathlib.Path(sys.argv[0]).name
args=sys.argv[1:]
with open(os.environ["NATIVE_LOG"],"a") as f: f.write(json.dumps([tool,*args])+"\n")
if tool=="git":
    assert args[:1] in (["ls-files"],["ls-tree"]), args
    sys.exit(subprocess.run([os.environ["REAL_GIT"],*args]).returncode)
if os.environ.get("FAIL_TOOL")==tool: sys.exit(23)
bundle=pathlib.Path("test/Plugins/UDP.bundle")
if tool=="xcodebuild":
    assert args==["-project","UDP.xcodeproj","-target","UDP","-configuration","Default",
                  "ARCHS=arm64 x86_64","ONLY_ACTIVE_ARCH=NO","MACOSX_DEPLOYMENT_TARGET=11.0",
                  "CODE_SIGNING_ALLOWED=NO","CONFIGURATION_BUILD_DIR="+os.getcwd()+"/test/Plugins","build"],args
    for leaf in ("Contents/MacOS/UDP","Contents/Info.plist","Contents/Resources/English.lproj/InfoPlist.strings"):
        p=bundle/leaf;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"fresh native")
    for name in ("constants.xlf","manifest.json"):
        p=bundle/"Contents/Resources"/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(name,p)
elif tool=="lipo":
    assert args==["-archs",str(bundle/"Contents/MacOS/UDP")],args
    print(os.environ.get("ARCHS","arm64 x86_64"))
elif tool=="security":
    if args[:1]==["find-identity"]: print('1) offline "Developer ID Application: Offline Fixture"')
elif tool=="codesign":
    if "--sign" in args:
        p=bundle/"Contents/_CodeSignature/CodeResources";p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"fresh signature")
    else: assert args==["--verify","--deep","--strict","--verbose=2",str(bundle)],args
elif tool=="ditto": pathlib.Path(args[-1]).write_bytes(b"zip")
elif tool=="hdiutil": pathlib.Path(args[-1]).write_bytes(b"dmg")
elif tool=="xcrun":
    if args[:2]==["notarytool","submit"]:
        print(os.environ.get("NOTARY_JSON",'{"status":"Accepted"}'))
        sys.exit(int(os.environ.get("NOTARY_EXIT","0")))
    elif args[:2]==["stapler","staple"]:
        sys.exit(int(os.environ.get("STAPLE_EXIT","0")))
    else: assert args[:2]==["notarytool","store-credentials"],args
elif tool=="base64":
    assert args[:2]==["--decode","-o"],args
    pathlib.Path(args[2]).write_bytes(b"offline fake certificate")
elif tool=="gh": sys.exit("API must never be reached by native harness")
else: sys.exit("Unexpected native command "+tool)
'''


class NativeFixture(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / (".native-fixture-" + uuid.uuid4().hex)
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)
        self.tools = self.root / "tools"
        self.tools.mkdir()
        self.log = self.root / "native.jsonl"
        self.env = {
            "PATH": str(self.tools), "HOME": str(self.root),
            "PRODUCT_NAME": "UDP", "BASE_DIR": "test", "MACOS_DEPLOYMENT_TARGET": "11.0",
            "VERSION": "2.1.3", "BUNDLE_PATH": str(native.BUNDLE),
            "NATIVE_LOG": str(self.log), "REAL_GIT": GIT,
            "GITHUB_ENV": str(self.root / "github.env"),
            "KEYCHAIN_PATH": str(self.root / "offline.keychain"),
            "RUNNER_TEMP": str(self.root / "runner"),
            "CERT_BASE64": "offline", "CERT_PASSWORD": "offline", "KEYCHAIN_PASSWORD": "offline",
            "APPLE_ID": "offline", "TEAM_ID": "offline", "APP_PASSWORD": "offline",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "PYTHONDONTWRITEBYTECODE": "1", "POWERSHELL_TELEMETRY_OPTOUT": "1",
            "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
        }
        (self.root / "runner").mkdir()
        for name in ("xcodebuild", "lipo", "codesign", "security", "ditto", "hdiutil",
                     "xcrun", "base64", "git", "gh"):
            self.write("tools/" + name, STUB.replace("PYTHON", sys.executable).encode()).chmod(0o755)
        for name in ("grep", "head", "sed"):
            executable = shutil.which(name)
            self.assertTrue(executable)
            (self.tools / name).symlink_to(executable)
        (self.tools / "python3").symlink_to(sys.executable)
        for name in ("native.py", "native.sh", "windows.ps1"):
            self.write(".github/scripts/" + name, (SCRIPTS / name).read_bytes())
        self.write(".github/scripts/source_version.py",
                   b"def verify_bundle(bundle):\n    assert bundle.name == 'UDP.bundle'\n")
        for name in ("manifest.json", "constants.xlf"):
            self.write(name, b"exact source " + name.encode())
        self.git("init", "--quiet")
        self.git("config", "user.email", "offline@example.invalid")
        self.git("config", "user.name", "Offline")
        self.git("commit", "--quiet", "--allow-empty", "-m", "offline fixture")

    def git(self, *args):
        result = subprocess.run([GIT, *args], cwd=self.root, env=self.env,
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def write(self, path, data=b"retained"):
        path = self.root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def phase(self, phase, success=True, **env):
        result = subprocess.run([BASH, ".github/scripts/native.sh", phase], cwd=self.root,
                                env={**self.env, **env}, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def script(self, script, success=True, **env):
        result = subprocess.run([BASH, "-e", "-o", "pipefail", "-c", script],
                                cwd=self.root, env={**self.env, **env},
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def populated(self):
        for path in native.FILES:
            self.write(path, b"fresh " + str(path).encode())
        for name in ("constants.xlf", "manifest.json"):
            self.write(native.BUNDLE / "Contents/Resources" / name, (self.root / name).read_bytes())
        self.write(native.DOWNLOADS[0], (self.root / native.WINDOWS_BINARY).read_bytes())

    def assert_no_native(self):
        self.assertFalse(any(c[0] != "git" for c in self.calls()), self.calls())
