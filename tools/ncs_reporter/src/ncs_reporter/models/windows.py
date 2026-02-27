from typing import Any
from pydantic import BaseModel, Field, ConfigDict
from .base import BaseAuditModel


class WindowsContext(BaseModel):
    model_config = ConfigDict(extra="ignore")
    
    config: dict[str, Any] = Field(default_factory=dict)
    services: dict[str, Any] = Field(default_factory=dict)
    applications: dict[str, Any] = Field(default_factory=dict)
    updates: dict[str, Any] = Field(default_factory=dict)


class WindowsAuditModel(BaseAuditModel):
    model_config = ConfigDict(extra="ignore")
    
    windows_audit: dict[str, Any] # Wrapped structure for parity
