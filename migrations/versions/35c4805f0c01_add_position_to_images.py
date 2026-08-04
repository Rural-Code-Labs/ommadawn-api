"""add position to images

Revision ID: 35c4805f0c01
Revises: cec3117a2e5d
Create Date: 2026-08-04 18:58:08.645328

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "35c4805f0c01"
down_revision: Union[str, Sequence[str], None] = "cec3117a2e5d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Aniade la columna 'position' a 'images' y la rellena con ROW_NUMBER.

    La columna es NOT NULL, asi que el flujo es:
    1. Anadirla con server_default=1 para que las filas existentes no rompan.
    2. Actualizar cada fila con ROW_NUMBER() OVER (PARTITION BY edition_id ORDER BY id),
       de modo que las imagenes ya subidas queden numeradas consecutivamente dentro
       de su edicion (en el orden en que se subieron, por id).
    3. Eliminar el server_default: a partir de aqui el valor lo pone el servicio
       (max+1 al subir una imagen nueva).
    """
    op.add_column(
        "images",
        sa.Column("position", sa.Integer(), nullable=False, server_default="1"),
    )

    # Poblar con ROW_NUMBER particionado por edicion (orden: id de insercion).
    op.execute(
        """
        UPDATE images
        SET position = subq.rn
        FROM (
            SELECT id,
                   ROW_NUMBER() OVER (PARTITION BY edition_id ORDER BY id) AS rn
            FROM images
        ) AS subq
        WHERE images.id = subq.id
        """
    )

    # Quitar el server_default: el service gestiona el valor a partir de ahora.
    op.alter_column("images", "position", server_default=None)


def downgrade() -> None:
    """Elimina la columna 'position' de 'images'."""
    op.drop_column("images", "position")
