"""extrae label de editions a tabla labels

Revision ID: 5677cd83477c
Revises: f6d9ebe87c0b
Create Date: 2026-08-06 10:59:10.403527

`Edition.label` era texto libre. Pasa a ser una FK a la nueva tabla `labels`,
para poder gestionar los sellos desde la app (crear, renombrar) y para que dos
ediciones del mismo sello apunten de verdad a la misma fila.

Migracion de datos: se crea un Label por cada valor DISTINTO de `editions.label`
(agrupando sin distinguir mayusculas, para no duplicar "Virgin" y "virgin"), y
se enlaza cada edicion con el suyo. Los NULL se quedan como NULL.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5677cd83477c"
down_revision: Union[str, Sequence[str], None] = "f6d9ebe87c0b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Tabla labels.
    op.create_table(
        "labels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Unicidad insensible a mayusculas: evita "Virgin" y "virgin" como sellos
    # distintos. Indice funcional, no un UNIQUE normal sobre la columna.
    op.create_index(
        "uq_labels_name_lower", "labels", [sa.text("lower(name)")], unique=True
    )

    # 2. Nueva columna FK en editions (nullable: el sello no siempre se conoce).
    op.add_column("editions", sa.Column("label_id", sa.Integer(), nullable=True))

    # 3. Migrar datos: un Label por cada nombre distinto (ignorando mayusculas).
    #    MIN(label) elige una grafia concreta cuando hay varias variantes.
    op.execute(
        """
        INSERT INTO labels (name)
        SELECT MIN(label)
        FROM editions
        WHERE label IS NOT NULL AND btrim(label) <> ''
        GROUP BY lower(btrim(label))
        """
    )
    op.execute(
        """
        UPDATE editions e
        SET label_id = l.id
        FROM labels l
        WHERE e.label IS NOT NULL
          AND lower(btrim(e.label)) = lower(btrim(l.name))
        """
    )

    # 4. FK e indice, y fuera la columna de texto.
    op.create_index("ix_editions_label_id", "editions", ["label_id"])
    op.create_foreign_key(
        "editions_label_id_fkey",
        "editions",
        "labels",
        ["label_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_column("editions", "label")


def downgrade() -> None:
    op.add_column("editions", sa.Column("label", sa.String(length=150), nullable=True))
    op.execute(
        """
        UPDATE editions e
        SET label = l.name
        FROM labels l
        WHERE e.label_id = l.id
        """
    )
    op.drop_constraint("editions_label_id_fkey", "editions", type_="foreignkey")
    op.drop_index("ix_editions_label_id", table_name="editions")
    op.drop_column("editions", "label_id")
    op.drop_index("uq_labels_name_lower", table_name="labels")
    op.drop_table("labels")
