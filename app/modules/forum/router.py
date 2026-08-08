"""Router del modulo de foro: define los endpoints HTTP.

Prefijo: se monta bajo `/api/v1` en `main.py`, y este router anade `/forum`,
asi que las rutas finales son `/api/v1/forum/threads...`.

Leer (listar subforos/hilos, ver detalle) es PUBLICO. Participar (crear un
hilo, comentar) exige estar autenticado Y tener el email verificado
(`require_verified_email`, en auth/dependencies.py) — no basta con tener una
cuenta activa. Cambiar el `status` de un hilo exige ser ADMINISTRADOR; esta
fase no aplica ningun cambio automaticamente en el catalogo, solo organiza la
conversacion.

Todo hilo vive dentro de un `Subforum` (`subforum_id`, obligatorio en
`ThreadCreate`); hoy solo existe uno ("Discusiones"), sembrado por migracion.
No hay CRUD de subforos desde la API todavia -- se anadira cuando haga falta
un segundo.
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.exceptions import ErrorMessage
from app.modules.auth.dependencies import require_admin, require_verified_email
from app.modules.auth.models import User
from app.modules.forum import service
from app.modules.forum.models import ForumEntityType, ThreadStatus
from app.modules.forum.schemas import (
    CommentCreate,
    CommentRead,
    SubforumRead,
    ThreadCreate,
    ThreadDetailRead,
    ThreadListRead,
    ThreadStatusUpdate,
)

router = APIRouter(prefix="/forum", tags=["forum"])

_NOT_FOUND = {"model": ErrorMessage, "description": "El hilo no existe"}
_NO_AUTH = {
    "model": ErrorMessage,
    "description": "Falta el access token o no es valido",
}
_EMAIL_NOT_VERIFIED = {
    "model": ErrorMessage,
    "description": (
        "El usuario esta autenticado pero no tiene el email verificado. "
        '`detail` es el codigo "email_not_verified" (no una frase), para que '
        'la app pueda mostrar "verifica tu email para participar" en vez de '
        "un 403 opaco."
    ),
}
_FORBIDDEN = {
    "model": ErrorMessage,
    "description": "El usuario esta autenticado pero no es administrador",
}
_INVALID_ENTITY = {
    "model": ErrorMessage,
    "description": "entity_id no corresponde a ninguna obra/edicion existente",
}
_SUBFORUM_NOT_FOUND = {
    "model": ErrorMessage,
    "description": "subforum_id no corresponde a ningun subforo existente",
}


@router.get(
    "/subforums",
    response_model=list[SubforumRead],
    summary="Listar subforos",
)
async def list_subforums(session: AsyncSession = Depends(get_session)) -> list[SubforumRead]:
    """Lista los subforos (secciones del foro), ordenados por `position`. Hoy
    solo existe "Discusiones"; no hay CRUD de subforos desde la API todavia."""
    return await service.list_subforums(session)


@router.get(
    "/threads",
    response_model=list[ThreadListRead],
    summary="Listar hilos del foro",
)
async def list_threads(
    subforum_id: int | None = Query(default=None, description="Filtra por subforo"),
    entity_type: ForumEntityType | None = Query(
        default=None, description="Filtra por a que se refiere el hilo"
    ),
    entity_id: int | None = Query(
        default=None, description="Filtra por el disco/edicion concreto (junto a entity_type)"
    ),
    thread_status: ThreadStatus | None = Query(
        default=None, alias="status", description="Filtra por estado del hilo"
    ),
    session: AsyncSession = Depends(get_session),
) -> list[ThreadListRead]:
    """Lista hilos, mas recientes primero, con el numero de comentarios de
    cada uno. `?subforum_id=1` para los hilos de un subforo;
    `?entity_type=release&entity_id=3` para los hilos de un disco concreto;
    `?status=open` para la cola de abiertos."""
    return await service.list_threads(
        session, subforum_id, entity_type, entity_id, thread_status
    )


@router.get(
    "/threads/{thread_id}",
    response_model=ThreadDetailRead,
    summary="Detalle de un hilo (con sus comentarios)",
    responses={status.HTTP_404_NOT_FOUND: _NOT_FOUND},
)
async def get_thread(
    thread_id: int, session: AsyncSession = Depends(get_session)
) -> ThreadDetailRead:
    """Devuelve un hilo con todos sus comentarios, o 404 si no existe."""
    return await service.get_thread(session, thread_id)


@router.post(
    "/threads",
    response_model=ThreadDetailRead,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un hilo (requiere email verificado)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_403_FORBIDDEN: _EMAIL_NOT_VERIFIED,
        status.HTTP_404_NOT_FOUND: _SUBFORUM_NOT_FOUND,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _INVALID_ENTITY,
    },
)
async def create_thread(
    data: ThreadCreate,
    current_user: User = Depends(require_verified_email),
    session: AsyncSession = Depends(get_session),
) -> ThreadDetailRead:
    """Crea un hilo dentro de `subforum_id` (obligatorio). `entity_type`/
    `entity_id` opcionales: a que obra o edicion se refiere (o ninguno, tema
    general sobre discografia)."""
    return await service.create_thread(session, current_user.id, data)


@router.post(
    "/threads/{thread_id}/comments",
    response_model=CommentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Comentar en un hilo (requiere email verificado)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_403_FORBIDDEN: _EMAIL_NOT_VERIFIED,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND,
    },
)
async def add_comment(
    thread_id: int,
    data: CommentCreate,
    current_user: User = Depends(require_verified_email),
    session: AsyncSession = Depends(get_session),
) -> CommentRead:
    """Anade un comentario al hilo."""
    return await service.add_comment(session, thread_id, current_user.id, data)


@router.patch(
    "/threads/{thread_id}",
    response_model=ThreadDetailRead,
    summary="Cambiar el estado de un hilo (requiere administrador)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND,
    },
)
async def update_thread_status(
    thread_id: int,
    data: ThreadStatusUpdate,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> ThreadDetailRead:
    """Cambia el `status` del hilo (`open`/`resolved`/`closed`) y,
    opcionalmente, `resolution_note`. Solo cambia el ESTADO del hilo: aplicar
    el cambio propuesto en el catalogo sigue siendo manual, con las
    herramientas de edicion existentes."""
    return await service.update_thread_status(session, thread_id, data)
