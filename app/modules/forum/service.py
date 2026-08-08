"""Logica de negocio del modulo de foro.

Igual que en auth/discografia: el `service` es quien toca la base de datos y
quien lanza los errores de negocio. Datos de OTROS modulos (username del
autor, existencia de un Release/Edition referenciado) se piden SIEMPRE a
traves de la capa de `service` del modulo dueno
(`auth.service.get_users_by_ids`, `discography.service.release_exists`/
`edition_exists`), nunca importando sus modelos aqui.
"""

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.auth import service as auth_service
from app.modules.discography import service as discography_service
from app.modules.forum.models import ForumComment, ForumEntityType, ForumThread, ThreadStatus
from app.modules.forum.schemas import (
    CommentCreate,
    CommentRead,
    ThreadCreate,
    ThreadDetailRead,
    ThreadListRead,
    ThreadStatusUpdate,
)

thread_not_found_exception = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Hilo no encontrado",
)


async def _validate_entity_reference(
    session: AsyncSession, entity_type: ForumEntityType | None, entity_id: int | None
) -> None:
    """Comprueba que el disco/edicion referenciado exista de verdad.

    Solo hace falta comprobar cuando `entity_type` es "release"/"edition": el
    schema (`ThreadCreate`) ya garantiza que en cualquier otro caso
    `entity_id` es `None`. 422, mismo criterio que `_build_tracks` en
    discografia al validar un `recording_id` que no existe.
    """
    if entity_type == ForumEntityType.RELEASE:
        if not await discography_service.release_exists(session, entity_id):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"entity_id {entity_id} no corresponde a ninguna obra",
            )
    elif entity_type == ForumEntityType.EDITION:
        if not await discography_service.edition_exists(session, entity_id):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"entity_id {entity_id} no corresponde a ninguna edicion",
            )


def _build_comment_read(comment: ForumComment, username: str) -> CommentRead:
    return CommentRead(
        id=comment.id,
        thread_id=comment.thread_id,
        author_id=comment.author_id,
        author_username=username,
        body=comment.body,
        created_at=comment.created_at,
    )


async def _build_thread_detail_read(
    session: AsyncSession, thread: ForumThread
) -> ThreadDetailRead:
    author_ids = {thread.author_id} | {c.author_id for c in thread.comments}
    users = await auth_service.get_users_by_ids(session, author_ids)
    return ThreadDetailRead(
        id=thread.id,
        title=thread.title,
        body=thread.body,
        author_id=thread.author_id,
        author_username=users[thread.author_id].username,
        entity_type=thread.entity_type,
        entity_id=thread.entity_id,
        status=thread.status,
        resolution_note=thread.resolution_note,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        comments=[
            _build_comment_read(c, users[c.author_id].username) for c in thread.comments
        ],
    )


async def create_thread(
    session: AsyncSession, author_id: int, data: ThreadCreate
) -> ThreadDetailRead:
    """Crea un hilo. Lanza 422 si `entity_id` no corresponde a ninguna obra/
    edicion real (ver `_validate_entity_reference`)."""
    await _validate_entity_reference(session, data.entity_type, data.entity_id)

    thread = ForumThread(
        title=data.title,
        body=data.body,
        author_id=author_id,
        entity_type=data.entity_type,
        entity_id=data.entity_id,
    )
    session.add(thread)
    await session.commit()
    # Fresh SELECT (via get_thread) en vez de un refresh parcial: mismo
    # criterio que update_collection en discografia. `thread.status`/etc.
    # tienen `onupdate=func.now()` a nivel de servidor -- tras el commit ese
    # valor queda "expirado" y un refresh que no lo incluya explicitamente
    # dispara un lazy-load sincrono no soportado en async (MissingGreenlet).
    return await get_thread(session, thread.id)


async def get_thread(session: AsyncSession, thread_id: int) -> ThreadDetailRead:
    """Detalle de un hilo con sus comentarios. Lanza 404 si no existe."""
    result = await session.execute(
        select(ForumThread)
        .options(selectinload(ForumThread.comments))
        .where(ForumThread.id == thread_id)
    )
    thread = result.scalar_one_or_none()
    if thread is None:
        raise thread_not_found_exception
    return await _build_thread_detail_read(session, thread)


async def list_threads(
    session: AsyncSession,
    entity_type: ForumEntityType | None = None,
    entity_id: int | None = None,
    thread_status: ThreadStatus | None = None,
) -> list[ThreadListRead]:
    """Lista hilos (mas recientes primero), con el numero de comentarios de
    cada uno. Filtrable por `entity_type`+`entity_id` (hilos de un disco/
    edicion concreto) y por `status` (p. ej. la cola de abiertos)."""
    count_col = func.count(ForumComment.id).label("comment_count")
    query = (
        select(ForumThread, count_col)
        .outerjoin(ForumComment, ForumComment.thread_id == ForumThread.id)
        .group_by(ForumThread.id)
        # Desempate por id: dos hilos creados casi a la vez pueden compartir
        # el mismo created_at (la resolucion de SQLite es menor que la de
        # Postgres), y sin un segundo criterio el orden dejaria de ser
        # deterministico. El id autoincremental es un proxy fiable de "mas
        # reciente" incluso cuando el timestamp empata.
        .order_by(ForumThread.created_at.desc(), ForumThread.id.desc())
    )
    if entity_type is not None:
        query = query.where(ForumThread.entity_type == entity_type)
    if entity_id is not None:
        query = query.where(ForumThread.entity_id == entity_id)
    if thread_status is not None:
        query = query.where(ForumThread.status == thread_status)

    rows = (await session.execute(query)).all()
    threads = [row[0] for row in rows]
    comment_counts = {row[0].id: row[1] for row in rows}

    author_ids = {t.author_id for t in threads}
    users = await auth_service.get_users_by_ids(session, author_ids)

    return [
        ThreadListRead(
            id=t.id,
            title=t.title,
            author_id=t.author_id,
            author_username=users[t.author_id].username,
            entity_type=t.entity_type,
            entity_id=t.entity_id,
            status=t.status,
            comment_count=comment_counts[t.id],
            created_at=t.created_at,
            updated_at=t.updated_at,
        )
        for t in threads
    ]


async def add_comment(
    session: AsyncSession, thread_id: int, author_id: int, data: CommentCreate
) -> CommentRead:
    """Anade un comentario a un hilo. Devuelve SOLO el comentario nuevo (no
    el hilo completo): mismo criterio que `upload_image` en discografia, para
    no reconstruir todo el hilo (con el username de cada autor) por un
    comentario mas."""
    thread = await session.get(ForumThread, thread_id)
    if thread is None:
        raise thread_not_found_exception

    comment = ForumComment(thread_id=thread_id, author_id=author_id, body=data.body)
    session.add(comment)
    await session.commit()
    await session.refresh(comment)

    users = await auth_service.get_users_by_ids(session, {author_id})
    return _build_comment_read(comment, users[author_id].username)


async def update_thread_status(
    session: AsyncSession, thread_id: int, data: ThreadStatusUpdate
) -> ThreadDetailRead:
    """Cambia el `status` de un hilo (y opcionalmente `resolution_note`).
    Solo aplica el cambio de ESTADO: aplicar el cambio propuesto en el
    catalogo sigue siendo manual, con las herramientas de edicion existentes
    (ver el router para el permiso de administrador)."""
    thread = await session.get(ForumThread, thread_id)
    if thread is None:
        raise thread_not_found_exception

    thread.status = data.status
    updates = data.model_dump(exclude_unset=True, exclude={"status"})
    for field, value in updates.items():
        setattr(thread, field, value)

    await session.commit()
    # Fresh SELECT en vez de refresh parcial -- mismo motivo que create_thread.
    return await get_thread(session, thread_id)
