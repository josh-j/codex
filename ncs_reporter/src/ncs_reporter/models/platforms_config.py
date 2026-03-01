from pydantic import BaseModel, ConfigDict


class PlatformEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_dir: str
    report_dir: str
    platform: str
    state_file: str
    render: bool = True
    schema_name: str | None = None  # overrides platform-based schema lookup


class PlatformsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platforms: list[PlatformEntry]
