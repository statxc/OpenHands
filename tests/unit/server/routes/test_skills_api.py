import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import SecretStr

from openhands.integrations.provider import ProviderToken, ProviderType
from openhands.microagent.microagent import KnowledgeMicroagent, RepoMicroagent
from openhands.microagent.types import MicroagentMetadata, MicroagentType
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
        return 'test-user'

    async def get_user_email(self) -> str | None:
        return 'test-email@whatever.com'

    async def get_access_token(self) -> SecretStr | None:
        return SecretStr('test-token')

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
        patch.dict(os.environ, {'SESSION_API_KEY': ''}, clear=False),
        patch('openhands.server.dependencies._SESSION_API_KEY', None),
        patch(
            'openhands.server.user_auth.user_auth.UserAuth.get_instance',
            return_value=MockUserAuth(),
        ),
        patch(
            'openhands.storage.settings.file_settings_store.FileSettingsStore.get_instance',
            AsyncMock(return_value=FileSettingsStore(InMemoryFileStore())),
        ),
    ):
        client = TestClient(app)
        yield client


def _make_repo_skills():
    """Create mock repo skills."""
    return {
        'test_repo': RepoMicroagent(
            name='test_repo',
            content='Test repo content',
            metadata=MicroagentMetadata(name='test_repo'),
            source='/test/test_repo.md',
            type=MicroagentType.REPO_KNOWLEDGE,
        ),
    }


def _make_knowledge_skills():
    """Create mock knowledge skills."""
    return {
        'test_knowledge': KnowledgeMicroagent(
            name='test_knowledge',
            content='Test knowledge content',
            metadata=MicroagentMetadata(
                name='test_knowledge',
                triggers=['testword'],
                type=MicroagentType.KNOWLEDGE,
            ),
            source='/test/test_knowledge.md',
            type=MicroagentType.KNOWLEDGE,
        ),
    }


@pytest.mark.asyncio
async def test_skills_endpoint_returns_skills(test_client):
    """Test that GET /api/skills returns a list of skills."""
    repo_skills = _make_repo_skills()
    knowledge_skills = _make_knowledge_skills()

    with patch(
        'openhands.server.routes.skills.load_microagents_from_dir',
        return_value=(repo_skills, knowledge_skills),
    ):
        response = test_client.get('/api/skills')

    assert response.status_code == 200
    data = response.json()
    assert 'skills' in data
    assert len(data['skills']) >= 2

    # Verify skill structure
    skill_names = [s['name'] for s in data['skills']]
    assert 'test_repo' in skill_names
    assert 'test_knowledge' in skill_names

    # Check knowledge skill has triggers
    knowledge_skill = next(s for s in data['skills'] if s['name'] == 'test_knowledge')
    assert knowledge_skill['triggers'] == ['testword']
    assert knowledge_skill['type'] == 'knowledge'

    # Check repo skill has no triggers
    repo_skill = next(s for s in data['skills'] if s['name'] == 'test_repo')
    assert repo_skill['triggers'] is None
    assert repo_skill['type'] == 'repo'


@pytest.mark.asyncio
async def test_skills_endpoint_handles_missing_dirs(test_client):
    """Test that the endpoint handles missing directories gracefully."""
    with patch(
        'openhands.server.routes.skills.load_microagents_from_dir',
        side_effect=FileNotFoundError('No such directory'),
    ):
        response = test_client.get('/api/skills')

    assert response.status_code == 200
    data = response.json()
    assert data['skills'] == []


@pytest.mark.asyncio
async def test_skills_endpoint_sorted_by_source_then_name(test_client):
    """Test that skills are sorted by source (global first) then by name."""
    global_repo = {
        'z_global': RepoMicroagent(
            name='z_global',
            content='content',
            metadata=MicroagentMetadata(name='z_global'),
            source='/test/z_global.md',
            type=MicroagentType.REPO_KNOWLEDGE,
        ),
        'a_global': RepoMicroagent(
            name='a_global',
            content='content',
            metadata=MicroagentMetadata(name='a_global'),
            source='/test/a_global.md',
            type=MicroagentType.REPO_KNOWLEDGE,
        ),
    }
    user_repo = {
        'b_user': RepoMicroagent(
            name='b_user',
            content='content',
            metadata=MicroagentMetadata(name='b_user'),
            source='/test/b_user.md',
            type=MicroagentType.REPO_KNOWLEDGE,
        ),
    }

    call_count = 0

    def mock_load(dir_path):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call is for global dir
            return (global_repo, {})
        else:
            # Second call is for user dir
            return (user_repo, {})

    with patch(
        'openhands.server.routes.skills.load_microagents_from_dir',
        side_effect=mock_load,
    ):
        response = test_client.get('/api/skills')

    assert response.status_code == 200
    data = response.json()
    skills = data['skills']

    # Global skills should come first, sorted by name
    assert skills[0]['name'] == 'a_global'
    assert skills[0]['source'] == 'global'
    assert skills[1]['name'] == 'z_global'
    assert skills[1]['source'] == 'global'
    # User skills should come last
    assert skills[2]['name'] == 'b_user'
    assert skills[2]['source'] == 'user'
