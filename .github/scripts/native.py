"""UDP's exact native outputs, selective cleanup, and publication resource gate."""

import argparse
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys


PRODUCT = "UDP"
BASE = Path("test/Plugins")
BUNDLE = BASE / "UDP.bundle"
WINDOWS_BINARY = BUNDLE / "Contents/Windows64/UDP.4DX"
DOWNLOADS = (Path("winbuild/UDP.4DX"),)
MAC_FILES = tuple(BUNDLE / relative for relative in (
    "Contents/MacOS/UDP", "Contents/Info.plist",
    "Contents/Resources/English.lproj/InfoPlist.strings",
    "Contents/Resources/constants.xlf", "Contents/Resources/manifest.json",
    "Contents/_CodeSignature/CodeResources",
))
FILES = (*MAC_FILES, WINDOWS_BINARY)
# Original hosted Default run 36970276549, job 110722792249, step 6.
# Development/Deployment's historical build/* is not Default's OBJROOT.
DIRECTORIES = (BASE / "UDP.build",)
XCODE_DATA = BASE / "XCBuildData"
_OBJECTS = r"(?:4DPlugin-JSON|4DPlugin-UDP|4DPluginAPI|C_LONGINT|C_TEXT)"
_TARGET = r"test/Plugins/UDP\.build/Default/UDP\.build/"
_OBJECT_ROOT = _TARGET + r"Objects-normal/(?:arm64|x86_64)/"
_INTERMEDIATE_FILES = (
    r"test/Plugins/UDP\.build/Default/UDP-[0-9a-f]{32}-VFS/all-product-headers\.yaml",
    _OBJECT_ROOT + _OBJECTS + r"\.(?:o|d|dia)",
    _OBJECT_ROOT + r"Binary/UDP",
    _OBJECT_ROOT + r"UDP\.(?:LinkFileList|SwiftConstValuesFileList|SwiftFileList)",
    _OBJECT_ROOT + r"UDP_dependency_info\.dat",
    _OBJECT_ROOT + r"[0-9a-f]{32}-common-args\.resp",
    _TARGET + r"Objects-normal/undefined_arch/(?:Processed-Info\.plist|UDP_dependency_info\.dat)",
    _TARGET + r"Objects/LinkFileList",
    _TARGET + r"(?:PkgInfo|Script-D1292E7B22C4A91E00CB5A8C\.sh)",
    _TARGET + r"UDP-(?:BuildDependencyInfo\.json|LinkMap-normal-undefined_arch\.txt)",
    _TARGET + r"UDP(?:-(?:all-non-framework-target-headers|all-target-headers|generated-files|own-target-headers|project-headers))?\.hmap",
    _TARGET + r"UDP\.(?:DependencyMetadataFileList|DependencyStaticMetadataFileList)",
)
_INTERMEDIATE_DIRS = (
    r"test/Plugins/UDP\.build(?:/Default)?",
    r"test/Plugins/UDP\.build/DerivedSources",
    r"test/Plugins/UDP\.build/Default/UDP-[0-9a-f]{32}-VFS",
    _TARGET.rstrip("/"),
    _TARGET + r"(?:DerivedSources|DerivedSources-normal)(?:/(?:arm64|x86_64))?",
    _TARGET + r"(?:FixedFiles|JavaClasses|Objects|PrefixHeaders|ResourceManagerResources(?:/Objects)?)",
    _TARGET + r"Objects-normal(?:/(?:arm64|x86_64)(?:/Binary)?|/undefined_arch)?",
)


def generated(path):
    """Only leaf outputs proven for this project; never historical build/*."""
    path = str(path)
    return (
        path in set(map(str, (*FILES, *DOWNLOADS)))
        or re.fullmatch(
            r"test/Plugins/XCBuildData/(?:build\.db(?:-wal|-shm)?|"
            r"[0-9a-f]{32}\.xcbuilddata/.+)", path) is not None
        or any(re.fullmatch(pattern, path) for pattern in _INTERMEDIATE_FILES)
    )


def _info(path):
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _node(path, directory=None):
    info = _info(path)
    if info is None:
        return None
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError(f"Refusing symlink/reparse output: {path}")
    is_dir = stat.S_ISDIR(info.st_mode)
    if not is_dir and not stat.S_ISREG(info.st_mode):
        raise ValueError(f"Nonregular output: {path}")
    if directory is not None and is_dir != directory:
        raise ValueError(f"Wrong output type: {path}")
    if is_dir:
        if not info.st_mode & 0o444 or not info.st_mode & 0o111:
            raise PermissionError(f"Inaccessible output directory: {path}")
        if not os.access(path, os.R_OK | os.X_OK):
            raise PermissionError(f"Inaccessible output directory: {path}")
        with os.scandir(path) as entries:
            tuple(entries)
    else:
        if not info.st_mode & 0o444:
            raise PermissionError(f"Inaccessible output file: {path}")
        with path.open("rb") as stream:
            stream.read(1)
    return info


def _relative(path):
    path = Path(path)
    if path.is_absolute():
        path = path.relative_to(Path.cwd())
    if ".." in path.parts or path == Path("."):
        raise ValueError(f"Output escapes checkout: {path}")
    return path


def _ancestors(path):
    for parent in reversed(path.parents):
        if parent == Path("."):
            continue
        info = _node(parent, directory=True)
        if info is not None and _info(parent / ".git") is not None:
            raise ValueError(f"Nested .git marker: {parent}")


def _directory_allowed(path):
    text = str(path)
    return (
        path == XCODE_DATA
        or re.fullmatch(r"test/Plugins/XCBuildData/[0-9a-f]{32}\.xcbuilddata(?:/.+)?", text)
        or any(re.fullmatch(pattern, text) for pattern in _INTERMEDIATE_DIRS)
    )


def _tree(path, intermediate=False):
    info = _node(path)
    if info is None:
        return
    if path.name == ".git":
        raise ValueError(f"Nested .git marker: {path}")
    directory = stat.S_ISDIR(info.st_mode)
    if intermediate and not (_directory_allowed(path) if directory else generated(path)):
        raise ValueError(f"Unexpected intermediate output: {path}")
    if directory:
        for child in path.iterdir():
            _tree(child, intermediate=intermediate)


def validate_paths(paths):
    for value in paths:
        path = _relative(value)
        _ancestors(path)
        expected = False if path in (*FILES, *DOWNLOADS) else (
            True if path in (*DIRECTORIES, XCODE_DATA) else None)
        _node(path, directory=expected)
        _tree(path, intermediate=path in (*DIRECTORIES, XCODE_DATA))


def prepare():
    targets = (*MAC_FILES, *DIRECTORIES, XCODE_DATA)
    validate_paths(targets)
    # Refuse selected/indexed inputs even if somebody put them inside OBJROOT.
    roots = tuple(map(str, (*DIRECTORIES, XCODE_DATA)))
    for args in (("ls-files", "-z", "--", *roots),
                 ("ls-tree", "-rz", "--name-only", "HEAD", "--", *roots)):
        if subprocess.run(["git", *args], check=True, stdout=subprocess.PIPE).stdout:
            raise ValueError("Tracked input inside native intermediate roots")
    for path in targets:
        if _info(path) is None:
            continue
        parent = path.parent
        if not parent.stat().st_mode & 0o222 or not os.access(parent, os.W_OK):
            raise PermissionError(f"Unwritable cleanup parent: {parent}")
        if path.is_dir():
            for descendant in (path, *path.rglob("*")):
                if descendant.is_dir() and (
                    not descendant.stat().st_mode & 0o222
                    or not os.access(descendant, os.W_OK)
                ):
                    raise PermissionError(f"Unwritable cleanup directory: {descendant}")
    for path in MAC_FILES:
        path.unlink(missing_ok=True)
    for path in (*DIRECTORIES, XCODE_DATA):
        if _info(path) is not None:
            shutil.rmtree(path)


def require_file(path):
    validate_paths((path,))
    if _info(path) is None or not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"Missing or empty native output: {path}")


def _resources():
    for name in ("manifest.json", "constants.xlf"):
        source = Path(name)
        copied = BUNDLE / "Contents/Resources" / name
        require_file(source)
        require_file(copied)
        if source.read_bytes() != copied.read_bytes():
            raise ValueError(f"Copied resource differs from source: {copied}")


def validate_unsigned():
    validate_paths((*FILES, *DOWNLOADS, *DIRECTORIES, XCODE_DATA))
    for path in MAC_FILES[:-1]:
        require_file(path)
    _resources()
    import source_version
    source_version.verify_bundle(BUNDLE)


def verify_windows():
    for source in DOWNLOADS:
        require_file(source)
    require_file(WINDOWS_BINARY)
    if DOWNLOADS[0].read_bytes() != WINDOWS_BINARY.read_bytes():
        raise ValueError("Merged Windows payload differs from downloaded artifact")


def merge_windows():
    validate_paths((*DOWNLOADS, WINDOWS_BINARY))
    require_file(DOWNLOADS[0])
    WINDOWS_BINARY.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DOWNLOADS[0], WINDOWS_BINARY)
    verify_windows()


def verify_resources():
    """Final gate: signatures and all packaged generated leaves are mandatory."""
    validate_unsigned()
    for path in FILES:
        require_file(path)
    verify_windows()


validate_outputs = verify_resources
verify_final = verify_resources


def accepted(stream):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate notarization JSON key: {key}")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"Nonfinite notarization JSON number: {value}")

    def finite(value):
        result = float(value)
        return result if math.isfinite(result) else invalid(value)

    result = json.load(stream, object_pairs_hook=unique, parse_constant=invalid,
                       parse_float=finite)
    if not isinstance(result, dict) or result.get("status") != "Accepted":
        raise ValueError("Notarization was not Accepted")


if __name__ == "__main__":
    phases = {
        "clean-macos": prepare, "verify-unsigned": validate_unsigned,
        "verify-resources": verify_resources, "merge-windows": merge_windows,
        "accepted": lambda: accepted(sys.stdin),
    }
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=phases)
    phases[parser.parse_args().phase]()
