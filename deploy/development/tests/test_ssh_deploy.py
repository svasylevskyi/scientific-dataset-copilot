"""Exercise real Git updates and flock; replace Docker with a recording command."""

import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


class DeploymentCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.home = root / "home"
        self.home.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), GIT_CONFIG_NOSYSTEM="1")
        self.source = root / "source"
        self.source.mkdir()
        self.git(self.source, "init", "-b", "main")
        scripts = self.source / "deploy/development"
        scripts.mkdir(parents=True)
        for name in ("deploy.sh", "compose.sh"):
            shutil.copyfile(SCRIPTS / name, scripts / name)
        (self.source / ".gitignore").write_text(
            ".development-deploy.lock\n.env.development\nbackups/\n"
        )
        (self.source / "version").write_text("old\n")
        self.commit("Initial deployment")
        self.old = self.git(self.source, "rev-parse", "HEAD")
        self.origin = root / "origin.git"
        self.git(root, "clone", "--bare", str(self.source), str(self.origin))
        self.repo = self.home / "scientific-dataset-copilot"
        self.git(root, "clone", str(self.origin), str(self.repo))
        self.git(self.source, "remote", "add", "origin", str(self.origin))
        (self.source / "version").write_text("new\n")
        self.commit("Next reviewed version")
        self.new = self.git(self.source, "rev-parse", "HEAD")
        self.git(self.source, "push", "origin", "main")
        # Match the installed command: it must not be read from a changing checkout.
        self.command = self.home / "sdc-deploy"
        shutil.copyfile(SCRIPTS / "ssh-deploy.sh", self.command)
        self.log = root / "docker.jsonl"
        bin_dir = root / "bin"
        bin_dir.mkdir()
        docker = bin_dir / "docker"
        docker.write_text(
            f"#!{sys.executable}\n"
            "import fcntl, json, os, sys\n"
            "with open('.development-deploy.lock', 'a') as lock:\n"
            "    try:\n"
            "        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
            "    except BlockingIOError:\n"
            "        pass\n"
            "    else:\n"
            "        sys.exit('Docker ran without the deployment lock')\n"
            "with open(os.environ['DOCKER_LOG'], 'a') as log:\n"
            "    log.write(json.dumps([os.environ['SDC_SOURCE_REVISION'], sys.argv[1:]]) + '\\n')\n"
            "if os.environ.get('FAIL_BUILD') and 'build' in sys.argv:\n"
            "    sys.exit(23)\n"
            "if 'pg_dump' in sys.argv:\n"
            "    print('test backup')\n"
        )
        docker.chmod(0o755)
        self.env.update(
            PATH=f"{bin_dir}:{os.environ['PATH']}", DOCKER_LOG=str(self.log)
        )

    def git(self, directory, *args):
        return subprocess.check_output(
            [
                "git",
                "-c",
                "user.name=Deployment test",
                "-c",
                "user.email=test@example.com",
                *args,
            ],
            cwd=directory,
            env=self.env,
            text=True,
            stderr=subprocess.PIPE,
        ).strip()

    def commit(self, message):
        self.git(self.source, "add", ".")
        self.git(self.source, "commit", "-m", message)

    def deploy(self, command=None):
        return subprocess.run(
            ["bash", str(self.command)],
            check=False,
            env=dict(self.env, SSH_ORIGINAL_COMMAND=command or f"deploy {self.new}"),
            capture_output=True,
            text=True,
            timeout=15,
        )

    def assert_rejected(self, result, message, head=None):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message, result.stderr)
        self.assertEqual(self.git(self.repo, "rev-parse", "HEAD"), head or self.old)
        self.assertFalse(
            self.log.exists(), "Rejected requests must never invoke Docker"
        )

    def test_exact_commit_repeat_and_shared_lock(self):
        # Ignored server configuration must survive the fast-forward.
        config = self.repo / ".env.development"
        config.write_text("keep existing credentials\n")
        for _ in range(2):
            result = self.deploy()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"completed for commit {self.new}", result.stdout)
        self.assertEqual(self.git(self.repo, "rev-parse", "HEAD"), self.new)
        self.assertEqual(config.read_text(), "keep existing credentials\n")
        entries = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertTrue(all(revision == self.new for revision, _ in entries))
        self.assertTrue(any("pg_dump" in args for _, args in entries))
        self.assertTrue(any("migrate" in args for _, args in entries))

    def test_shell_and_malformed_commands_rejected(self):
        for command in (
            "bash",
            "deploy main",
            f"deploy {self.new}; id",
            f"deploy {self.new}\nid",
            "status",
        ):
            with self.subTest(command=command):
                self.assert_rejected(self.deploy(command), "Only")

    def test_non_main_checkout_rejected(self):
        self.git(self.repo, "switch", "-c", "work")
        self.assert_rejected(self.deploy(), "must be on main")

    def test_tracked_and_untracked_changes_rejected(self):
        for name in ("version", "operator-notes"):
            with self.subTest(name=name):
                path = self.repo / name
                original = path.read_text() if path.exists() else None
                path.write_text("local edit\n")
                self.assert_rejected(self.deploy(), "local changes")
                if original is None:
                    path.unlink()
                else:
                    path.write_text(original)

    def test_commit_outside_main_rejected(self):
        self.git(self.source, "switch", "-c", "unmerged")
        (self.source / "version").write_text("unmerged\n")
        self.commit("Not merged")
        other = self.git(self.source, "rev-parse", "HEAD")
        self.git(self.source, "push", "origin", "unmerged")
        self.git(self.repo, "fetch", "origin", "unmerged")
        self.assert_rejected(self.deploy(f"deploy {other}"), "not on origin/main")

    def test_older_commit_rejected(self):
        self.git(self.repo, "pull", "--ff-only")
        self.assert_rejected(
            self.deploy(f"deploy {self.old}"), "backwards", head=self.new
        )

    def test_concurrent_deployment_rejected_before_git_update(self):
        with (self.repo / ".development-deploy.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assert_rejected(self.deploy(), "already running")

    def test_build_failure_propagates_and_releases_lock(self):
        self.env["FAIL_BUILD"] = "1"
        result = self.deploy()
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertIn("failed during image build", result.stderr)
        entries = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertFalse(
            any("stop" in args or "pg_dump" in args for _, args in entries)
        )
        del self.env["FAIL_BUILD"]
        result = self.deploy()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_direct_operator_deployment_still_acquires_lock(self):
        result = subprocess.run(
            ["bash", "deploy/development/deploy.sh"],
            check=False,
            cwd=self.repo,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
