"""Minimal in-memory fake Odoo (JSON-RPC) for the Playwright e2e suite. Tests-only.

It implements exactly what the connector's generic Odoo adapter calls over ``POST /jsonrpc``:

* ``common.authenticate``
* ``object.execute_kw`` with ``fields_get``, ``search_read``, ``read``, ``create``, ``write`` on
  ``res.partner`` (plus ``ir.model`` for model discovery).

It is NOT Odoo: domains are ANDed ``[field, op, value]`` triples, there are no access rights,
computed fields or constraints beyond "name is required" and "no unknown fields". Run it with
``uv run python -m tests.e2e_support.fake_odoo --port 8169``.
"""

import argparse
from dataclasses import dataclass, field
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

UID = 2

# name -> (type, extra attributes). ``id`` is implicit.
_PARTNER_FIELDS: dict[str, dict[str, Any]] = {
    "name": {"string": "Name", "type": "char", "required": True},
    "ref": {"string": "Reference", "type": "char"},
    "email": {"string": "Email", "type": "char"},
    "phone": {"string": "Phone", "type": "char"},
    "vat": {"string": "Tax ID", "type": "char"},
    "street": {"string": "Street", "type": "char"},
    "city": {"string": "City", "type": "char"},
    "comment": {"string": "Notes", "type": "html"},
    "active": {"string": "Active", "type": "boolean"},
    "country_id": {"string": "Country", "type": "many2one", "relation": "res.country"},
}
_IR_MODEL_FIELDS: dict[str, dict[str, Any]] = {
    "model": {"string": "Model", "type": "char", "required": True},
    "name": {"string": "Model Description", "type": "char", "required": True},
    "transient": {"string": "Transient Model", "type": "boolean"},
}
_SCHEMAS = {"res.partner": _PARTNER_FIELDS, "ir.model": _IR_MODEL_FIELDS}
_DEFAULTS = {"res.partner": {"active": True}}


@dataclass(frozen=True)
class FakeOdooConfig:
    db: str = "e2e"
    login: str = "admin"
    api_key: str = "e2e-odoo-api-key-0123456789"


class OdooFault(Exception):
    def __init__(self, name: str, message: str) -> None:
        super().__init__(message)
        self.name = name


@dataclass
class _Store:
    tables: dict[str, dict[int, dict[str, Any]]] = field(default_factory=dict)
    next_id: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.tables = {"res.partner": {}}
        self.next_id = {"res.partner": 1}

    def rows(self, model: str) -> list[dict[str, Any]]:
        if model == "ir.model":
            return [
                {"id": i, "model": m, "name": "Contact" if m == "res.partner" else m}
                | {"transient": False}
                for i, m in enumerate(sorted(self.tables), start=1)
            ]
        return [self.tables[model][i] for i in sorted(self.tables[model])]


def _schema(model: str) -> dict[str, dict[str, Any]]:
    if model not in _SCHEMAS:
        raise OdooFault("odoo.exceptions.MissingError", f"Object {model} doesn't exist")
    return _SCHEMAS[model]


def _present(row: dict[str, Any], fields: list[str] | None) -> dict[str, Any]:
    names = fields or ["id", *row.keys()]
    out: dict[str, Any] = {"id": row["id"]}
    for name in names:
        if name == "id":
            continue
        value = row.get(name)
        out[name] = False if value is None else value
    return out


_OPS = {
    "=": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a is not None and a > b,
    ">=": lambda a, b: a is not None and a >= b,
    "<": lambda a, b: a is not None and a < b,
    "<=": lambda a, b: a is not None and a <= b,
    "in": lambda a, b: a in b,
    "not in": lambda a, b: a not in b,
    "ilike": lambda a, b: a is not None and str(b).lower() in str(a).lower(),
    "=ilike": lambda a, b: a is not None and str(a).lower() == str(b).lower(),
}


def _matches(row: dict[str, Any], domain: list[Any]) -> bool:
    for term in domain:
        if not isinstance(term, list | tuple) or len(term) != 3 or term[1] not in _OPS:
            raise OdooFault("odoo.exceptions.UserError", f"unsupported domain term {term!r}")
        name, op, value = term
        stored = row.get(name)
        if stored is False:
            stored = None
        if value is False:
            value = None
        if not _OPS[op](stored, value):
            return False
    return True


def _check_values(model: str, values: dict[str, Any], *, creating: bool) -> dict[str, Any]:
    schema = _schema(model)
    unknown = sorted(set(values) - set(schema))
    if unknown:
        raise OdooFault(
            "odoo.exceptions.ValidationError", f"Invalid field(s): {', '.join(unknown)}"
        )
    cleaned = {k: (None if v is False else v) for k, v in values.items()}
    if creating and not cleaned.get("name"):
        raise OdooFault(
            "odoo.exceptions.ValidationError", "Missing required value for the field 'name' (name)"
        )
    return cleaned


def _execute(
    store: _Store, model: str, method: str, args: list[Any], kwargs: dict[str, Any]
) -> Any:
    if method == "fields_get":
        if model not in _SCHEMAS:
            return {}
        wanted = kwargs.get("attributes")
        result = {"id": {"string": "ID", "type": "integer", "readonly": True}}
        result.update(_schema(model))
        return {
            name: {k: v for k, v in meta.items() if not wanted or k in wanted}
            for name, meta in result.items()
        }
    _schema(model)
    if method == "search_read":
        domain = args[0] if args else kwargs.get("domain", [])
        rows = [r for r in store.rows(model) if _matches(r, domain)]
        rows.sort(key=lambda r: r["id"])
        limit = kwargs.get("limit")
        offset = int(kwargs.get("offset") or 0)
        rows = rows[offset : offset + limit] if limit else rows[offset:]
        return [_present(r, kwargs.get("fields")) for r in rows]
    if method == "read":
        table = store.tables.get(model, {})
        return [_present(table[i], kwargs.get("fields")) for i in args[0] if i in table]
    if model != "res.partner":
        raise OdooFault("odoo.exceptions.AccessError", f"{model} is read-only in the fake")
    table = store.tables[model]
    if method == "create":
        values = _check_values(model, {**_DEFAULTS[model], **args[0]}, creating=True)
        new_id = store.next_id[model]
        store.next_id[model] += 1
        table[new_id] = {"id": new_id, **values}
        return new_id
    if method == "write":
        ids, raw = args[0], args[1]
        missing = [i for i in ids if i not in table]
        if missing:
            raise OdooFault("odoo.exceptions.MissingError", f"Record does not exist: {missing}")
        values = _check_values(model, raw, creating=False)
        for i in ids:
            table[i].update(values)
        return True
    raise OdooFault("odoo.exceptions.UserError", f"unsupported method {method!r}")


def create_fake_odoo_app(config: FakeOdooConfig | None = None) -> FastAPI:
    cfg = config or FakeOdooConfig()
    store = _Store()
    app = FastAPI(title="fake-odoo")

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"fake": "odoo"}

    @app.post("/jsonrpc")
    async def jsonrpc(request: Request) -> JSONResponse:
        body = await request.json()
        request_id = body.get("id")
        params = body.get("params", {})
        service, method, args = params.get("service"), params.get("method"), params.get("args", [])
        try:
            if service == "common" and method == "authenticate":
                db, login, key = args[0], args[1], args[2]
                ok = (db, login, key) == (cfg.db, cfg.login, cfg.api_key)
                result: Any = UID if ok else False
            elif service == "object" and method == "execute_kw":
                db, uid, key, model, meth, call_args, kwargs = args
                if (db, uid, key) != (cfg.db, UID, cfg.api_key):
                    raise OdooFault("odoo.exceptions.AccessDenied", "Access Denied")
                result = _execute(store, model, meth, call_args, kwargs or {})
            else:
                raise OdooFault("odoo.exceptions.UserError", f"unsupported {service}.{method}")
        except OdooFault as exc:
            error = {
                "code": 200,
                "message": "Odoo Server Error",
                "data": {"name": exc.name, "message": str(exc)},
            }
            return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": error})
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Fake Odoo JSON-RPC server for e2e tests")
    parser.add_argument("--port", type=int, default=8169)
    parser.add_argument("--host", default="127.0.0.1")
    defaults = FakeOdooConfig()
    parser.add_argument("--db", default=defaults.db)
    parser.add_argument("--login", default=defaults.login)
    parser.add_argument("--api-key", default=defaults.api_key)
    ns = parser.parse_args()
    app = create_fake_odoo_app(FakeOdooConfig(ns.db, ns.login, ns.api_key))
    uvicorn.run(app, host=ns.host, port=ns.port, log_level="warning")


if __name__ == "__main__":
    main()
