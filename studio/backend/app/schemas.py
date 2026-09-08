from typing import Optional, Any
from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class JobCreate(BaseModel):
    project_id: Optional[str] = None
    preset_id: Optional[str] = None
    engine: Optional[str] = None
    model: Optional[str] = None
    mode: str
    kind: str = "video"
    prompt: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class LoraCreate(BaseModel):
    name: str
    engine: str = "mock"
    compatible_model: Optional[str] = None
    description: str = ""
    strength: float = 1.0
    active: bool = True
    tags: list[str] = Field(default_factory=list)


class LoraUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    strength: Optional[float] = None
    active: Optional[bool] = None
    tags: Optional[list[str]] = None
    compatible_model: Optional[str] = None


class SettingUpdate(BaseModel):
    key: str
    value: Any


class CloudConnectionUpdate(BaseModel):
    provider: Optional[str] = None
    worker_url: Optional[str] = None
    worker_port: Optional[int] = None
    worker_name: Optional[str] = None
    worker_token: Optional[str] = None


class CloudConnectionTest(BaseModel):
    provider: Optional[str] = None
    worker_url: Optional[str] = None
    worker_port: Optional[int] = None
    worker_token: Optional[str] = None
