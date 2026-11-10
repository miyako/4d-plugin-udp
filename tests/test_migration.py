"""The one production branch authorization, exercised only against local bare Git."""

import shutil
import subprocess
import sys

from helper_support import GitFixture, ROOT


class MigrationGuardTests(GitFixture):
    def setUp(self):
        super().setUp()
        shutil.copytree(ROOT / ".github/migration-hooks", self.local / ".github/migration-hooks")
        self.git("add", ".github/migration-hooks")
        self.git("commit", "--quiet", "-m",
                 "migration fixture\n\nCo-authored-by: Copilot App "
                 "<223556219+Copilot@users.noreply.github.com>")
        self.new = self.git("rev-parse", "HEAD")
        self.ref = "refs/heads/miyako-simplify-udp-workflows"
        self.env.update(MIGRATION_OLD_SHA="0" * 40, MIGRATION_NEW_SHA=self.new)

    def guard(self, records=None):
        return subprocess.run(
            [sys.executable, ".github/scripts/migration_guard.py"],
            cwd=self.local, env=self.env, input=(
                f"{self.new} {self.new} {self.ref} {'0' * 40}\n"
                if records is None else records), text=True, capture_output=True, timeout=60)

    def test_exact_committed_executable_before_push_and_real_singular_new_advertisement(self):
        result = self.guard()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.git("tag", "-a", "incidental", "-m", "must never follow")
        self.git("config", "push.followTags", "true")
        result = subprocess.run(
            ["git", "-c", "core.hooksPath=.github/migration-hooks",
             "-c", "push.followTags=false", "push", "--no-follow-tags",
             "origin", f"{self.new}:{self.ref}"], cwd=self.local, env=self.env,
            capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git("ls-remote", "--refs", "origin", self.ref),
                         self.new + "\t" + self.ref)
        self.assertEqual(self.git("--git-dir=" + str(self.bare), "tag", "--list"), "")

    def test_zero_wrong_new_wrong_old_wrong_ref_and_multiple_updates_rejected(self):
        record = f"{self.new} {self.new} {self.ref} {'0' * 40}\n"
        for records in ("", record * 2, record.replace(self.ref, self.ref + "-evil"),
                        record.replace("0" * 40, self.sha),
                        record.replace(self.new, "HEAD", 1),
                        record.replace(self.new, self.sha, 1)):
            self.assertNotEqual(self.guard(records).returncode, 0)

    def test_guard_rejects_replaced_symlink_nonexec_hook_and_staged_mutation(self):
        hook = self.local / ".github/migration-hooks/pre-push"
        raw = hook.read_bytes()
        hook.write_bytes(b"#!/bin/sh\nexit 0\n")
        self.assertNotEqual(self.guard().returncode, 0)
        hook.write_bytes(raw)
        hook.chmod(0o644)
        self.assertNotEqual(self.guard().returncode, 0)
        hook.chmod(0o755)
        outside = self.root / "same-bytes-hook"
        outside.write_bytes(raw)
        outside.chmod(0o755)
        hook.unlink()
        hook.symlink_to(outside)
        self.assertNotEqual(self.guard().returncode, 0)
        hook.unlink()
        hook.write_bytes(raw)
        hook.chmod(0o755)
        self.git("update-index", "--chmod=-x", "--", str(hook.relative_to(self.local)))
        self.assertNotEqual(self.guard().returncode, 0)
        self.git("update-index", "--chmod=+x", "--", str(hook.relative_to(self.local)))
        self.assertEqual(self.guard().returncode, 0)

    def test_existing_advertised_branch_is_not_create_only_even_at_same_head(self):
        self.git("--git-dir=" + str(self.bare), "fetch", "--quiet", "--no-tags",
                 str(self.local), self.new)
        for remote in (self.sha, self.new):
            self.git("--git-dir=" + str(self.bare), "update-ref", self.ref, remote)
            result = subprocess.run(
                ["git", "-c", "core.hooksPath=.github/migration-hooks",
                 "-c", "push.followTags=false", "push", "--no-follow-tags",
                 "origin", f"{self.new}:{self.ref}"], cwd=self.local, env=self.env,
                capture_output=True, text=True, timeout=60)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.git("--git-dir=" + str(self.bare), "rev-parse", self.ref),
                             remote)
