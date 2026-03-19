import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import SecretStr

from openhands.integrations.provider import ProviderToken, ProviderType
from openhands.server.app import app
from openhands.server.user_auth.user_auth import UserAuth
from openhands.storage.data_models.secrets import Secrets
from openhands.storage.memory import InMemoryFileStore
from openhands.storage.secrets.secrets_store import SecretsStore
from openhands.storage.settings.file_settings_store import FileSettingsStore
from openhands.storage.settings.settings_store import SettingsStore


class MockUserAuth(UserAuth):
    """Mock implementation of UserAuth for testing."""

    def __init__(self):
        self._settings = None
        self._settings_store = MagicMock()
        self._settings_store.load = AsyncMock(return_value=None)
        self._settings_store.store = AsyncMock()

    async def get_user_id(self) -> str | None:
        return "test-user"

    async def get_user_email(self) -> str | None:
        return "test-email@whatever.com"

    async def get_access_token(self) -> SecretStr | None:
        return SecretStr("test-token")

    async def get_provider_tokens(
        self,
    ) -> dict[ProviderType, ProviderToken] | None:
        return None

    async def get_user_settings_store(self) -> SettingsStore | None:
        return self._settings_store

    async def get_secrets_store(self) -> SecretsStore | None:
        return None

    async def get_secrets(self) -> Secrets | None:
        return None

    async def get_mcp_api_key(self) -> str | None:
        return None

    @classmethod
    async def get_instance(cls, request: Request) -> UserAuth:
        return MockUserAuth()

    @classmethod
    async def get_for_user(cls, user_id: str) -> UserAuth:
        return MockUserAuth()


@pytest.fixture
def test_client():
    with (
        patch.dict(os.environ, {"SESSION_API_KEY": ""}, clear=False),
        patch("openhands.server.dependencies._SESSION_API_KEY", None),
        patch(
            "openhands.server.user_auth.user_auth.UserAuth.get_instance",
            return_value=MockUserAuth(),
        ),
        patch(
            "openhands.storage.settings.file_settings_store.FileSettingsStore.get_instance",
            AsyncMock(return_value=FileSettingsStore(InMemoryFileStore())),
        ),
    ):
        client = TestClient(app)
        yield client


def _write_skill_file(
    dir_path: Path,
    name: str,
    skill_type: str = "knowledge",
    triggers: list[str] | None = None,
) -> None:
    """Write a mock skill markdown file with frontmatter."""
    dir_path.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"name: {name}",
        f"type: {skill_type}",
    ]
    if triggers:
        lines.append("triggers:")
        for t in triggers:
            lines.append(f"- {t}")
    lines.append("---")
    lines.append(f"{name} content")
    (dir_path / f"{name}.md").write_text("\n".join(lines))


@pytest.mark.asyncio
async def test_skills_endpoint_returns_skills(test_client, tmp_path):
    """Test that GET /api/v1/skills returns a list of skills."""
    global_dir = tmp_path / "global"
    _write_skill_file(global_dir, "test_repo", skill_type="repo")
    _write_skill_file(
        global_dir, "test_knowledge", skill_type="knowledge", triggers=["testword"]
    )

    with (
        patch("openhands.app_server.user.skills_router.GLOBAL_SKILLS_DIR", global_dir),
        patch(
            "openhands.app_server.user.skills_router.USER_SKILLS_DIR",
            tmp_path / "nonexistent",
        ),
    ):
        response = test_client.get("/api/v1/skills")

    assert response.status_code == 200
    data = response.json()
    assert "skills" in data
    assert len(data["skills"]) == 2

    # Verify skill structure
    skill_names = [s["name"] for s in data["skills"]]
    assert "test_repo" in skill_names
    assert "test_knowledge" in skill_names

    # Check knowledge skill has triggers
    knowledge_skill = next(s for s in data["skills"] if s["name"] == "test_knowledge")
    assert knowledge_skill["triggers"] == ["testword"]
    assert knowledge_skill["type"] == "knowledge"

    # Check repo skill has no triggers
    repo_skill = next(s for s in data["skills"] if s["name"] == "test_repo")
    assert repo_skill["triggers"] is None
    assert repo_skill["type"] == "repo"


@pytest.mark.asyncio
async def test_skills_endpoint_handles_missing_dirs(test_client, tmp_path):
    """Test that the endpoint handles missing directories gracefully."""
    with (
        patch(
            "openhands.app_server.user.skills_router.GLOBAL_SKILLS_DIR",
            tmp_path / "no_such_dir",
        ),
        patch(
            "openhands.app_server.user.skills_router.USER_SKILLS_DIR",
            tmp_path / "also_missing",
        ),
    ):
        response = test_client.get("/api/v1/skills")

    assert response.status_code == 200
    data = response.json()
    assert data["skills"] == []


@pytest.mark.asyncio
async def test_skills_endpoint_sorted_by_source_then_name(test_client, tmp_path):
    """Test that skills are sorted by source (global first) then by name."""
    global_dir = tmp_path / "global"
    user_dir = tmp_path / "user"

    _write_skill_file(global_dir, "z_global", skill_type="repo")
    _write_skill_file(global_dir, "a_global", skill_type="repo")
    _write_skill_file(user_dir, "b_user", skill_type="repo")

    with (
        patch("openhands.app_server.user.skills_router.GLOBAL_SKILLS_DIR", global_dir),
        patch("openhands.app_server.user.skills_router.USER_SKILLS_DIR", user_dir),
    ):
        response = test_client.get("/api/v1/skills")

    assert response.status_code == 200
    data = response.json()
    skills = data["skills"]

    # Global skills should come first, sorted by name
    assert skills[0]["name"] == "a_global"
    assert skills[0]["source"] == "global"
    assert skills[1]["name"] == "z_global"
    assert skills[1]["source"] == "global"
    # User skills should come last
    assert skills[2]["name"] == "b_user"
    assert skills[2]["source"] == "user"
