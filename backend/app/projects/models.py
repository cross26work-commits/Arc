from typing import Literal

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


class FileTreeItem(BaseModel):
    name: str
    path: str
    type: Literal["directory", "file"]
    size: int | None = None
    children: list["FileTreeItem"] | None = None


class ProjectTreeResponse(BaseModel):
    project_id: int
    project_name: str
    root_name: str
    root_path: str
    entries: list[FileTreeItem]
    entry_count: int
    truncated: bool
    excluded_names: list[str]
    max_depth: int
    max_entries: int


class FileContentResponse(BaseModel):
    project_id: int
    project_name: str
    relative_path: str
    language: str
    size_bytes: int
    line_count: int
    content: str
    truncated: bool
