from typing import Any

from conector_odoo.domain.mapping import Expr, MappingDefinition, MappingRule, Step, Transform
from conector_odoo.domain.records import Record


def rec(id: str | None = "1", **fields: Any) -> Record:
    return Record(id=id, fields=fields)


def definition(*rules: MappingRule, name: str = "m") -> MappingDefinition:
    return MappingDefinition(
        name=name, source_resource="src", target_resource="dst", rules=tuple(rules)
    )


def rule(target: str, expr: Expr, *, required: bool = False) -> MappingRule:
    return MappingRule(target=target, expr=expr, required=required)


def steps(source: Expr, *chain: Step) -> Transform:
    return Transform(input=source, steps=tuple(chain))
