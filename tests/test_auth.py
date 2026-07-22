"""Tests de integracion del modulo de auth.

Cada test ejerce un COMPORTAMIENTO observable desde fuera (la respuesta HTTP), no
los detalles internos. Con `asyncio_mode = "auto"` (en pyproject) no hace falta
marcar cada test: pytest-asyncio los detecta por ser `async def`.
"""

from httpx import AsyncClient

BASE = "/api/v1/auth"

# Credenciales de ejemplo reutilizadas en los tests.
CREDS = {
    "username": "mike",
    "email": "mike@oldfield.com",
    "password": "tubular123",
    "full_name": "Mike Oldfield",
}


async def _register_and_login(client: AsyncClient) -> dict:
    """Helper: registra al usuario de ejemplo, hace login y devuelve los tokens."""
    await client.post(f"{BASE}/register", json=CREDS)
    resp = await client.post(
        f"{BASE}/login",
        json={"username_or_email": CREDS["username"], "password": CREDS["password"]},
    )
    return resp.json()


# --- Registro ------------------------------------------------------------------


async def test_register_creates_user_without_leaking_password(client: AsyncClient):
    resp = await client.post(f"{BASE}/register", json=CREDS)
    assert resp.status_code == 201
    body = resp.json()
    assert body["username"] == "mike"
    assert body["email"] == "mike@oldfield.com"
    assert body["is_active"] is True
    assert body["is_admin"] is False
    # Lo mas importante: la contrasena (ni su hash) NUNCA sale por la API.
    assert "password" not in body
    assert "hashed_password" not in body


async def test_register_duplicate_username_returns_409(client: AsyncClient):
    await client.post(f"{BASE}/register", json=CREDS)
    resp = await client.post(
        f"{BASE}/register",
        json={**CREDS, "email": "otro@correo.com"},  # mismo username, otro email
    )
    assert resp.status_code == 409


async def test_register_duplicate_email_returns_409(client: AsyncClient):
    await client.post(f"{BASE}/register", json=CREDS)
    resp = await client.post(
        f"{BASE}/register",
        json={**CREDS, "username": "otro"},  # mismo email, otro username
    )
    assert resp.status_code == 409


async def test_register_invalid_payload_returns_422(client: AsyncClient):
    # Email mal formado y contrasena demasiado corta -> Pydantic rechaza (422).
    resp = await client.post(
        f"{BASE}/register",
        json={"username": "x", "email": "no-es-email", "password": "corta"},
    )
    assert resp.status_code == 422


# --- Login ---------------------------------------------------------------------


async def test_login_with_username(client: AsyncClient):
    await client.post(f"{BASE}/register", json=CREDS)
    resp = await client.post(
        f"{BASE}/login",
        json={"username_or_email": "mike", "password": "tubular123"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]


async def test_login_with_email(client: AsyncClient):
    await client.post(f"{BASE}/register", json=CREDS)
    resp = await client.post(
        f"{BASE}/login",
        json={"username_or_email": "mike@oldfield.com", "password": "tubular123"},
    )
    assert resp.status_code == 200


async def test_login_wrong_password_returns_401(client: AsyncClient):
    await client.post(f"{BASE}/register", json=CREDS)
    resp = await client.post(
        f"{BASE}/login",
        json={"username_or_email": "mike", "password": "incorrecta"},
    )
    assert resp.status_code == 401


async def test_login_unknown_user_returns_401(client: AsyncClient):
    resp = await client.post(
        f"{BASE}/login",
        json={"username_or_email": "fantasma", "password": "loquesea1"},
    )
    assert resp.status_code == 401


# --- /me (endpoint protegido) --------------------------------------------------


async def test_me_without_token_is_rejected(client: AsyncClient):
    resp = await client.get(f"{BASE}/me")
    assert resp.status_code == 401


async def test_me_with_token_returns_current_user(client: AsyncClient):
    tokens = await _register_and_login(client)
    resp = await client.get(
        f"{BASE}/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert resp.status_code == 200
    assert resp.json()["username"] == "mike"


async def test_me_with_garbage_token_returns_401(client: AsyncClient):
    resp = await client.get(
        f"{BASE}/me", headers={"Authorization": "Bearer no.es.un.jwt"}
    )
    assert resp.status_code == 401


# --- Refresh + rotacion --------------------------------------------------------


async def test_refresh_rotates_and_invalidates_old_token(client: AsyncClient):
    tokens = await _register_and_login(client)
    old_refresh = tokens["refresh_token"]

    resp = await client.post(f"{BASE}/refresh", json={"refresh_token": old_refresh})
    assert resp.status_code == 200
    new_refresh = resp.json()["refresh_token"]
    # El refresh token es aleatorio: el nuevo siempre es distinto del anterior.
    assert new_refresh != old_refresh

    # Reusar el refresh viejo (ya rotado) debe fallar: es la deteccion basica.
    reuse = await client.post(f"{BASE}/refresh", json={"refresh_token": old_refresh})
    assert reuse.status_code == 401


async def test_refresh_with_invalid_token_returns_401(client: AsyncClient):
    resp = await client.post(f"{BASE}/refresh", json={"refresh_token": "inventado"})
    assert resp.status_code == 401


# --- Logout --------------------------------------------------------------------


async def test_logout_revokes_refresh_token(client: AsyncClient):
    tokens = await _register_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    logout = await client.post(
        f"{BASE}/logout",
        json={"refresh_token": tokens["refresh_token"]},
        headers=headers,
    )
    assert logout.status_code == 204

    # Tras el logout, ese refresh token ya no sirve para renovar.
    after = await client.post(
        f"{BASE}/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert after.status_code == 401


async def test_logout_requires_authentication(client: AsyncClient):
    tokens = await _register_and_login(client)
    # Sin cabecera Authorization no se puede hacer logout.
    resp = await client.post(
        f"{BASE}/logout", json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 401
