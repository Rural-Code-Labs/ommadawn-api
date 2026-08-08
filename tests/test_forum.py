"""Tests de integracion del modulo de foro.

Participar (crear hilos, comentar) exige email verificado, no solo estar
autenticado. Como no hay (a proposito) forma de verificar el email sin pasar
por el flujo completo de codigo, los tests marcan `email_verified=True`
directamente en BD (via `db_session`), igual que se marca `is_admin=True`
en los tests de discografia.
"""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User

BASE = "/api/v1/forum"
AUTH_BASE = "/api/v1/auth"
DISCOGRAPHY_BASE = "/api/v1/discography"

VERIFIED_CREDS = {
    "username": "verified",
    "email": "verified@ommadawn.com",
    "password": "verifiedpass1",
}

UNVERIFIED_CREDS = {
    "username": "unverified",
    "email": "unverified@ommadawn.com",
    "password": "unverifiedpass1",
}

ADMIN_CREDS = {
    "username": "admin",
    "email": "admin@ommadawn.com",
    "password": "adminpass123",
}


async def _login(client: AsyncClient, username: str, password: str) -> dict:
    resp = await client.post(
        f"{AUTH_BASE}/login",
        json={"username_or_email": username, "password": password},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _verified_headers(
    client: AsyncClient, db_session: AsyncSession, creds: dict = VERIFIED_CREDS
) -> dict:
    """Registra un usuario, lo marca con el email verificado en BD y
    devuelve su cabecera."""
    await client.post(f"{AUTH_BASE}/register", json=creds)

    user = (
        await db_session.execute(select(User).where(User.username == creds["username"]))
    ).scalar_one()
    user.email_verified = True
    await db_session.commit()

    return await _login(client, creds["username"], creds["password"])


async def _admin_headers(client: AsyncClient, db_session: AsyncSession) -> dict:
    """Registra un usuario, lo promueve a admin en BD y devuelve su cabecera.

    Deliberadamente NO marca `email_verified`: cambiar el status de un hilo
    exige solo ser admin (ver backlog), no tambien tener el email verificado.
    """
    await client.post(f"{AUTH_BASE}/register", json=ADMIN_CREDS)

    user = (
        await db_session.execute(select(User).where(User.username == ADMIN_CREDS["username"]))
    ).scalar_one()
    user.is_admin = True
    await db_session.commit()

    return await _login(client, ADMIN_CREDS["username"], ADMIN_CREDS["password"])


async def _create_release(client: AsyncClient, admin_headers: dict) -> int:
    """Helper: crea una obra minima (para probar entity_type='release'), usando
    unas cabeceras de administrador (crear discografia exige ser admin)."""
    resp = await client.post(
        f"{DISCOGRAPHY_BASE}/releases",
        json={"title": "Tubular Bells", "release_type": "studio"},
        headers=admin_headers,
    )
    return resp.json()["id"]


async def _create_edition(client: AsyncClient, admin_headers: dict, release_id: int) -> int:
    resp = await client.post(
        f"{DISCOGRAPHY_BASE}/releases/{release_id}/editions",
        json={},
        headers=admin_headers,
    )
    return resp.json()["id"]


# --- Crear hilos -----------------------------------------------------------------


async def test_create_thread_requires_authentication(client: AsyncClient):
    resp = await client.post(
        f"{BASE}/threads", json={"title": "x", "body": "y"}
    )
    assert resp.status_code == 401


async def test_create_thread_requires_verified_email(
    client: AsyncClient, db_session: AsyncSession
):
    await client.post(f"{AUTH_BASE}/register", json=UNVERIFIED_CREDS)
    headers = await _login(client, UNVERIFIED_CREDS["username"], UNVERIFIED_CREDS["password"])

    resp = await client.post(
        f"{BASE}/threads", json={"title": "x", "body": "y"}, headers=headers
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "email_not_verified"


async def test_verified_user_can_create_general_thread(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _verified_headers(client, db_session)

    resp = await client.post(
        f"{BASE}/threads",
        json={"title": "Sobre el catalogo", "body": "Un tema general"},
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Sobre el catalogo"
    assert body["body"] == "Un tema general"
    assert body["entity_type"] is None
    assert body["entity_id"] is None
    assert body["status"] == "open"
    assert body["resolution_note"] is None
    assert body["author_username"] == VERIFIED_CREDS["username"]
    assert body["comments"] == []


async def test_create_thread_about_a_release(client: AsyncClient, db_session: AsyncSession):
    admin_headers = await _admin_headers(client, db_session)
    release_id = await _create_release(client, admin_headers)
    headers = await _verified_headers(client, db_session)

    resp = await client.post(
        f"{BASE}/threads",
        json={
            "title": "Fecha incorrecta",
            "body": "La fecha de esta edicion parece mal",
            "entity_type": "release",
            "entity_id": release_id,
        },
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["entity_type"] == "release"
    assert body["entity_id"] == release_id


async def test_create_thread_about_an_edition(client: AsyncClient, db_session: AsyncSession):
    admin_headers = await _admin_headers(client, db_session)
    release_id = await _create_release(client, admin_headers)
    edition_id = await _create_edition(client, admin_headers, release_id)
    headers = await _verified_headers(client, db_session)

    resp = await client.post(
        f"{BASE}/threads",
        json={
            "title": "Falta la portada",
            "body": "Esta edicion no tiene portada todavia",
            "entity_type": "edition",
            "entity_id": edition_id,
        },
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["entity_type"] == "edition"
    assert resp.json()["entity_id"] == edition_id


async def test_create_thread_release_requires_entity_id(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _verified_headers(client, db_session)

    resp = await client.post(
        f"{BASE}/threads",
        json={"title": "x", "body": "y", "entity_type": "release"},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_create_thread_discography_rejects_entity_id(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _verified_headers(client, db_session)

    resp = await client.post(
        f"{BASE}/threads",
        json={"title": "x", "body": "y", "entity_type": "discography", "entity_id": 1},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_create_thread_unknown_release_returns_422(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _verified_headers(client, db_session)

    resp = await client.post(
        f"{BASE}/threads",
        json={"title": "x", "body": "y", "entity_type": "release", "entity_id": 999},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_create_thread_unknown_edition_returns_422(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _verified_headers(client, db_session)

    resp = await client.post(
        f"{BASE}/threads",
        json={"title": "x", "body": "y", "entity_type": "edition", "entity_id": 999},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_verified_user_can_create_general_discography_thread(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _verified_headers(client, db_session)

    resp = await client.post(
        f"{BASE}/threads",
        json={
            "title": "Nuevo tipo de release",
            "body": "Deberiamos anadir 'directo'",
            "entity_type": "discography",
        },
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["entity_type"] == "discography"
    assert resp.json()["entity_id"] is None


# --- Leer hilos --------------------------------------------------------------------


async def test_get_unknown_thread_returns_404(client: AsyncClient):
    resp = await client.get(f"{BASE}/threads/999")
    assert resp.status_code == 404


async def test_list_threads_starts_empty(client: AsyncClient):
    resp = await client.get(f"{BASE}/threads")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_threads_filters_by_entity(client: AsyncClient, db_session: AsyncSession):
    admin_headers = await _admin_headers(client, db_session)
    release_id = await _create_release(client, admin_headers)
    headers = await _verified_headers(client, db_session)

    await client.post(
        f"{BASE}/threads",
        json={
            "title": "Sobre esta obra",
            "body": "...",
            "entity_type": "release",
            "entity_id": release_id,
        },
        headers=headers,
    )
    await client.post(
        f"{BASE}/threads", json={"title": "General", "body": "..."}, headers=headers
    )

    resp = await client.get(
        f"{BASE}/threads", params={"entity_type": "release", "entity_id": release_id}
    )
    assert resp.status_code == 200
    threads = resp.json()
    assert len(threads) == 1
    assert threads[0]["title"] == "Sobre esta obra"


async def test_list_threads_filters_by_status(client: AsyncClient, db_session: AsyncSession):
    admin_headers = await _admin_headers(client, db_session)
    headers = await _verified_headers(client, db_session)

    resp = await client.post(
        f"{BASE}/threads", json={"title": "Uno", "body": "..."}, headers=headers
    )
    thread_id = resp.json()["id"]
    await client.post(
        f"{BASE}/threads", json={"title": "Dos", "body": "..."}, headers=headers
    )
    await client.patch(
        f"{BASE}/threads/{thread_id}", json={"status": "resolved"}, headers=admin_headers
    )

    resp = await client.get(f"{BASE}/threads", params={"status": "open"})
    titles = {t["title"] for t in resp.json()}
    assert titles == {"Dos"}

    resp = await client.get(f"{BASE}/threads", params={"status": "resolved"})
    titles = {t["title"] for t in resp.json()}
    assert titles == {"Uno"}


async def test_list_threads_orders_most_recent_first(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _verified_headers(client, db_session)
    await client.post(f"{BASE}/threads", json={"title": "Primero", "body": ".."}, headers=headers)
    await client.post(f"{BASE}/threads", json={"title": "Segundo", "body": ".."}, headers=headers)

    resp = await client.get(f"{BASE}/threads")
    titles = [t["title"] for t in resp.json()]
    assert titles == ["Segundo", "Primero"]


async def test_list_threads_includes_comment_count(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _verified_headers(client, db_session)
    resp = await client.post(
        f"{BASE}/threads", json={"title": "Uno", "body": ".."}, headers=headers
    )
    thread_id = resp.json()["id"]
    await client.post(
        f"{BASE}/threads/{thread_id}/comments", json={"body": "primero"}, headers=headers
    )
    await client.post(
        f"{BASE}/threads/{thread_id}/comments", json={"body": "segundo"}, headers=headers
    )

    resp = await client.get(f"{BASE}/threads")
    assert resp.json()[0]["comment_count"] == 2


# --- Comentarios ---------------------------------------------------------------


async def test_add_comment_requires_verified_email(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _verified_headers(client, db_session)
    resp = await client.post(
        f"{BASE}/threads", json={"title": "x", "body": "y"}, headers=headers
    )
    thread_id = resp.json()["id"]

    await client.post(f"{AUTH_BASE}/register", json=UNVERIFIED_CREDS)
    unverified_headers = await _login(
        client, UNVERIFIED_CREDS["username"], UNVERIFIED_CREDS["password"]
    )

    resp = await client.post(
        f"{BASE}/threads/{thread_id}/comments",
        json={"body": "un comentario"},
        headers=unverified_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "email_not_verified"


async def test_add_comment_to_unknown_thread_returns_404(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _verified_headers(client, db_session)
    resp = await client.post(
        f"{BASE}/threads/999/comments", json={"body": "x"}, headers=headers
    )
    assert resp.status_code == 404


async def test_verified_user_can_comment(client: AsyncClient, db_session: AsyncSession):
    headers = await _verified_headers(client, db_session)
    resp = await client.post(
        f"{BASE}/threads", json={"title": "x", "body": "y"}, headers=headers
    )
    thread_id = resp.json()["id"]

    resp = await client.post(
        f"{BASE}/threads/{thread_id}/comments",
        json={"body": "un comentario"},
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["thread_id"] == thread_id
    assert body["body"] == "un comentario"
    assert body["author_username"] == VERIFIED_CREDS["username"]

    detail = await client.get(f"{BASE}/threads/{thread_id}")
    assert len(detail.json()["comments"]) == 1
    assert detail.json()["comments"][0]["body"] == "un comentario"


async def test_different_users_can_comment_on_same_thread(
    client: AsyncClient, db_session: AsyncSession
):
    author_headers = await _verified_headers(client, db_session)
    resp = await client.post(
        f"{BASE}/threads", json={"title": "x", "body": "y"}, headers=author_headers
    )
    thread_id = resp.json()["id"]

    other_creds = {
        "username": "otro",
        "email": "otro@ommadawn.com",
        "password": "otropassword1",
    }
    other_headers = await _verified_headers(client, db_session, other_creds)
    await client.post(
        f"{BASE}/threads/{thread_id}/comments",
        json={"body": "respuesta de otro usuario"},
        headers=other_headers,
    )

    detail = (await client.get(f"{BASE}/threads/{thread_id}")).json()
    assert len(detail["comments"]) == 1
    assert detail["comments"][0]["author_username"] == "otro"


# --- Cambiar status (solo admin) ------------------------------------------------


async def test_update_thread_status_requires_authentication(client: AsyncClient):
    resp = await client.patch(f"{BASE}/threads/1", json={"status": "resolved"})
    assert resp.status_code == 401


async def test_update_thread_status_requires_admin(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _verified_headers(client, db_session)
    resp = await client.post(
        f"{BASE}/threads", json={"title": "x", "body": "y"}, headers=headers
    )
    thread_id = resp.json()["id"]

    resp = await client.patch(
        f"{BASE}/threads/{thread_id}", json={"status": "resolved"}, headers=headers
    )
    assert resp.status_code == 403


async def test_update_unknown_thread_status_returns_404(
    client: AsyncClient, db_session: AsyncSession
):
    admin_headers = await _admin_headers(client, db_session)
    resp = await client.patch(
        f"{BASE}/threads/999", json={"status": "resolved"}, headers=admin_headers
    )
    assert resp.status_code == 404


async def test_admin_can_resolve_thread_with_note(
    client: AsyncClient, db_session: AsyncSession
):
    admin_headers = await _admin_headers(client, db_session)
    headers = await _verified_headers(client, db_session)
    resp = await client.post(
        f"{BASE}/threads", json={"title": "x", "body": "y"}, headers=headers
    )
    thread_id = resp.json()["id"]

    resp = await client.patch(
        f"{BASE}/threads/{thread_id}",
        json={"status": "resolved", "resolution_note": "Aplicado a mano en la edicion 3"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "resolved"
    assert body["resolution_note"] == "Aplicado a mano en la edicion 3"


async def test_update_thread_status_without_note_keeps_previous_note(
    client: AsyncClient, db_session: AsyncSession
):
    admin_headers = await _admin_headers(client, db_session)
    headers = await _verified_headers(client, db_session)
    resp = await client.post(
        f"{BASE}/threads", json={"title": "x", "body": "y"}, headers=headers
    )
    thread_id = resp.json()["id"]
    await client.patch(
        f"{BASE}/threads/{thread_id}",
        json={"status": "resolved", "resolution_note": "Nota original"},
        headers=admin_headers,
    )

    # Segundo cambio de status SIN mandar resolution_note: no debe borrarla.
    resp = await client.patch(
        f"{BASE}/threads/{thread_id}", json={"status": "closed"}, headers=admin_headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "closed"
    assert resp.json()["resolution_note"] == "Nota original"


async def test_update_thread_status_can_clear_note_with_null(
    client: AsyncClient, db_session: AsyncSession
):
    admin_headers = await _admin_headers(client, db_session)
    headers = await _verified_headers(client, db_session)
    resp = await client.post(
        f"{BASE}/threads", json={"title": "x", "body": "y"}, headers=headers
    )
    thread_id = resp.json()["id"]
    await client.patch(
        f"{BASE}/threads/{thread_id}",
        json={"status": "resolved", "resolution_note": "Se borrara"},
        headers=admin_headers,
    )

    resp = await client.patch(
        f"{BASE}/threads/{thread_id}",
        json={"status": "resolved", "resolution_note": None},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["resolution_note"] is None
