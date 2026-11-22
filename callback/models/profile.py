from pydantic import BaseModel


class CreatedStory(BaseModel):
    id: str
    primary_skill: str
    skills: list[str]
    story_type: str
    job_title: str
    situation: str
    behavior: str
    impact: str


class OrphanedSkill(BaseModel):
    skill: str
    deferred: bool = False


class CompiledProfile(BaseModel):
    schema_version: str
    skills_index: list[str]  # union of all compiled_story.skills across stories
    stories: list[CreatedStory]
    orphaned_skills: list[OrphanedSkill]
    compiled_at: str
