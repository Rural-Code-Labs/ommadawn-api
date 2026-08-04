"""Tests de integracion del modulo de auth.

Cada test ejerce un COMPORTAMIENTO observable desde fuera (la respuesta HTTP), no
los detalles internos. Con `asyncio_mode = "auto"` (en pyproject) no hace falta
marcar cada test: pytest-asyncio los detecta por ser `async def`.
"""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.auth.models import User

BASE = "/api/v1/auth"

# Vida esperada del access token (segundos), derivada de la config real.
EXPECTED_EXPIRES_IN = get_settings().access_token_expire_minutes * 60

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
    # La respuesta anuncia la vida del access token para renovar de forma proactiva.
    assert body["expires_in"] == EXPECTED_EXPIRES_IN


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
    body = resp.json()
    new_refresh = body["refresh_token"]
    # El refresh token es aleatorio: el nuevo siempre es distinto del anterior.
    assert new_refresh != old_refresh
    # Refresh tambien anuncia la vida del nuevo access token.
    assert body["expires_in"] == EXPECTED_EXPIRES_IN

    # Reusar el refresh viejo (ya rotado) debe fallar: es la deteccion basica.
    reuse = await client.post(f"{BASE}/refresh", json={"refresh_token": old_refresh})
    assert reuse.status_code == 401


async def test_refresh_with_invalid_token_returns_401(client: AsyncClient):
    resp = await client.post(f"{BASE}/refresh", json={"refresh_token": "inventado"})
    assert resp.status_code == 401


async def test_reusing_rotated_token_revokes_entire_session(client: AsyncClient):
    # Deteccion de reuso: si un refresh token YA rotado reaparece, es senal de
    # robo -> se revoca TODA la sesion del usuario, no solo ese token.
    await client.post(f"{BASE}/register", json=CREDS)
    login = {"username_or_email": "mike", "password": "tubular123"}

    # Dos sesiones activas del mismo usuario (p. ej. dos dispositivos).
    session_a = (await client.post(f"{BASE}/login", json=login)).json()["refresh_token"]
    session_b = (await client.post(f"{BASE}/login", json=login)).json()["refresh_token"]

    # Rotamos la sesion A: `session_a` queda revocado, nace `session_a_new`.
    rotated = await client.post(f"{BASE}/refresh", json={"refresh_token": session_a})
    assert rotated.status_code == 200
    session_a_new = rotated.json()["refresh_token"]

    # REUSO: volvemos a mandar `session_a` (ya rotado) -> 401 y dispara la alarma.
    reuse = await client.post(f"{BASE}/refresh", json={"refresh_token": session_a})
    assert reuse.status_code == 401

    # Consecuencia: NINGUN refresh token del usuario sirve ya, ni el token nuevo
    # y legitimo de A ni la otra sesion B. Todo el mundo debe re-loguear.
    assert (
        await client.post(f"{BASE}/refresh", json={"refresh_token": session_a_new})
    ).status_code == 401
    assert (
        await client.post(f"{BASE}/refresh", json={"refresh_token": session_b})
    ).status_code == 401


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


# --- Avatar ----------------------------------------------------------------------

# Un JPEG minimo valido (cabecera SOI + EOI): basta para pasar la validacion de
# content-type, no hace falta una imagen real para probar el flujo de subida.
FAKE_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 16 + b"\xff\xd9"


async def test_upload_avatar_requires_authentication(client: AsyncClient):
    resp = await client.post(
        f"{BASE}/me/avatar",
        files={"file": ("avatar.jpg", FAKE_JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 401


async def test_can_upload_own_avatar(client: AsyncClient):
    tokens = await _register_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    resp = await client.post(
        f"{BASE}/me/avatar",
        files={"file": ("avatar.jpg", FAKE_JPEG_BYTES, "image/jpeg")},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["avatar_url"].startswith("http://testserver/media/")

    # Y se refleja al leer /me.
    me = await client.get(f"{BASE}/me", headers=headers)
    assert me.json()["avatar_url"] == body["avatar_url"]


async def test_uploading_a_new_avatar_replaces_the_previous_one(client: AsyncClient):
    tokens = await _register_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    first = await client.post(
        f"{BASE}/me/avatar",
        files={"file": ("v1.jpg", FAKE_JPEG_BYTES, "image/jpeg")},
        headers=headers,
    )
    second = await client.post(
        f"{BASE}/me/avatar",
        files={"file": ("v2.jpg", FAKE_JPEG_BYTES, "image/jpeg")},
        headers=headers,
    )
    assert second.status_code == 200
    assert second.json()["avatar_url"] != first.json()["avatar_url"]


async def test_upload_avatar_rejects_unsupported_content_type(client: AsyncClient):
    tokens = await _register_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    resp = await client.post(
        f"{BASE}/me/avatar",
        files={"file": ("avatar.pdf", b"%PDF-1.4 ...", "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_upload_avatar_rejects_oversized_image(client: AsyncClient, monkeypatch):
    from app.core import storage

    # Bajamos el limite a 10 bytes para no tener que generar un fichero enorme.
    monkeypatch.setattr(storage, "MAX_IMAGE_SIZE_BYTES", 10)

    tokens = await _register_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    resp = await client.post(
        f"{BASE}/me/avatar",
        files={"file": ("avatar.jpg", FAKE_JPEG_BYTES, "image/jpeg")},
        headers=headers,
    )
    assert resp.status_code == 413


async def test_delete_avatar_requires_authentication(client: AsyncClient):
    resp = await client.delete(f"{BASE}/me/avatar")
    assert resp.status_code == 401


async def test_can_delete_own_avatar(client: AsyncClient):
    tokens = await _register_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    await client.post(
        f"{BASE}/me/avatar",
        files={"file": ("avatar.jpg", FAKE_JPEG_BYTES, "image/jpeg")},
        headers=headers,
    )

    resp = await client.delete(f"{BASE}/me/avatar", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["avatar_url"] is None


async def test_deleting_avatar_when_none_exists_is_a_no_op(client: AsyncClient):
    tokens = await _register_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    resp = await client.delete(f"{BASE}/me/avatar", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["avatar_url"] is None


# --- Seguridad: no se puede escalar privilegios al registrarse -------------------


async def test_register_cannot_inject_admin_roles(client: AsyncClient):
    # Ni is_admin ni is_super_admin existen en UserCreate: Pydantic los ignora y
    # el service nunca los lee, asi que da igual lo que mande el cliente.
    resp = await client.post(
        f"{BASE}/register",
        json={**CREDS, "is_admin": True, "is_super_admin": True},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["is_admin"] is False
    assert body["is_super_admin"] is False


# --- Perfil: PATCH /me -------------------------------------------------------------


async def test_update_profile_requires_authentication(client: AsyncClient):
    resp = await client.patch(f"{BASE}/me", json={"country": "ES"})
    assert resp.status_code == 401


async def test_update_profile_only_touches_sent_fields(client: AsyncClient):
    tokens = await _register_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    resp = await client.patch(f"{BASE}/me", json={"country": "ES"}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["country"] == "ES"
    # No enviado: sigue como se registro.
    assert body["full_name"] == CREDS["full_name"]
    assert body["city"] is None


async def test_update_profile_sets_birth_date(client: AsyncClient):
    tokens = await _register_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    resp = await client.patch(
        f"{BASE}/me", json={"birth_date": "1953-05-15"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["birth_date"] == "1953-05-15"


async def test_update_profile_can_clear_a_field_with_null(client: AsyncClient):
    tokens = await _register_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    await client.patch(f"{BASE}/me", json={"country": "ES"}, headers=headers)

    resp = await client.patch(f"{BASE}/me", json={"country": None}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["country"] is None


async def test_register_defaults_theme_preference_to_system(client: AsyncClient):
    resp = await client.post(f"{BASE}/register", json=CREDS)
    assert resp.status_code == 201
    assert resp.json()["theme_preference"] == "system"


async def test_update_profile_can_change_theme_preference(client: AsyncClient):
    tokens = await _register_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    resp = await client.patch(
        f"{BASE}/me", json={"theme_preference": "dark"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["theme_preference"] == "dark"


async def test_update_profile_rejects_null_theme_preference(client: AsyncClient):
    # theme_preference NO es nullable en BD: un null explicito debe dar 422,
    # no reventar en el commit.
    tokens = await _register_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    resp = await client.patch(
        f"{BASE}/me", json={"theme_preference": None}, headers=headers
    )
    assert resp.status_code == 422


async def test_update_profile_cannot_touch_admin_fields(client: AsyncClient):
    # UserUpdate no declara is_admin/is_super_admin/username/email: si se mandan,
    # Pydantic los ignora (no son campos del schema, no dan ni 422).
    tokens = await _register_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    resp = await client.patch(
        f"{BASE}/me", json={"is_admin": True, "username": "otro"}, headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_admin"] is False
    assert body["username"] == CREDS["username"]


# --- Superadmin: gestion de quien es admin -----------------------------------------

SUPERADMIN_CREDS = {
    "username": "root",
    "email": "root@ommadawn.com",
    "password": "rootpassword1",
}


async def _superadmin_headers(client: AsyncClient, db_session: AsyncSession) -> dict:
    """Registra un usuario, lo marca is_super_admin=True en BD y hace login."""
    await client.post(f"{BASE}/register", json=SUPERADMIN_CREDS)

    user = (
        await db_session.execute(
            select(User).where(User.username == SUPERADMIN_CREDS["username"])
        )
    ).scalar_one()
    user.is_super_admin = True
    await db_session.commit()

    login = await client.post(
        f"{BASE}/login",
        json={
            "username_or_email": SUPERADMIN_CREDS["username"],
            "password": SUPERADMIN_CREDS["password"],
        },
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_list_users_requires_authentication(client: AsyncClient):
    resp = await client.get(f"{BASE}/users")
    assert resp.status_code == 401


async def test_list_users_requires_superadmin(client: AsyncClient):
    tokens = await _register_and_login(client)  # usuario normal
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    resp = await client.get(f"{BASE}/users", headers=headers)
    assert resp.status_code == 403


async def test_regular_admin_cannot_manage_other_admins(
    client: AsyncClient, db_session: AsyncSession
):
    # Un admin normal (is_admin=True, is_super_admin=False) no basta: hace falta
    # ser superadmin para decidir quien es admin.
    await client.post(f"{BASE}/register", json=CREDS)
    admin_user = (
        await db_session.execute(select(User).where(User.username == CREDS["username"]))
    ).scalar_one()
    admin_user.is_admin = True
    await db_session.commit()

    login = await client.post(
        f"{BASE}/login",
        json={"username_or_email": CREDS["username"], "password": CREDS["password"]},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.get(f"{BASE}/users", headers=headers)
    assert resp.status_code == 403


async def test_superadmin_can_list_users(client: AsyncClient, db_session: AsyncSession):
    await _register_and_login(client)
    headers = await _superadmin_headers(client, db_session)

    resp = await client.get(f"{BASE}/users", headers=headers)
    assert resp.status_code == 200
    usernames = {u["username"] for u in resp.json()}
    assert {CREDS["username"], SUPERADMIN_CREDS["username"]}.issubset(usernames)


async def test_superadmin_can_promote_another_user_to_admin(
    client: AsyncClient, db_session: AsyncSession
):
    await client.post(f"{BASE}/register", json=CREDS)
    target = (
        await db_session.execute(select(User).where(User.username == CREDS["username"]))
    ).scalar_one()
    headers = await _superadmin_headers(client, db_session)

    resp = await client.patch(
        f"{BASE}/users/{target.id}", json={"is_admin": True}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["is_admin"] is True


async def test_superadmin_can_demote_an_admin(
    client: AsyncClient, db_session: AsyncSession
):
    await client.post(f"{BASE}/register", json=CREDS)
    target = (
        await db_session.execute(select(User).where(User.username == CREDS["username"]))
    ).scalar_one()
    target.is_admin = True
    await db_session.commit()
    target_id = target.id

    headers = await _superadmin_headers(client, db_session)
    resp = await client.patch(
        f"{BASE}/users/{target_id}", json={"is_admin": False}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["is_admin"] is False


async def test_update_user_admin_status_unknown_user_returns_404(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _superadmin_headers(client, db_session)
    resp = await client.patch(
        f"{BASE}/users/999", json={"is_admin": True}, headers=headers
    )
    assert resp.status_code == 404


async def test_update_user_admin_status_cannot_touch_super_admin_flag(
    client: AsyncClient, db_session: AsyncSession
):
    # UserAdminUpdate solo declara is_admin: is_super_admin ni se puede enviar.
    await client.post(f"{BASE}/register", json=CREDS)
    target = (
        await db_session.execute(select(User).where(User.username == CREDS["username"]))
    ).scalar_one()
    target_id = target.id
    headers = await _superadmin_headers(client, db_session)

    resp = await client.patch(
        f"{BASE}/users/{target_id}",
        json={"is_admin": True, "is_super_admin": True},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["is_super_admin"] is False
