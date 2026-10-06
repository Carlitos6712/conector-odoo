"""Use cases for mappings: save (validated, versioned), read, delete, dry-run and suggestions.

Schemas and sample records come from injected callables, so these use cases never touch profiles,
secrets or adapters; the composition root decides how a resource name becomes a live schema.
"""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from conector_odoo.domain.errors import MappingNotFound, ResourceNotFound
from conector_odoo.domain.mapping import (
    SCHEMA_VERSION,
    Direct,
    Expr,
    MappingDefinition,
    MappingRule,
    MappingValidationFailed,
    Severity,
    StoredMapping,
    ToString,
    Transform,
    ValidationIssue,
)
from conector_odoo.domain.mapping_validation import DryRunReport, dry_run, validate_definition
from conector_odoo.domain.ports import MappingRepository
from conector_odoo.domain.records import FieldSpec, FieldType, Record, ResourceSchema

DRY_RUN_MAX_LIMIT = 50

# (source schema, target schema) of a definition's resources; ``None`` when not resolvable.
SchemaResolver = Callable[
    [MappingDefinition], Awaitable[tuple[ResourceSchema | None, ResourceSchema | None]]
]
SampleProvider = Callable[[MappingDefinition, int], Awaitable[list[Record]]]


@dataclass(frozen=True, slots=True)
class SaveResult:
    stored: StoredMapping
    warnings: list[ValidationIssue]
    created: bool  # False when the definition equals the latest version (nothing was stored)


class SaveMapping:
    def __init__(self, repo: MappingRepository, schemas: SchemaResolver | None = None) -> None:
        self._repo = repo
        self._schemas = schemas

    async def execute(self, definition: MappingDefinition) -> SaveResult:
        """Raises ``MappingValidationFailed`` (nothing is stored) when there are errors; warnings
        are returned with the saved version."""
        source, target = await self._schemas(definition) if self._schemas else (None, None)
        issues = validate_definition(definition, source, target)
        if any(issue.severity is Severity.ERROR for issue in issues):
            raise MappingValidationFailed(issues)
        before = await self._repo.get(definition.name)
        stored = await self._repo.save_new_version(definition)
        created = before is None or before.version != stored.version
        return SaveResult(stored, issues, created)


class GetMapping:
    def __init__(self, repo: MappingRepository) -> None:
        self._repo = repo

    async def execute(self, name: str, version: int | None = None) -> StoredMapping:
        stored = await self._repo.get(name, version)
        if stored is None:
            suffix = "" if version is None else f" version {version}"
            raise MappingNotFound(f"mapping {name!r}{suffix} not found")
        return stored


class ListMappings:
    def __init__(self, repo: MappingRepository) -> None:
        self._repo = repo

    async def execute(self) -> list[StoredMapping]:
        return await self._repo.list_latest()


class ListMappingVersions:
    def __init__(self, repo: MappingRepository) -> None:
        self._repo = repo

    async def execute(self, name: str) -> list[StoredMapping]:
        versions = await self._repo.list_versions(name)
        if not versions:
            raise MappingNotFound(f"mapping {name!r} not found")
        return versions


class DeleteMapping:
    def __init__(self, repo: MappingRepository) -> None:
        self._repo = repo

    async def execute(self, name: str) -> None:
        """Raises ``MappingNotFound`` or ``MappingInUse`` (a sync job references it)."""
        await self._repo.delete(name)


class DryRunMapping:
    def __init__(
        self, repo: MappingRepository, schemas: SchemaResolver, samples: SampleProvider
    ) -> None:
        self._repo = repo
        self._schemas = schemas
        self._samples = samples

    async def execute(self, definition: MappingDefinition, limit: int = 10) -> DryRunReport:
        """Map a sample of the source (``limit`` clamped to ``1..DRY_RUN_MAX_LIMIT``) without
        writing anything. Works for unsaved drafts. Raises ``ResourceNotFound`` when the target
        schema cannot be resolved."""
        limit = max(1, min(limit, DRY_RUN_MAX_LIMIT))
        source, target = await self._schemas(definition)
        if target is None:
            raise ResourceNotFound(f"schema of {definition.target_resource!r} is not available")
        records = await self._samples(definition, limit)
        return dry_run(definition, records[:limit], target, source)

    async def execute_saved(
        self, name: str, version: int | None = None, limit: int = 10
    ) -> DryRunReport:
        return await self.execute(
            (await GetMapping(self._repo).execute(name, version)).definition, limit
        )


# -- suggestions -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MappingSuggestion:
    definition: MappingDefinition
    unmatched_source: tuple[str, ...]
    unmatched_target: tuple[str, ...]


_CAMEL = re.compile(r"([a-z0-9])([A-Z])")
_SCALARS = {FieldType.INTEGER, FieldType.NUMBER, FieldType.BOOLEAN}
_SAME_FAMILY = {
    (FieldType.INTEGER, FieldType.NUMBER),
    (FieldType.STRING, FieldType.DATE),
    (FieldType.STRING, FieldType.DATETIME),
    (FieldType.DATE, FieldType.DATETIME),
}


def _normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _CAMEL.sub(r"\1_\2", name).lower())


def _expression(source: FieldSpec, target: FieldSpec) -> Expr | None:
    """Direct read when the types are compatible, a ``to_string`` for scalars into text, else
    ``None`` (incompatible)."""
    if FieldType.UNKNOWN in (source.type, target.type) or source.type is target.type:
        return Direct(source.name)
    if (source.type, target.type) in _SAME_FAMILY:
        return Direct(source.name)
    if target.type is FieldType.STRING and source.type in _SCALARS:
        return Transform(Direct(source.name), (ToString(),))
    return None


def suggest_mapping(source: ResourceSchema, target: ResourceSchema) -> MappingSuggestion:
    """Draft ``Direct`` rules for source/target fields whose names match after normalising case,
    snake/camel/space/punctuation differences and whose types are compatible. Read-only targets
    are never proposed. Each source field is used at most once."""
    by_name: dict[str, list[FieldSpec]] = {}
    for spec in source.fields:
        by_name.setdefault(_normalise(spec.name), []).append(spec)
    used: set[str] = set()
    rules: list[MappingRule] = []
    unmatched_target: list[str] = []
    for spec in target.fields:
        if spec.readonly:
            continue
        for candidate in by_name.get(_normalise(spec.name), []):
            expr = _expression(candidate, spec) if candidate.name not in used else None
            if expr is not None:
                used.add(candidate.name)
                rules.append(MappingRule(spec.name, expr, required=spec.required))
                break
        else:
            unmatched_target.append(spec.name)
    return MappingSuggestion(
        MappingDefinition(
            name=f"{source.name}_to_{target.name}",
            source_resource=source.name,
            target_resource=target.name,
            rules=tuple(rules),
            schema_version=SCHEMA_VERSION,
        ),
        tuple(s.name for s in source.fields if s.name not in used),
        tuple(unmatched_target),
    )
