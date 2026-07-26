"""Tests del contrato OpenAPI pensados para el cliente generado (app iOS).

swift-openapi-generator no soporta el tipo nulo de JSON Schema (`{"type":
"null"}`) dentro de un `anyOf`: descarta el campo. Estos tests fijan el estado
objetivo del esquema para que eso no vuelva a pasar (ni con `full_name` ni con
ningun opcional futuro). Ver app/core/openapi.py.
"""

from typing import Any

from app.main import app


def _iter_nodes(node: Any):
    """Recorre en profundidad todos los dicts del esquema."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_nodes(item)


def test_openapi_has_no_null_type_anywhere():
    """En ninguna parte del esquema debe aparecer el tipo nulo."""
    schema = app.openapi()
    for node in _iter_nodes(schema):
        for key in ("anyOf", "oneOf"):
            variants = node.get(key)
            if isinstance(variants, list):
                assert all(
                    v.get("type") != "null"
                    for v in variants
                    if isinstance(v, dict)
                ), f"Quedo un tipo nulo en un {key}: {node}"
        type_ = node.get("type")
        if isinstance(type_, list):
            assert "null" not in type_, f"Quedo 'null' en un type-lista: {node}"


def test_optional_fields_are_optional_not_required():
    """Un campo `T | None` queda como opcional (tipo simple, fuera de required)."""
    schemas = app.openapi()["components"]["schemas"]
    for model in ("UserRead", "UserCreate"):
        full_name = schemas[model]["properties"]["full_name"]
        # Tipo simple, sin union: el generador lo vera como propiedad normal...
        assert full_name.get("type") == "string"
        assert "anyOf" not in full_name
        # ...y opcional (fuera de required) -> Swift `String?`.
        assert "full_name" not in schemas[model].get("required", [])
