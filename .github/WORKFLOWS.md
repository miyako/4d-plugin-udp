# Manual source maintenance and publication

**Bump version** and **Build** are independent manual decisions. Bump has one
required `patch` / `minor` / `major` choice (default `patch`), updates source
metadata on the selected branch, and never builds, tags, publishes or dispatches
another workflow. Build has no custom inputs: use GitHub's built-in ref selector.
Every checkout uses the immutable event SHA, not a moving branch or tag name.

Bump requires the selected branch still to advertise the selected event commit.
It creates exactly one nonempty, source-only direct child with explicit Actions
bot author and committer identities and the ending Copilot App co-author trailer.
The committed executable hook is raw-blob verified before edits and immediately
before pushing. Its actual push advertisement must contain exactly the expected
single update; advancement, rewind, deletion and an already-identical result
all fail closed. Both no-follow-tags controls are explicit. There is no force,
amend, automatic retry or rollback.

## UDP source authority

Intake was `a288635fb05d030cf9faeca7b03a1ea1e0546df8`, canonical repository
`miyako/4d-plugin-udp`, default branch `master`. The rename-follow Bump history
changed from the fallback header at
`f156d710397d35a12e0cc613a8a3611446329ff7` to the explicit coordinated header at
`7c2eb38001a56120b5935a06ec9587412ef93902`. That later header, not its buggy
marketing-only body, establishes the coordinated version model.

All six `MARKETING_VERSION` and `CURRENT_PROJECT_VERSION` assignments, the
required source `Info.plist` short version, and the actual copied
`English.lproj/InfoPlist.strings` versions must agree. Only the build plist key
is optional; its absence and supported references are preserved. The migration
does not increment `2.1.3`: it only repairs the six stale current values `2.1.1`
and the two stale source-localization values `2.1.0`. Prebuilt bundle metadata
is deliberately untouched. Subsequent bumps preserve encodings, BOMs, individual
line terminators, unrelated bytes and Git modes.

## Build and create-only publication

Build retains Windows x64 Release followed by macOS universal Default, deployment
target 11.0, the original project/target/output settings, resources, runtime
signing, ZIP and UDBZ DMG packaging, two notarizations, and DMG stapling.
It does not bypass Xcode phases, relocate outputs, modernize native dependencies
or invoke 4D. Both arm64 and x86_64 are required; no new architecture exclusion
is imposed. Notarization requires both a successful command and JSON `Accepted`.
The original release notes policy remains empty body, no generated notes.

The constant publication concurrency group covers all refs, with cancellation
disabled. GitHub concurrency does not promise FIFO ordering. There is no new
default-branch-only restriction. Process-scoped inherited `core.autocrlf=false`
is set before all Build checkouts, without modifying runner-global Git settings.
Only Windows regular-file executable-bit differences are tolerated, and only
when raw bytes agree; index/tree modes, links, reparse points and other types
remain strict.

Availability is authenticated with explicit `GH_TOKEN`, exact canonical-case
repository identity and selected SHA. All release pages, including drafts,
are read until an empty page, with strict JSON/schema validation. Exact tag
absence is required from both API refs and Git advertisement before any native
work and again after all native/sign/notary/staple work. Publication separately
creates the tag at the selected SHA, verifies API and Git, creates a new public
release with a new positive ID, then uploads only the two exact assets to it,
verifying names, integer sizes and uploaded state.

An occupied version or an ambiguous/failed response stops publication. **Do not
rerun blindly:** inspect retained tag, release and assets and resolve manually.
There is no delete, patch, clobber, reuse, retry or rollback. The helper reports
partial retained state explicitly.

## Native output boundaries

Cleanup validates all targets, ancestors, descendants, types, permissions,
links/reparse points and nested Git markers before deleting the first leaf.
It deletes selective proven generated leaves/intermediates, never whole bundles,
resource trees, lowercase plugin directories or unrelated Default siblings.
Windows uses the actual VCXPROJ output, not a recursive first-match search.

Original successful hosted run `36970276549`, job `110722792249`, step 6 at the
intake SHA supplies the actual Default path evidence. Its build-only extract
(credential steps excluded) is 222924 bytes, SHA-256
`e0d7e5b3d211df39364be473ba725377cc16b7bc8fd3be08557dce10319e43c7`.
It shows `test/Plugins/UDP.build/Default/...` and
`test/Plugins/XCBuildData/251a06e17cfb4042f92013e479386e4e.xcbuilddata`.
`CONFIGURATION_BUILD_DIR` alone does not establish `OBJROOT`; Development and
Deployment settings are not Default evidence. Tracked historical `build/*`
files remain immutable. Xcode database allowances are exact `build.db`,
`build.db-wal`, `build.db-shm` and proven 32-hex `.xcbuilddata` records, not an
arbitrary subtree. Empty auxiliary directories grant no file exemption.

Initial checkout validation is globally clean. Final validation instead retains
the freshly generated bytes (including originally tracked leaves), checking
immutable HEAD, exact index and raw nongenerated bytes independently, including
both `git ls-files -v` and `-f`. Every packaged generated leaf must be a nonempty
regular nonsymlink file; compiled metadata, exact copied source resources and
downloaded-versus-merged Windows bytes are revalidated. Unsigned and final
signature gates are separate. No reset is used to fake a clean native build.

Direct native-helper processes disable bytecode writes before importing local
metadata code, independently of workflow or runner environment. The regression
runs extracted native workflow commands with real source/compiled metadata and
bytecode environment flags explicitly absent, then the real final publication
CLI. The hostile-global actual-clone regression also runs the complete Windows
mode/raw/index/hidden-flag/type/reparse and non-Windows negative matrix on the
cloned checkout, with restored positives and unchanged fixture-global bytes.

## Offline regression suite

Run `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v` and
`actionlint .github/workflows/*.yml`. Python, PowerShell, actionlint and the
Python dependencies in `tests/requirements.txt` are needed. The suite uses
disposable local Git/bare repositories and closed-PATH
native/credential/API doubles. It never proves hosted toolchain, signing or
service success and must not invoke real native, signing, notarization or 4D
tools. Original intake fixtures are pinned; live version expectations also work
on the genuinely generated bump child.

## Immutable migration references

These are adaptation references, not authority to transfer another product's
native paths, independent version policy or output/phase exceptions.

| `miyako/4d-plugin-` repository | Immutable commit |
|---|---|
| native-encoding-detection | `c42ca565857f674bde5ea6ed3435c87375eda4a7` |
| file-information | `19848973601acfd3a2b5070230fa40cdc7e4edb2` |
| common-string-algorithm | `2606a68201866ec9fcbb38b51462d79215f504ef` |
| window-button | `3f14facb9aaaaff0e22eeb8e07531163680c3a8a` |
| raw-picture-data | `8144537fdc8dcc3d0c053dfe97aff0a8c0c3a6f9` |
| PRNG | `522f62e1e9f388be0f3f226c1d4c39362dad2491` |
| get-file-description | `0e6dad397e015c3c7ec61d7dfeb9c60bc6a4a22b` |
| maddy | `e000f17a5ad5085dcd010a9ddde76a4cb2d3119b` |
| keychain | `7aedc6ba4633e53f5055c1b83c68a6dd32d9c85a` |
| window-style | `2794dbe06717b8344a99fc14991a7a2b5d6ef196` |
| shell-execute-v2 | `ee33f21111d9a042101ccc11d68672a7a0067e9c` |
| serial | `32f33a3b3de7dd5201b215ff6050dd3d68e03936` |
| UTI | `5decf4be07f8297d256dfb559ef9466525fe9045` |
| RTF2TEXT | `4a8c89677515cd5c71c162e0b296e63bee374cdd` |
| libarchive | `9547d09522fc422ddd754fb088165b3d1d1d3073` |
| stomp | `ab9f5e51dba5b8b6ec1a1b70e191082fcb73fb41` |
