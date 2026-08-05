"""recordings y refactor tracks

Revision ID: c6fd0f01da70
Revises: 590d74c493ce
Create Date: 2026-08-05 16:32:14.674784

Separa el concepto de "grabacion" (Recording: titulo, duracion, creditos) de
"aparicion en una edicion" (Track: posicion, disco, cara). Las filas existentes
en `tracks` se migran creando una Recording por cada una y enlazandolas.

Tambien anade disc_number y side para agrupar pistas por disco/cara (CD1/CD2,
Cara A/B), y sustituye el UNIQUE antiguo (edition_id, position) por dos indices
parciales que manejan correctamente el caso side IS NULL.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c6fd0f01da70"
down_revision: Union[str, Sequence[str], None] = "590d74c493ce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Crear tabla recordings.
    op.create_table(
        "recordings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("credits", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # 2. Anadir nuevas columnas a tracks como nullable/con default primero,
    #    para que las filas existentes no rompan antes de la migracion de datos.
    op.add_column(
        "tracks",
        sa.Column("recording_id", sa.Integer(), nullable=True),  # nullable temporal
    )
    op.add_column(
        "tracks",
        sa.Column("disc_number", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("tracks", sa.Column("side", sa.String(length=10), nullable=True))

    # 3. Migrar datos: crear una Recording por cada Track existente y enlazarla.
    #    Se usa una tabla temporal para guardar la correspondencia track_id → rec_id.
    op.execute("""
        CREATE TEMP TABLE track_rec_map AS
        SELECT t.id AS track_id,
               nextval('recordings_id_seq') AS rec_id
        FROM tracks t
        ORDER BY t.id
    """)
    op.execute("""
        INSERT INTO recordings (id, title, duration_seconds)
        SELECT m.rec_id, t.title, t.duration_seconds
        FROM track_rec_map m
        JOIN tracks t ON t.id = m.track_id
    """)
    op.execute("""
        UPDATE tracks
        SET recording_id = m.rec_id
        FROM track_rec_map m
        WHERE tracks.id = m.track_id
    """)

    # 4. Ahora recording_id tiene valor en todas las filas → hacer NOT NULL.
    op.alter_column("tracks", "recording_id", nullable=False)

    # 5. Eliminar el server_default de disc_number (el service lo pone ya).
    op.alter_column("tracks", "disc_number", server_default=None)

    # 6. Sustituir el UNIQUE antiguo por los dos indices parciales.
    op.drop_constraint("uq_tracks_edition_position", "tracks", type_="unique")
    op.create_index(
        "uq_tracks_edition_disc_null_side_pos",
        "tracks",
        ["edition_id", "disc_number", "position"],
        unique=True,
        postgresql_where=sa.text("side IS NULL"),
        sqlite_where=sa.text("side IS NULL"),
    )
    op.create_index(
        "uq_tracks_edition_disc_side_pos",
        "tracks",
        ["edition_id", "disc_number", "side", "position"],
        unique=True,
        postgresql_where=sa.text("side IS NOT NULL"),
        sqlite_where=sa.text("side IS NOT NULL"),
    )

    # 7. FK e indice de recording_id.
    op.create_index(op.f("ix_tracks_recording_id"), "tracks", ["recording_id"], unique=False)
    op.create_foreign_key(None, "tracks", "recordings", ["recording_id"], ["id"], ondelete="RESTRICT")

    # 8. Borrar las columnas antiguas de tracks (ya en recordings).
    op.drop_column("tracks", "title")
    op.drop_column("tracks", "duration_seconds")


def downgrade() -> None:
    op.add_column("tracks", sa.Column("duration_seconds", sa.INTEGER(), nullable=True))
    op.add_column("tracks", sa.Column("title", sa.VARCHAR(length=200), nullable=True))

    # Recuperar title/duration desde la recording enlazada.
    op.execute("""
        UPDATE tracks
        SET title = r.title,
            duration_seconds = r.duration_seconds
        FROM recordings r
        WHERE tracks.recording_id = r.id
    """)
    op.alter_column("tracks", "title", nullable=False)

    op.drop_constraint(None, "tracks", type_="foreignkey")
    op.drop_index("uq_tracks_edition_disc_side_pos", table_name="tracks",
                  postgresql_where=sa.text("side IS NOT NULL"), sqlite_where=sa.text("side IS NOT NULL"))
    op.drop_index("uq_tracks_edition_disc_null_side_pos", table_name="tracks",
                  postgresql_where=sa.text("side IS NULL"), sqlite_where=sa.text("side IS NULL"))
    op.drop_index(op.f("ix_tracks_recording_id"), table_name="tracks")
    op.create_unique_constraint("uq_tracks_edition_position", "tracks", ["edition_id", "position"])
    op.drop_column("tracks", "side")
    op.drop_column("tracks", "disc_number")
    op.drop_column("tracks", "recording_id")
    op.drop_table("recordings")
