"""Unit tests for GitManager cloning from custom git servers.

Covers the GIT_CLONE_* env configuration: ssh:// clones of custom hosts driven
through GIT_SSH_COMMAND, and the default-host posture (github.com/gitlab.com
https + per-call token) staying exactly as strict as before. Custom
GIT_CLONE_EXTRA_HOSTS servers are ssh-only — http(s) clone URLs are rejected.
"""

import os

import git
import pytest

from src.exceptions import ValidationError
from src.services.git_manager import (
    GitManager,
    _ssh_clone_env,
)


@pytest.fixture(autouse=True)
def _clean_git_clone_env(monkeypatch):
    """Start every test from an empty GIT_CLONE_* configuration."""
    for var in (
        "GIT_CLONE_EXTRA_HOSTS",
        "GIT_CLONE_SSH_KEY_PATH",
        "GIT_CLONE_SSH_KNOWN_HOSTS",
        "GIT_CLONE_SSH_COMMAND",
    ):
        monkeypatch.delenv(var, raising=False)


class TestSshCloneEnv:
    """GIT_SSH_COMMAND construction for ssh:// clones of custom hosts."""

    def test_default_command(self):
        env = _ssh_clone_env()
        cmd = env["GIT_SSH_COMMAND"]
        assert cmd.startswith("ssh ")
        # Never hang on a prompt: batch mode + auto-accept the host key.
        assert "BatchMode=yes" in cmd
        assert "StrictHostKeyChecking=accept-new" in cmd

    def test_key_path_injected(self, monkeypatch):
        monkeypatch.setenv("GIT_CLONE_SSH_KEY_PATH", "/keys/id_ed25519")
        cmd = _ssh_clone_env()["GIT_SSH_COMMAND"]
        assert "-i /keys/id_ed25519" in cmd

    def test_key_path_is_shell_quoted(self, monkeypatch):
        """git runs GIT_SSH_COMMAND through a shell — a spaced path must survive."""
        monkeypatch.setenv("GIT_CLONE_SSH_KEY_PATH", "/my keys/id_ed25519")
        cmd = _ssh_clone_env()["GIT_SSH_COMMAND"]
        assert "-i '/my keys/id_ed25519'" in cmd

    def test_known_hosts_pins_the_server_key(self, monkeypatch):
        monkeypatch.setenv("GIT_CLONE_SSH_KNOWN_HOSTS", "/keys/known_hosts")
        cmd = _ssh_clone_env()["GIT_SSH_COMMAND"]
        assert "UserKnownHostsFile=/keys/known_hosts" in cmd
        assert "StrictHostKeyChecking=yes" in cmd
        assert "accept-new" not in cmd

    def test_full_command_override_wins(self, monkeypatch):
        monkeypatch.setenv("GIT_CLONE_SSH_KEY_PATH", "/keys/ignored")
        monkeypatch.setenv("GIT_CLONE_SSH_COMMAND", "ssh -i /other/key -p 2222")
        assert _ssh_clone_env()["GIT_SSH_COMMAND"] == "ssh -i /other/key -p 2222"

    def test_env_is_the_ssh_command_only(self, monkeypatch):
        """GitPython layers env over os.environ, so don't copy the whole thing.

        This server's environment holds POSTGRES_PASSWORD / GITHUB_TOKEN /
        JOERN_SERVER_AUTH_PASSWORD; none of it belongs in the Git object.
        """
        monkeypatch.setenv("CODEBADGER_TEST_MARKER", "1")
        assert list(_ssh_clone_env()) == ["GIT_SSH_COMMAND"]


class TestCloneRepository:
    """clone_repository URL/env behavior (git itself is mocked out)."""

    @pytest.fixture
    def recorder(self, monkeypatch):
        """Capture git.Repo.clone_from calls instead of cloning."""
        calls = []
        stripped = []

        def fake_clone_from(url, target, **kwargs):
            os.makedirs(target, exist_ok=True)
            calls.append({"url": url, "target": target, **kwargs})

        monkeypatch.setattr(git.Repo, "clone_from", staticmethod(fake_clone_from))
        monkeypatch.setattr(
            GitManager,
            "_strip_remote_credential",
            lambda self, repo_path, clean_url: stripped.append((repo_path, clean_url)),
        )
        return {"calls": calls, "stripped": stripped}

    async def test_github_token_injection_unchanged(self, tmp_path, recorder):
        # Historic behavior: https://<token>@github.com/... + post-clone strip.
        manager = GitManager(str(tmp_path))
        source = await manager.clone_repository(
            "https://github.com/user/repo", str(tmp_path / "cb"), token="ghp_abc"
        )
        assert source.endswith("/source")
        assert len(recorder["calls"]) == 1
        assert recorder["calls"][0]["url"] == "https://ghp_abc@github.com/user/repo"
        assert recorder["stripped"] == [(source, "https://github.com/user/repo")]

    async def test_ssh_clone_uses_ssh_command_env(
        self, tmp_path, recorder, monkeypatch
    ):
        monkeypatch.setenv("GIT_CLONE_EXTRA_HOSTS", "192.168.152.14:3000")
        monkeypatch.setenv("GIT_CLONE_SSH_KEY_PATH", "/keys/id_ed25519")
        manager = GitManager(str(tmp_path))
        url = "ssh://git@192.168.152.14:3000/ethan/demo.git"
        await manager.clone_repository(url, str(tmp_path / "cb"), branch="dev")
        call = recorder["calls"][0]
        # URL is passed through untouched; auth rides in GIT_SSH_COMMAND.
        assert call["url"] == url
        assert call["branch"] == "dev"
        assert "-i /keys/id_ed25519" in call["env"]["GIT_SSH_COMMAND"]
        # No URL credential was injected, so nothing to strip.
        assert recorder["stripped"] == []

    async def test_custom_host_http_url_rejected_before_clone(
        self, tmp_path, recorder, monkeypatch
    ):
        # Custom hosts are ssh-only: even an allowlisted host can't be cloned
        # over http(s).
        monkeypatch.setenv("GIT_CLONE_EXTRA_HOSTS", "192.168.152.14:3000")
        manager = GitManager(str(tmp_path))
        for url in (
            "http://192.168.152.14:3000/ethan/demo.git",
            "https://192.168.152.14:3000/ethan/demo",
        ):
            with pytest.raises(ValidationError):
                await manager.clone_repository(url, str(tmp_path / "cb"))
        assert recorder["calls"] == []

    async def test_off_allowlist_url_rejected_before_clone(self, tmp_path, recorder):
        manager = GitManager(str(tmp_path))
        with pytest.raises(ValidationError):
            await manager.clone_repository(
                "http://192.168.152.14:3000/ethan/demo.git", str(tmp_path / "cb")
            )
        assert recorder["calls"] == []
