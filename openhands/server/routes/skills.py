from fastapi import APIRouter
from pydantic import BaseModel

from openhands.core.logger import openhands_logger as logger

# NOTE: These imports still use the legacy "microagent" naming from shared modules.
# The underlying APIs will be renamed to "skills" as part of the broader migration.
from openhands.memory.memory import GLOBAL_MICROAGENTS_DIR, USER_MICROAGENTS_DIR
from openhands.microagent import load_microagents_from_dir
from openhands.server.dependencies import get_dependencies

app = APIRouter(prefix='/api', dependencies=get_dependencies())


class SkillInfo(BaseModel):
    """Information about a single available skill."""

    name: str
    type: str  # 'knowledge', 'repo', or 'task'
    source: str  # 'global' or 'user'
    triggers: list[str] | None = None


class SkillListResponse(BaseModel):
    """Response model for the skills list endpoint."""

    skills: list[SkillInfo]


@app.get(
    '/skills',
    response_model=SkillListResponse,
)
async def list_skills() -> SkillListResponse:
    """List all available global and user-level skills.

    Returns skill metadata so the frontend can render a toggle list.
    """
    skills: list[SkillInfo] = []

    # Load global skills
    try:
        repo_skills, knowledge_skills = load_microagents_from_dir(
            GLOBAL_MICROAGENTS_DIR
        )
        for repo_skill in repo_skills.values():
            skills.append(
                SkillInfo(
                    name=repo_skill.name,
                    type=repo_skill.type.value,
                    source='global',
                )
            )
        for knowledge_skill in knowledge_skills.values():
            triggers = (
                knowledge_skill.metadata.triggers
                if knowledge_skill.metadata.triggers
                else None
            )
            skills.append(
                SkillInfo(
                    name=knowledge_skill.name,
                    type=knowledge_skill.type.value,
                    source='global',
                    triggers=triggers,
                )
            )
    except Exception as e:
        logger.warning(f'Failed to load global skills: {e}')

    # Load user-level skills
    try:
        repo_skills, knowledge_skills = load_microagents_from_dir(USER_MICROAGENTS_DIR)
        for repo_skill in repo_skills.values():
            skills.append(
                SkillInfo(
                    name=repo_skill.name,
                    type=repo_skill.type.value,
                    source='user',
                )
            )
        for knowledge_skill in knowledge_skills.values():
            triggers = (
                knowledge_skill.metadata.triggers
                if knowledge_skill.metadata.triggers
                else None
            )
            skills.append(
                SkillInfo(
                    name=knowledge_skill.name,
                    type=knowledge_skill.type.value,
                    source='user',
                    triggers=triggers,
                )
            )
    except Exception as e:
        logger.warning(f'Failed to load user skills: {e}')

    # Sort by source (global first), then by name
    skills.sort(key=lambda s: (s.source, s.name))
    return SkillListResponse(skills=skills)
