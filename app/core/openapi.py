"""Ajustes del esquema OpenAPI para los clientes generados (app iOS).

Pydantic v2 serializa un campo `T | None` (opcional / anulable) como una union
con el tipo nulo de JSON Schema 2020-12:

    "full_name": {"anyOf": [{"type": "string"}, {"type": "null"}]}

Es OpenAPI 3.1 valido, pero **swift-openapi-generator (1.13) no soporta el
`{"type": "null"}`** dentro de un `anyOf`: emite un warning y DESCARTA el campo
entero. Resultado: la propiedad ni siquiera existe en el cliente Swift, y la app
es ciega a ese dato.

Aqui reescribimos el esquema para que "anulable" se exprese como "opcional" en el
sentido que el generador entiende:

  - Se elimina la rama `{"type": "null"}` de los `anyOf` / `oneOf` (y el valor
    "null" de un `type` en forma de lista). Si solo queda un miembro, se "aplana"
    (se funde en el nodo) para dejar un tipo simple.
  - El campo se saca de `required`. Asi el generador produce una propiedad Swift
    OPCIONAL (`String?`), cuyo `decodeIfPresent` decodifica bien los tres casos:
    string, `null` y ausente.

Esto NO cambia las respuestas en runtime (la API sigue enviando lo mismo); solo
cambia como se DESCRIBE el contrato. Se aplica a TODO el esquema, asi que
cualquier opcional futuro (discografia, conciertos, libros...) queda cubierto sin
tener que acordarse de nada.

Trade-off asumido: un campo que en la BD puede ser NULL se anuncia al cliente
como "opcional" en vez de "anulable". Para un cliente que mapea ambos a `String?`
es lo mismo, y es el patron habitual para consumir esta API desde Swift.
"""

from typing import Any

from fastapi import FastAPI


def _is_null_branch(node: Any) -> bool:
    """True si el nodo es exactamente el esquema del tipo nulo (`{"type":"null"}`)."""
    return isinstance(node, dict) and node.get("type") == "null"


def _is_nullable(node: dict[str, Any]) -> bool:
    """True si el nodo declara que admite `null` (via union o `type` en lista)."""
    for key in ("anyOf", "oneOf"):
        variants = node.get(key)
        if isinstance(variants, list) and any(_is_null_branch(v) for v in variants):
            return True
    type_ = node.get("type")
    return isinstance(type_, list) and "null" in type_


def _drop_null(node: dict[str, Any]) -> None:
    """Quita la anulabilidad de un nodo, in place.

    - anyOf/oneOf: elimina la rama nula; si queda un unico miembro, lo funde en el
      nodo (tipo simple) SIN pisar las claves ya presentes (p. ej. `title`).
    - type en lista: quita "null" de la lista.
    """
    for key in ("anyOf", "oneOf"):
        variants = node.get(key)
        if not isinstance(variants, list):
            continue
        non_null = [v for v in variants if not _is_null_branch(v)]
        if len(non_null) == len(variants):
            continue  # esta union no tenia rama nula
        if len(non_null) == 1 and isinstance(non_null[0], dict):
            node.pop(key)
            for k, v in non_null[0].items():
                node.setdefault(k, v)
        else:
            node[key] = non_null

    type_ = node.get("type")
    if isinstance(type_, list) and "null" in type_:
        rest = [t for t in type_ if t != "null"]
        node["type"] = rest[0] if len(rest) == 1 else rest


def _simplify(node: Any) -> None:
    """Recorre el esquema entero aplicando la regla anulable -> opcional."""
    if isinstance(node, dict):
        # A nivel de objeto: los campos anulables salen de `required`.
        properties = node.get("properties")
        required = node.get("required")
        if isinstance(properties, dict) and isinstance(required, list):
            for name, prop in properties.items():
                if isinstance(prop, dict) and _is_nullable(prop) and name in required:
                    required.remove(name)
            if not required:
                node.pop("required", None)

        # Este nodo puede ser el propio campo anulable: quitarle el `null`.
        _drop_null(node)

        for value in node.values():
            _simplify(value)
    elif isinstance(node, list):
        for item in node:
            _simplify(item)


def use_ios_friendly_openapi(app: FastAPI) -> None:
    """Envuelve `app.openapi` para post-procesar el esquema generado.

    Reutiliza el generador real de FastAPI (asi se conservan servers, contact,
    seguridad, etc.) y solo reescribe la parte de la anulabilidad. El resultado se
    cachea en `app.openapi_schema`, asi que el post-proceso corre una sola vez.
    """
    generate = app.openapi  # metodo original (genera y cachea)

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = generate()  # genera y setea app.openapi_schema
        _simplify(schema)
        return schema

    app.openapi = custom_openapi
