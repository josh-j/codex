from typing import Any
from pydantic import Field, ConfigDict
from .base import BaseAuditModel


class STIGAuditModel(BaseAuditModel):
    model_config = ConfigDict(extra="ignore")
    
    target_type: str = ""
    full_audit: list[dict[str, Any]] = Field(default_factory=list)
