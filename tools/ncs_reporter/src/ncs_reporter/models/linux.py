from typing import Any
from pydantic import BaseModel, Field, ConfigDict
from .base import BaseAuditModel


class LinuxSystemInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    
    hostname: str = ""
    ip: str = "N/A"
    kernel: str = "unknown"
    uptime_days: int = 0
    load_avg: float = 0.0
    memory: dict[str, Any] = Field(default_factory=dict)
    swap: dict[str, Any] = Field(default_factory=dict)
    services: dict[str, Any] = Field(default_factory=dict)
    disks: list[dict[str, Any]] = Field(default_factory=list)


class LinuxContext(BaseModel):
    model_config = ConfigDict(extra="ignore")
    
    system: LinuxSystemInfo = Field(default_factory=LinuxSystemInfo)
    updates: dict[str, Any] = Field(default_factory=dict)
    security: dict[str, Any] = Field(default_factory=dict)


class LinuxAuditModel(BaseAuditModel):
    model_config = ConfigDict(extra="ignore")
    
    ubuntu_ctx: LinuxContext
    linux_system: dict[str, Any] # For view-model parity
