"""Schemas (contratos) del modulo de foro.

Igual que en auth/discografia: los models ORM nunca se exponen tal cual.
`author_id`/`author_username` en las vistas de salida vienen de
`auth.service.get_users_by_ids` (el foro no tiene relacion ORM hacia `User`,
ver el docstring de `forum/models.py`), no de una relacion cargada aqui.
"""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.modules.forum.models import ForumEntityType, ThreadStatus

# --- Entrada (request) ---------------------------------------------------------


class ThreadCreate(BaseModel):
    """Datos para crear un hilo (body de POST /forum/threads).

    `subforum_id` es OBLIGATORIO: todo hilo vive dentro de un subforo (ver
    GET /forum/subforums para listarlos; hoy solo existe "Discusiones").

    `entity_type`/`entity_id` son EXCLUYENTES segun el tipo, y siguen siendo
    opcionales (independientes de `subforum_id`: un hilo tiene subforo -donde
    vive- y, opcionalmente, a que entidad del catalogo se refiere DENTRO de
    ese subforo): "release" y "edition" exigen `entity_id`; "discography"
    (tema general) y la ausencia de `entity_type` (tema sin tema, ver
    ForumThread.entity_type) NO admiten `entity_id`.
    """

    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    subforum_id: int
    entity_type: ForumEntityType | None = None
    entity_id: int | None = None

    @model_validator(mode="after")
    def _check_entity(self) -> "ThreadCreate":
        needs_id = self.entity_type in (ForumEntityType.RELEASE, ForumEntityType.EDITION)
        if needs_id and self.entity_id is None:
            raise ValueError(
                f"entity_id es obligatorio cuando entity_type es {self.entity_type.value!r}"
            )
        if not needs_id and self.entity_id is not None:
            raise ValueError(
                "entity_id solo se admite cuando entity_type es 'release' o 'edition'"
            )
        return self


class CommentCreate(BaseModel):
    """Datos para anadir un comentario (body de POST /forum/threads/{id}/comments)."""

    body: str = Field(min_length=1)


class ThreadStatusUpdate(BaseModel):
    """Body de PATCH /forum/threads/{id} (solo administrador).

    `status` es OBLIGATORIO (es el proposito del endpoint: cambiar el estado
    del hilo). `resolution_note` sigue el patron PATCH normal si se envia (se
    aplica tal cual, incluido un `null` explicito para borrarla) y se ignora
    si se omite -- el service distingue "omitido" de "enviado como null" con
    `model_dump(exclude_unset=True)`, igual que ReleaseUpdate/LabelUpdate.
    """

    status: ThreadStatus
    resolution_note: str | None = None


# --- Salida (response) ---------------------------------------------------------


class SubforumRead(BaseModel):
    """Vista publica de un subforo (GET /forum/subforums)."""

    id: int
    name: str
    description: str | None
    icon: str | None
    position: int

    model_config = {"from_attributes": True}


class CommentRead(BaseModel):
    """Vista publica de un comentario, con el username de su autor."""

    id: int
    thread_id: int
    author_id: int
    author_username: str
    body: str
    created_at: datetime


class ThreadListRead(BaseModel):
    """Vista de un hilo en el listado (GET /forum/threads): sin el cuerpo
    completo ni los comentarios, con `comment_count` para la cola de la app."""

    id: int
    title: str
    author_id: int
    author_username: str
    subforum_id: int
    subforum_name: str
    entity_type: ForumEntityType | None
    entity_id: int | None
    status: ThreadStatus
    comment_count: int
    created_at: datetime
    updated_at: datetime


class ThreadDetailRead(BaseModel):
    """Vista publica de un hilo con detalle y sus comentarios (GET
    /forum/threads/{id}, y respuesta de crear/cambiar estado)."""

    id: int
    title: str
    body: str
    author_id: int
    author_username: str
    subforum_id: int
    subforum_name: str
    entity_type: ForumEntityType | None
    entity_id: int | None
    status: ThreadStatus
    resolution_note: str | None
    created_at: datetime
    updated_at: datetime
    comments: list[CommentRead]
