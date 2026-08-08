"""subforos: Subforum + subforum_id en ForumThread

Revision ID: a068d351cf44
Revises: b8d9caca4cde
Create Date: 2026-08-08 18:26:26.783236

Introduce el concepto de subforo (seccion del foro): "Discusiones" hoy,
pensado para futuros "Anuncios"/"Ayuda" sin volver a tocar el esquema. Todo
`ForumThread` pasa a vivir dentro de un `Subforum` (`subforum_id`,
obligatorio).

Como `forum_threads` puede ya tener filas (creadas antes de que existiera el
concepto de subforo), el orden importa, igual que en la extraccion de `Label`
en discografia (migracion 5677cd83477c):
  1. Crear `subforums` y sembrar la fila "Discusiones".
  2. Anadir `subforum_id` NULLABLE (todavia no se puede exigir NOT NULL con
     filas existentes sin valor).
  3. Backfill: todo hilo existente pasa a "Discusiones" (el unico subforo).
  4. Ahora si, `subforum_id` a NOT NULL + FK + indice.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a068d351cf44'
down_revision: Union[str, Sequence[str], None] = 'b8d9caca4cde'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Tabla subforums + seed.
    op.create_table(
        'subforums',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('icon', sa.String(length=100), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.execute(
        """
        INSERT INTO subforums (name, icon, position)
        VALUES ('Discusiones', 'bubble.left.and.bubble.right', 0)
        """
    )

    # 2. Columna nueva, todavia nullable (puede haber filas existentes).
    op.add_column('forum_threads', sa.Column('subforum_id', sa.Integer(), nullable=True))

    # 3. Backfill: todo hilo ya existente va al unico subforo que hay.
    op.execute(
        """
        UPDATE forum_threads
        SET subforum_id = (SELECT id FROM subforums WHERE name = 'Discusiones')
        WHERE subforum_id IS NULL
        """
    )

    # 4. Ya se puede exigir NOT NULL + FK + indice.
    op.alter_column('forum_threads', 'subforum_id', nullable=False)
    op.create_index(
        op.f('ix_forum_threads_subforum_id'), 'forum_threads', ['subforum_id']
    )
    op.create_foreign_key(
        'forum_threads_subforum_id_fkey',
        'forum_threads',
        'subforums',
        ['subforum_id'],
        ['id'],
        ondelete='RESTRICT',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('forum_threads_subforum_id_fkey', 'forum_threads', type_='foreignkey')
    op.drop_index(op.f('ix_forum_threads_subforum_id'), table_name='forum_threads')
    op.drop_column('forum_threads', 'subforum_id')
    op.drop_table('subforums')
