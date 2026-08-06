"""anade CHECK real a los enums-texto

Revision ID: f6d9ebe87c0b
Revises: c6fd0f01da70
Create Date: 2026-08-06 10:43:15.322692

Los cuatro campos "enum como texto" (release_type, format, image_type,
theme_preference) se documentaban como "validados por Python + CHECK", pero el
CHECK nunca llego a existir: `Enum(native_enum=False)` de SQLAlchemy trae
`create_constraint=False` por defecto desde la version 1.4.

Sin el CHECK la validacion era SOLO de Python: un UPDATE a mano en psql podia
escribir cualquier cadena en esas columnas. Esta migracion emite las
restricciones de verdad.

Se comprobo antes de escribirla que los datos de dev y de pre cumplen los
cuatro conjuntos de valores, asi que ningun ALTER TABLE deberia fallar.

NOTA para el futuro: al anadir un valor nuevo a uno de estos enums ahora SI
hace falta migracion (DROP + CREATE del CHECK con la lista nueva), a diferencia
de antes, cuando bastaba con tocar el enum de Python y la migracion salia vacia.
Es el precio de que la base de datos proteja de verdad.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6d9ebe87c0b"
down_revision: Union[str, Sequence[str], None] = "c6fd0f01da70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (nombre del constraint, tabla, columna, valores permitidos, columna nullable)
_CHECKS = [
    (
        "ck_releases_release_type",
        "releases",
        "release_type",
        ["studio", "compilation", "single", "bootleg", "live"],
        False,
    ),
    (
        "ck_editions_format",
        "editions",
        "format",
        ["vinyl", "cd", "single", "maxi_single", "cd_single", "cassette"],
        True,
    ),
    (
        "ck_images_image_type",
        "images",
        "image_type",
        ["front_cover", "back_cover", "other"],
        False,
    ),
    (
        "ck_users_theme_preference",
        "users",
        "theme_preference",
        ["light", "dark", "system"],
        False,
    ),
]


def upgrade() -> None:
    for name, table, column, values, nullable in _CHECKS:
        allowed = ", ".join(f"'{v}'" for v in values)
        condition = f"{column} IN ({allowed})"
        # En una columna nullable, `col IN (...)` da NULL (no TRUE) para las
        # filas sin valor. Un CHECK solo rechaza cuando la condicion es FALSE,
        # asi que tecnicamente NULL pasaria igual; se anade el OR explicito
        # para que la intencion quede escrita y no dependa de ese matiz.
        if nullable:
            condition = f"{condition} OR {column} IS NULL"
        op.create_check_constraint(name, table, condition)


def downgrade() -> None:
    for name, table, _column, _values, _nullable in _CHECKS:
        op.drop_constraint(name, table, type_="check")
