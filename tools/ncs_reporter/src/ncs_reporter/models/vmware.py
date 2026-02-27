from typing import Any
from pydantic import BaseModel, Field, ConfigDict
from .base import BaseAuditModel


class VMwareApplianceHealth(BaseModel):
    model_config = ConfigDict(extra="ignore")
    
    overall: str = "gray"
    cpu: str = "gray"
    memory: str = "gray"
    database: str = "gray"
    storage: str = "gray"
    swap: str = "gray"


class VMwareApplianceInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    
    product: str = "vCenter Server"
    version: str = "unknown"
    build: str = "unknown"
    uptime_days: int = 0


class VMwareAppliance(BaseModel):
    model_config = ConfigDict(extra="ignore")
    
    info: VMwareApplianceInfo = Field(default_factory=VMwareApplianceInfo)
    health: VMwareApplianceHealth = Field(default_factory=VMwareApplianceHealth)
    config: dict[str, Any] = Field(default_factory=dict)
    backup: dict[str, Any] = Field(default_factory=dict)


class VMwareUtilization(BaseModel):
    model_config = ConfigDict(extra="ignore")
    
    cpu_total_mhz: int = 0
    cpu_used_mhz: int = 0
    cpu_pct: float = 0.0
    memory_total_mb: int = 0
    memory_used_mb: int = 0
    memory_pct: float = 0.0


class VMwareDiscoverySummary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    
    clusters: int = 0
    hosts: int = 0
    vms: int = 0
    datastores: int = 0


class VMwareDiscoveryContext(BaseModel):
    model_config = ConfigDict(extra="ignore")
    
    audit_type: str = "discovery"
    system: dict[str, Any] = Field(default_factory=dict) # Includes utilization
    health: dict[str, Any] = Field(default_factory=dict) # Includes appliance, alarms
    inventory: dict[str, Any] = Field(default_factory=dict)
    summary: VMwareDiscoverySummary = Field(default_factory=VMwareDiscoverySummary)


class VMwareAuditModel(BaseAuditModel):
    model_config = ConfigDict(extra="ignore")
    
    discovery: VMwareDiscoveryContext
    vmware_vcenter: dict[str, Any] # For view-model parity
