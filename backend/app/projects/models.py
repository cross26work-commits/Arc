from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    path: str = Field(min_length=1)
    project_type: str = Field(default="software", max_length=50)


class ProjectResponse(BaseModel):
    id: int
    name: str
    path: str
    project_type: str
    status: str
    created_at: str
    updated_at: str
