import sqlite3
from collections.abc import Iterator

import pytest

from conector_odoo.application.mappings import (
    DeleteMapping,
    DryRunMapping,
    GetMapping,
    ListMappings,
    ListMappingVersions,
    SaveMapping,
    suggest_mapping,
)
from conector_odoo.domain.errors import MappingNotFound, ResourceNotFound
from conector_odoo.domain.mapping import (
    Constant,
    Direct,
    MappingDefinition,
    MappingValidationFailed,
    Severity,
    ToInt,
    ToString,
    Transform,
)
from conector_odoo.domain.records import FieldSpec, FieldType, Record, ResourceSchema
from conector_odoo.infrastructure.mappings.repository import SqliteMappingRepository
from conector_odoo.infrastructure.migrations import open_admin_database
from tests.mapping.helpers import definition, rule, steps
from tests.unit.fakes_records import InMemoryRecordEndpoint

SOURCE = ResourceSchema(
    "src", "Src", (FieldSpec("n", FieldType.STRING), FieldSpec("a", FieldType.STRING))
)
TARGET = ResourceSchema(
    "dst",
    "Dst",
    (
        FieldSpec("name", FieldType.STRING, required=True),
        FieldSpec("age", FieldType.INTEGER),
    ),
)


@pytest.fixture
def repo() -> Iterator[SqliteMappingRepository]:
    conn: sqlite3.Connection = open_admin_database(":memory:")
    yield SqliteMappingRepository(conn)
    conn.close()


async def schemas(_: MappingDefinition) -> tuple[ResourceSchema | None, ResourceSchema | None]:
    return SOURCE, TARGET


GOOD = definition(rule("name", Direct("n")), rule("age", steps(Direct("a"), ToInt())))


async def test_save_validates_returns_warnings_and_versions(repo: SqliteMappingRepository) -> None:
    save = SaveMapping(repo, schemas)
    d = definition(rule("name", Direct("n")), rule("age", Direct("ghost")))
    first = await save.execute(d)
    assert first.created and first.stored.version == 1
    assert [(w.path, w.severity) for w in first.warnings] == [
        ("rules[1].expr.source", Severity.WARNING)
    ]
    again = await save.execute(d)
    assert not again.created and again.stored.version == 1
    changed = await save.execute(GOOD)
    assert changed.created and changed.stored.version == 2 and changed.warnings == []


async def test_save_blocks_on_errors_and_stores_nothing(repo: SqliteMappingRepository) -> None:
    save = SaveMapping(repo, schemas)
    with pytest.raises(MappingValidationFailed) as excinfo:
        await save.execute(definition(rule("zzz", Constant(1)), name="bad"))
    assert {i.path for i in excinfo.value.issues if i.severity is Severity.ERROR} == {
        "rules[0].target",
        "target.name",
    }
    assert await repo.get("bad") is None


async def test_save_without_schema_resolver_still_checks_structure(
    repo: SqliteMappingRepository,
) -> None:
    save = SaveMapping(repo)
    with pytest.raises(MappingValidationFailed):
        await save.execute(definition(rule("a", Constant(1)), rule("a", Constant(2))))
    assert (await save.execute(definition(rule("a", Constant(1))))).stored.version == 1


async def test_get_list_and_versions(repo: SqliteMappingRepository) -> None:
    save = SaveMapping(repo)
    await save.execute(definition(rule("a", Constant(1)), name="x"))
    await save.execute(definition(rule("a", Constant(2)), name="x"))
    await save.execute(definition(rule("a", Constant(1)), name="y"))
    assert (await GetMapping(repo).execute("x")).version == 2
    assert (await GetMapping(repo).execute("x", 1)).version == 1
    assert [m.name for m in await ListMappings(repo).execute()] == ["x", "y"]
    assert [m.version for m in await ListMappingVersions(repo).execute("x")] == [1, 2]
    with pytest.raises(MappingNotFound):
        await GetMapping(repo).execute("nope")
    with pytest.raises(MappingNotFound):
        await GetMapping(repo).execute("x", 7)
    with pytest.raises(MappingNotFound):
        await ListMappingVersions(repo).execute("nope")


async def test_delete(repo: SqliteMappingRepository) -> None:
    await SaveMapping(repo).execute(definition(rule("a", Constant(1)), name="x"))
    await DeleteMapping(repo).execute("x")
    with pytest.raises(MappingNotFound):
        await DeleteMapping(repo).execute("x")


async def sample(d: MappingDefinition, limit: int) -> list[Record]:
    endpoint = InMemoryRecordEndpoint({d.source_resource: SOURCE})
    for i in range(30):
        endpoint.seed(d.source_resource, {"n": f"N{i}", "a": str(i)})
    return await endpoint.sample(d.source_resource, limit)


async def test_dry_run_of_a_draft_and_of_a_saved_mapping(repo: SqliteMappingRepository) -> None:
    dry = DryRunMapping(repo, schemas, sample)
    report = await dry.execute(GOOD, limit=3)
    assert report.summary.total == 3 and report.summary.ok == 3
    assert report.items[1].mapped_fields == {"name": "N1", "age": 1}
    await SaveMapping(repo).execute(GOOD)
    saved = await dry.execute_saved("m", limit=2)
    assert saved.summary.total == 2
    with pytest.raises(MappingNotFound):
        await dry.execute_saved("nope")


async def test_dry_run_limit_is_clamped(repo: SqliteMappingRepository) -> None:
    dry = DryRunMapping(repo, schemas, sample)
    assert (await dry.execute(GOOD, limit=0)).summary.total == 1
    assert (await dry.execute(GOOD, limit=500)).summary.total == 30


async def test_dry_run_needs_a_known_target_schema(repo: SqliteMappingRepository) -> None:
    async def none(_: MappingDefinition) -> tuple[None, None]:
        return None, None

    with pytest.raises(ResourceNotFound):
        await DryRunMapping(repo, none, sample).execute(GOOD)


# -- suggest_mapping ---------------------------------------------------------------------------


def fields(*specs: FieldSpec) -> ResourceSchema:
    return ResourceSchema("r", "R", specs)


def test_suggest_matches_normalised_names_and_compatible_types() -> None:
    src = fields(
        FieldSpec("firstName", FieldType.STRING),
        FieldSpec("Last Name", FieldType.STRING),
        FieldSpec("ZIP-code", FieldType.STRING),
        FieldSpec("age", FieldType.INTEGER),
        FieldSpec("extra", FieldType.STRING),
    )
    dst = fields(
        FieldSpec("first_name", FieldType.STRING, required=True),
        FieldSpec("last_name", FieldType.STRING),
        FieldSpec("zipcode", FieldType.STRING),
        FieldSpec("age", FieldType.NUMBER),
        FieldSpec("missing_one", FieldType.STRING),
    )
    s = suggest_mapping(src, dst)
    assert [(r.target, r.expr, r.required) for r in s.definition.rules] == [
        ("first_name", Direct("firstName"), True),
        ("last_name", Direct("Last Name"), False),
        ("zipcode", Direct("ZIP-code"), False),
        ("age", Direct("age"), False),
    ]
    assert s.unmatched_source == ("extra",)
    assert s.unmatched_target == ("missing_one",)
    assert s.definition.source_resource == "r" and s.definition.target_resource == "r"


def test_suggest_skips_readonly_targets_and_incompatible_types() -> None:
    src = fields(FieldSpec("id", FieldType.STRING), FieldSpec("born", FieldType.BOOLEAN))
    dst = fields(
        FieldSpec("id", FieldType.STRING, readonly=True),
        FieldSpec("born", FieldType.DATE),
    )
    s = suggest_mapping(src, dst)
    assert s.definition.rules == ()
    assert s.unmatched_source == ("id", "born")
    assert s.unmatched_target == ("born",)


def test_suggest_converts_scalars_into_string_targets() -> None:
    src = fields(FieldSpec("code", FieldType.INTEGER), FieldSpec("ok", FieldType.UNKNOWN))
    dst = fields(FieldSpec("code", FieldType.STRING), FieldSpec("ok", FieldType.BOOLEAN))
    s = suggest_mapping(src, dst)
    assert s.definition.rules[0].expr == Transform(Direct("code"), (ToString(),))
    assert s.definition.rules[1].expr == Direct("ok")


def test_suggest_uses_each_source_once_and_names_the_draft() -> None:
    src = fields(FieldSpec("Name", FieldType.STRING), FieldSpec("name", FieldType.STRING))
    dst = fields(FieldSpec("name", FieldType.STRING), FieldSpec("NAME", FieldType.STRING))
    s = suggest_mapping(src, dst)
    assert [(r.target, r.expr) for r in s.definition.rules] == [
        ("name", Direct("Name")),
        ("NAME", Direct("name")),
    ]
    assert s.definition.name == "r_to_r"
    assert s.unmatched_source == () and s.unmatched_target == ()
