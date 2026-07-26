"""Tests de integracion del modulo de discografia.

Leer el catalogo es publico; crear exige ser administrador. Como no hay (a
proposito) un endpoint publico para promover a alguien a admin, los tests que lo
necesitan usan `db_session` para marcarlo directamente en la BD de prueba.
"""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User

BASE = "/api/v1/discography"
AUTH_BASE = "/api/v1/auth"

ADMIN_CREDS = {
    "username": "admin",
    "email": "admin@ommadawn.com",
    "password": "adminpass123",
}

FAN_CREDS = {
    "username": "fan",
    "email": "fan@ommadawn.com",
    "password": "fanpassword1",
}

# Payload de ejemplo: el primer disco de Mike Oldfield, con sus dos temas.
TUBULAR_BELLS = {
    "title": "Tubular Bells",
    "release_type": "studio",
    "release_date": "1973-05-25",
    "tracks": [
        {"position": 1, "title": "Tubular Bells, Part One", "duration_seconds": 1548},
        {"position": 2, "title": "Tubular Bells, Part Two", "duration_seconds": 1350},
    ],
}


async def _login(client: AsyncClient, username: str, password: str) -> dict:
    """Helper: hace login y devuelve la cabecera Authorization lista para usar."""
    resp = await client.post(
        f"{AUTH_BASE}/login",
        json={"username_or_email": username, "password": password},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _admin_headers(client: AsyncClient, db_session: AsyncSession) -> dict:
    """Registra un usuario, lo promueve a admin en BD y devuelve su cabecera."""
    await client.post(f"{AUTH_BASE}/register", json=ADMIN_CREDS)

    user = (
        await db_session.execute(
            select(User).where(User.username == ADMIN_CREDS["username"])
        )
    ).scalar_one()
    user.is_admin = True
    await db_session.commit()

    return await _login(client, ADMIN_CREDS["username"], ADMIN_CREDS["password"])


# --- Lectura (publica) ----------------------------------------------------------


async def test_list_releases_starts_empty(client: AsyncClient):
    resp = await client.get(f"{BASE}/releases")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_unknown_release_returns_404(client: AsyncClient):
    resp = await client.get(f"{BASE}/releases/999")
    assert resp.status_code == 404


# --- Escritura: control de acceso ------------------------------------------------


async def test_create_release_requires_authentication(client: AsyncClient):
    resp = await client.post(f"{BASE}/releases", json=TUBULAR_BELLS)
    assert resp.status_code == 401


async def test_create_release_requires_admin(client: AsyncClient):
    await client.post(f"{AUTH_BASE}/register", json=FAN_CREDS)
    headers = await _login(client, FAN_CREDS["username"], FAN_CREDS["password"])

    resp = await client.post(f"{BASE}/releases", json=TUBULAR_BELLS, headers=headers)
    assert resp.status_code == 403


# --- Escritura: creacion con temas ------------------------------------------------


async def test_admin_can_create_release_with_tracks(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)

    resp = await client.post(f"{BASE}/releases", json=TUBULAR_BELLS, headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Tubular Bells"
    assert body["release_type"] == "studio"
    assert body["release_date"] == "1973-05-25"
    assert [t["title"] for t in body["tracks"]] == [
        "Tubular Bells, Part One",
        "Tubular Bells, Part Two",
    ]


async def test_create_release_rejects_duplicate_track_positions(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    payload = {
        **TUBULAR_BELLS,
        "tracks": [
            {"position": 1, "title": "A"},
            {"position": 1, "title": "B"},  # misma posicion que la anterior
        ],
    }

    resp = await client.post(f"{BASE}/releases", json=payload, headers=headers)
    assert resp.status_code == 422


async def test_release_without_tracks_is_allowed(
    client: AsyncClient, db_session: AsyncSession
):
    # Un bootleg del que aun no se ha catalogado la tracklist es un caso valido.
    headers = await _admin_headers(client, db_session)
    payload = {"title": "Unknown Bootleg", "release_type": "bootleg", "tracks": []}

    resp = await client.post(f"{BASE}/releases", json=payload, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["tracks"] == []


# --- Lectura tras crear -----------------------------------------------------------


async def test_get_release_by_id(client: AsyncClient, db_session: AsyncSession):
    headers = await _admin_headers(client, db_session)
    created = await client.post(f"{BASE}/releases", json=TUBULAR_BELLS, headers=headers)
    release_id = created.json()["id"]

    resp = await client.get(f"{BASE}/releases/{release_id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Tubular Bells"


async def test_list_releases_filters_by_type(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    await client.post(f"{BASE}/releases", json=TUBULAR_BELLS, headers=headers)
    await client.post(
        f"{BASE}/releases",
        json={"title": "Boxed", "release_type": "compilation", "tracks": []},
        headers=headers,
    )

    resp = await client.get(f"{BASE}/releases", params={"type": "compilation"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["title"] == "Boxed"
