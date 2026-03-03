from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from ncs_reporter.pathing import validate_template


class PlatformPaths(BaseModel):
    model_config = ConfigDict(extra="forbid")
    raw_stig_artifact: str
    report_fleet: str
    report_node_latest: str
    report_node_historical: str
    report_stig_host: str
    report_search_entry: str
    report_site: str
    report_stig_fleet: str

    @field_validator("*")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("path template must be a non-empty string")
        return value

    @model_validator(mode="after")
    def _validate_templates(self) -> PlatformPaths:
        all_allowed = {"report_dir", "hostname", "schema_name", "target_type", "report_stamp"}
        validate_template(
            self.raw_stig_artifact,
            allowed=all_allowed,
            required={"report_dir", "hostname", "target_type"},
            field_name="paths.raw_stig_artifact",
        )
        validate_template(
            self.report_fleet,
            allowed=all_allowed,
            required={"report_dir", "schema_name"},
            field_name="paths.report_fleet",
        )
        validate_template(
            self.report_node_latest,
            allowed=all_allowed,
            required={"report_dir", "hostname"},
            field_name="paths.report_node_latest",
        )
        validate_template(
            self.report_node_historical,
            allowed=all_allowed,
            required={"report_dir", "hostname", "report_stamp"},
            field_name="paths.report_node_historical",
        )
        validate_template(
            self.report_stig_host,
            allowed=all_allowed,
            required={"report_dir", "hostname", "target_type"},
            field_name="paths.report_stig_host",
        )
        validate_template(
            self.report_search_entry,
            allowed=all_allowed,
            required={"report_dir", "hostname"},
            field_name="paths.report_search_entry",
        )
        validate_template(
            self.report_site,
            allowed=all_allowed,
            required=set(),
            field_name="paths.report_site",
        )
        validate_template(
            self.report_stig_fleet,
            allowed=all_allowed,
            required=set(),
            field_name="paths.report_stig_fleet",
        )
        return self


class PlatformEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_dir: str
    report_dir: str
    platform: str
    state_file: str
    render: bool = True
    schema_name: str | None = None  # overrides platform-based schema lookup
    target_types: list[str]
    paths: PlatformPaths


class PlatformsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platforms: list[PlatformEntry]
