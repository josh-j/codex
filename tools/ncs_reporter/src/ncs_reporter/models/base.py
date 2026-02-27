from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field, ConfigDict


class MetadataModel(BaseModel):
    model_config = ConfigDict(extra="ignore")
    
    host: Optional[str] = None
    audit_type: str
    timestamp: str
    generated_at: Optional[str] = Field(default_factory=lambda: datetime.now().isoformat())


class AlertModel(BaseModel):
    model_config = ConfigDict(extra="ignore")
    
    severity: str
    category: str
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)
    affected_items: list[Any] = Field(default_factory=list)
    recommendation: Optional[str] = None
    remediation: Optional[str] = None


class SummaryModel(BaseModel):
    model_config = ConfigDict(extra="ignore")
    
    total: int = 0
    critical_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    by_category: dict[str, int] = Field(default_factory=dict)


class BaseAuditModel(BaseModel):
    model_config = ConfigDict(extra="ignore")
    
    metadata: MetadataModel
    health: str = "UNKNOWN"
    summary: SummaryModel
    alerts: list[AlertModel] = Field(default_factory=list)
