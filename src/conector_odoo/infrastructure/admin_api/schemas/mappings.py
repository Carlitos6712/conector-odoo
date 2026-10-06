from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, Field, model_validator

from conector_odoo.application.mappings import MappingSuggestion, SaveResult
from conector_odoo.domain.mapping import StoredMapping, ValidationIssue
from conector_odoo.domain.mapping_codec import mapping_to_dict
from conector_odoo.domain.mapping_validation import DryRunReport
from conector_odoo.infrastructure.admin_api.schemas.common import StrictModel


class IssueOut(BaseModel):
    path: str
    severity: str
    message: str

    @classmethod
    def of(cls, issue: ValidationIssue) -> Self:
        return cls(path=issue.path, severity=issue.severity.value, message=issue.message)


class StoredMappingOut(BaseModel):
    name: str
    version: int
    created_at: datetime
    definition: dict[str, Any]

    @classmethod
    def of(cls, stored: StoredMapping) -> Self:
        return cls(
            name=stored.name,
            version=stored.version,
            created_at=stored.created_at,
            definition=mapping_to_dict(stored.definition),
        )


class StoredMappingListOut(BaseModel):
    items: list[StoredMappingOut]


class MappingPutIn(StrictModel):
    """``definition`` follows the versioned mapping JSON (see ``domain/mapping_codec.py``).

    The profile ids are optional: when given, the definition is also checked against the live
    schemas of those profiles (unreachable profiles only skip that extra check)."""

    definition: dict[str, Any]
    source_profile_id: int | None = None
    target_profile_id: int | None = None


class MappingSaveOut(BaseModel):
    mapping: StoredMappingOut
    created: bool
    warnings: list[IssueOut]

    @classmethod
    def of(cls, result: SaveResult) -> Self:
        return cls(
            mapping=StoredMappingOut.of(result.stored),
            created=result.created,
            warnings=[IssueOut.of(i) for i in result.warnings],
        )


class DryRunIn(StrictModel):
    """A draft ``definition`` or a saved mapping by ``name`` (and optional ``version``)."""

    definition: dict[str, Any] | None = None
    name: str | None = None
    version: int | None = Field(default=None, ge=1)
    source_profile_id: int
    target_profile_id: int
    limit: int = Field(default=10, ge=1, le=50)

    @model_validator(mode="after")
    def _exactly_one_subject(self) -> Self:
        if (self.definition is None) == (self.name is None):
            raise ValueError("provide exactly one of definition or name")
        return self


class RuleErrorOut(BaseModel):
    rule_target: str
    step_index: int | None
    message: str


class DryRunItemOut(BaseModel):
    source_id: str | None
    ok: bool
    mapped_fields: dict[str, Any]
    errors: list[RuleErrorOut]
    validation: list[IssueOut]


class DryRunOut(BaseModel):
    items: list[DryRunItemOut]
    total: int
    ok: int
    with_errors: int
    definition_issues: list[IssueOut]

    @classmethod
    def of(cls, report: DryRunReport) -> Self:
        return cls(
            items=[
                DryRunItemOut(
                    source_id=i.source_id,
                    ok=i.ok,
                    mapped_fields=i.mapped_fields,
                    errors=[
                        RuleErrorOut(
                            rule_target=e.rule_target, step_index=e.step_index, message=e.message
                        )
                        for e in i.errors
                    ],
                    validation=[IssueOut.of(v) for v in i.validation],
                )
                for i in report.items
            ],
            total=report.summary.total,
            ok=report.summary.ok,
            with_errors=report.summary.with_errors,
            definition_issues=[IssueOut.of(i) for i in report.definition_issues],
        )


class SuggestIn(StrictModel):
    source_profile_id: int
    source_resource: str = Field(min_length=1)
    target_profile_id: int
    target_resource: str = Field(min_length=1)


class SuggestOut(BaseModel):
    definition: dict[str, Any]
    unmatched_source: list[str]
    unmatched_target: list[str]

    @classmethod
    def of(cls, suggestion: MappingSuggestion) -> Self:
        return cls(
            definition=mapping_to_dict(suggestion.definition),
            unmatched_source=list(suggestion.unmatched_source),
            unmatched_target=list(suggestion.unmatched_target),
        )
