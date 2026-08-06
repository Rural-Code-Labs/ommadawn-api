"""Tests de integracion del modulo de discografia.

Tres niveles: Release (la obra) -> Edition (una publicacion concreta) -> Track.
Leer el catalogo es publico; crear/editar/borrar exige ser administrador. Como
no hay (a proposito) un endpoint publico para promover a alguien a admin, los
tests que lo necesitan usan `db_session` para marcarlo directamente en la BD.
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

TUBULAR_BELLS = {"title": "Tubular Bells", "release_type": "studio"}

UK_1973_EDITION = {
    "country": "GB",
    "edition_name": "Edicion original",
    "catalog_number": "V2001",
    "release_date": "1973-05-25",
    "format": "vinyl",
    "credits": "Mike Oldfield: todos los instrumentos. Producido por Tom Newman y Simon Heyworth.",
    "notes": "Primer album de Mike Oldfield, grabado en The Manor Studio.",
    "is_primary": True,
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


async def _create_release(client: AsyncClient, headers: dict) -> int:
    """Helper: crea la obra de ejemplo y devuelve su id."""
    resp = await client.post(f"{BASE}/releases", json=TUBULAR_BELLS, headers=headers)
    return resp.json()["id"]


async def _create_release_and_edition(client: AsyncClient, headers: dict) -> tuple[int, int]:
    """Helper: crea la obra y una edicion de ejemplo. Devuelve (release_id, edition_id)."""
    release_id = await _create_release(client, headers)
    edition = await client.post(
        f"{BASE}/releases/{release_id}/editions", json=UK_1973_EDITION, headers=headers
    )
    return release_id, edition.json()["id"]


# Un JPEG minimo valido (cabecera SOI + EOI): basta para pasar la validacion de
# content-type, no hace falta una imagen real para probar el flujo de subida.
FAKE_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 16 + b"\xff\xd9"


# --- Release: lectura (publica) --------------------------------------------------


async def test_list_releases_starts_empty(client: AsyncClient):
    resp = await client.get(f"{BASE}/releases")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_unknown_release_returns_404(client: AsyncClient):
    resp = await client.get(f"{BASE}/releases/999")
    assert resp.status_code == 404


# --- Release: control de acceso ---------------------------------------------------


async def test_create_release_requires_authentication(client: AsyncClient):
    resp = await client.post(f"{BASE}/releases", json=TUBULAR_BELLS)
    assert resp.status_code == 401


async def test_create_release_requires_admin(client: AsyncClient):
    await client.post(f"{AUTH_BASE}/register", json=FAN_CREDS)
    headers = await _login(client, FAN_CREDS["username"], FAN_CREDS["password"])

    resp = await client.post(f"{BASE}/releases", json=TUBULAR_BELLS, headers=headers)
    assert resp.status_code == 403


async def test_superadmin_without_is_admin_can_also_create_releases(
    client: AsyncClient, db_session: AsyncSession
):
    # Regresion: require_admin acepta is_admin O is_super_admin (ver
    # auth/dependencies.py). Un superadmin no necesita ademas is_admin=True.
    creds = {"username": "root", "email": "root@ommadawn.com", "password": "rootpassword1"}
    await client.post(f"{AUTH_BASE}/register", json=creds)
    user = (
        await db_session.execute(select(User).where(User.username == creds["username"]))
    ).scalar_one()
    assert user.is_admin is False
    user.is_super_admin = True
    await db_session.commit()

    headers = await _login(client, creds["username"], creds["password"])
    resp = await client.post(f"{BASE}/releases", json=TUBULAR_BELLS, headers=headers)
    assert resp.status_code == 201


# --- Release: creacion, edicion y borrado -----------------------------------------


async def test_admin_can_create_release_without_editions(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)

    resp = await client.post(f"{BASE}/releases", json=TUBULAR_BELLS, headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Tubular Bells"
    assert body["release_type"] == "studio"
    assert body["editions"] == []


async def test_update_release_only_touches_sent_fields(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    release_id = await _create_release(client, headers)

    resp = await client.patch(
        f"{BASE}/releases/{release_id}",
        json={"title": "Tubular Bells (nuevo titulo)"},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Tubular Bells (nuevo titulo)"
    assert body["release_type"] == "studio"  # no enviado, no se toca


async def test_update_unknown_release_returns_404(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    resp = await client.patch(
        f"{BASE}/releases/999", json={"title": "Nuevo"}, headers=headers
    )
    assert resp.status_code == 404


async def test_admin_can_delete_release(client: AsyncClient, db_session: AsyncSession):
    headers = await _admin_headers(client, db_session)
    release_id = await _create_release(client, headers)

    resp = await client.delete(f"{BASE}/releases/{release_id}", headers=headers)
    assert resp.status_code == 204

    after = await client.get(f"{BASE}/releases/{release_id}")
    assert after.status_code == 404


async def test_list_releases_filters_by_type(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    await client.post(f"{BASE}/releases", json=TUBULAR_BELLS, headers=headers)
    await client.post(
        f"{BASE}/releases",
        json={"title": "Boxed", "release_type": "compilation"},
        headers=headers,
    )

    resp = await client.get(f"{BASE}/releases", params={"type": "compilation"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["title"] == "Boxed"


# --- Edition: control de acceso ---------------------------------------------------


async def test_create_edition_requires_admin(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    release_id = await _create_release(client, headers)

    resp = await client.post(f"{BASE}/releases/{release_id}/editions", json=UK_1973_EDITION)
    assert resp.status_code == 401


# --- Edition: creacion con temas ---------------------------------------------------


async def test_admin_can_create_edition_with_tracks(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    release_id = await _create_release(client, headers)

    resp = await client.post(
        f"{BASE}/releases/{release_id}/editions", json=UK_1973_EDITION, headers=headers
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["country"] == "GB"
    assert body["format"] == "vinyl"
    assert body["catalog_number"] == "V2001"
    assert body["credits"] == UK_1973_EDITION["credits"]
    assert body["notes"] == UK_1973_EDITION["notes"]
    assert body["is_primary"] is True
    assert [t["title"] for t in body["tracks"]] == [
        "Tubular Bells, Part One",
        "Tubular Bells, Part Two",
    ]

    # Y aparece anidada al leer la obra completa.
    release = (await client.get(f"{BASE}/releases/{release_id}")).json()
    assert len(release["editions"]) == 1
    assert release["editions"][0]["country"] == "GB"


async def test_create_edition_on_unknown_release_returns_404(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    resp = await client.post(
        f"{BASE}/releases/999/editions", json=UK_1973_EDITION, headers=headers
    )
    assert resp.status_code == 404


async def test_create_edition_rejects_duplicate_track_positions(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    release_id = await _create_release(client, headers)
    payload = {
        **UK_1973_EDITION,
        "tracks": [{"position": 1, "title": "A"}, {"position": 1, "title": "B"}],
    }

    resp = await client.post(
        f"{BASE}/releases/{release_id}/editions", json=payload, headers=headers
    )
    assert resp.status_code == 422


async def test_edition_without_tracks_is_allowed(
    client: AsyncClient, db_session: AsyncSession
):
    # Una edicion de la que aun no se ha catalogado la tracklist es valida.
    headers = await _admin_headers(client, db_session)
    release_id = await _create_release(client, headers)

    resp = await client.post(
        f"{BASE}/releases/{release_id}/editions",
        json={"country": "JP", "tracks": []},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["tracks"] == []


# --- Edition: solo una principal por obra -----------------------------------------


async def test_marking_a_new_edition_primary_demotes_the_previous_one(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    release_id = await _create_release(client, headers)

    first = await client.post(
        f"{BASE}/releases/{release_id}/editions", json=UK_1973_EDITION, headers=headers
    )
    assert first.json()["is_primary"] is True

    second = await client.post(
        f"{BASE}/releases/{release_id}/editions",
        json={**UK_1973_EDITION, "country": "JP", "is_primary": True, "tracks": []},
        headers=headers,
    )
    assert second.status_code == 201
    assert second.json()["is_primary"] is True

    # La primera ha quedado desmarcada automaticamente: no hace falta que el
    # admin lo gestione a mano ni se viola el indice unico parcial.
    release = (await client.get(f"{BASE}/releases/{release_id}")).json()
    primaries = [e for e in release["editions"] if e["is_primary"]]
    assert len(primaries) == 1
    assert primaries[0]["country"] == "JP"


# --- Edition: edicion (PATCH) ------------------------------------------------------


async def test_update_edition_only_touches_sent_fields(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    release_id = await _create_release(client, headers)
    created = await client.post(
        f"{BASE}/releases/{release_id}/editions", json=UK_1973_EDITION, headers=headers
    )
    edition_id = created.json()["id"]

    resp = await client.patch(
        f"{BASE}/releases/{release_id}/editions/{edition_id}",
        json={"edition_name": "Reedicion remasterizada"},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["edition_name"] == "Reedicion remasterizada"
    assert body["country"] == "GB"  # no enviado, no se toca
    assert body["format"] == "vinyl"  # tampoco se toca
    assert len(body["tracks"]) == 2  # tampoco se tocan


async def test_update_edition_can_change_format(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    release_id = await _create_release(client, headers)
    created = await client.post(
        f"{BASE}/releases/{release_id}/editions", json=UK_1973_EDITION, headers=headers
    )
    edition_id = created.json()["id"]

    resp = await client.patch(
        f"{BASE}/releases/{release_id}/editions/{edition_id}",
        json={"format": "cd"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["format"] == "cd"


async def test_update_edition_can_change_catalog_number_credits_and_notes(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    release_id = await _create_release(client, headers)
    created = await client.post(
        f"{BASE}/releases/{release_id}/editions", json=UK_1973_EDITION, headers=headers
    )
    edition_id = created.json()["id"]

    resp = await client.patch(
        f"{BASE}/releases/{release_id}/editions/{edition_id}",
        json={
            "catalog_number": "CDV 2001",
            "credits": "Remasterizado por ...",
            "notes": "Reedicion en CD.",
        },
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["catalog_number"] == "CDV 2001"
    assert body["credits"] == "Remasterizado por ..."
    assert body["notes"] == "Reedicion en CD."


async def test_update_edition_can_clear_a_nullable_field(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    release_id = await _create_release(client, headers)
    created = await client.post(
        f"{BASE}/releases/{release_id}/editions", json=UK_1973_EDITION, headers=headers
    )
    edition_id = created.json()["id"]

    resp = await client.patch(
        f"{BASE}/releases/{release_id}/editions/{edition_id}",
        json={"release_date": None},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["release_date"] is None


async def test_update_edition_with_tracks_replaces_the_whole_tracklist(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    release_id = await _create_release(client, headers)
    created = await client.post(
        f"{BASE}/releases/{release_id}/editions", json=UK_1973_EDITION, headers=headers
    )
    edition_id = created.json()["id"]

    resp = await client.patch(
        f"{BASE}/releases/{release_id}/editions/{edition_id}",
        json={"tracks": [{"position": 1, "title": "Version unica"}]},
        headers=headers,
    )
    assert resp.status_code == 200
    tracks = resp.json()["tracks"]
    assert len(tracks) == 1
    assert tracks[0]["title"] == "Version unica"


async def test_update_unknown_edition_returns_404(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    release_id = await _create_release(client, headers)

    resp = await client.patch(
        f"{BASE}/releases/{release_id}/editions/999",
        json={"edition_name": "X"},
        headers=headers,
    )
    assert resp.status_code == 404


async def test_edition_from_another_release_is_not_reachable(
    client: AsyncClient, db_session: AsyncSession
):
    # Una edicion existe, pero bajo OTRA obra: no debe poder editarse mezclando ids.
    headers = await _admin_headers(client, db_session)
    release_id = await _create_release(client, headers)
    other_release_id = await _create_release(client, headers)
    created = await client.post(
        f"{BASE}/releases/{release_id}/editions", json=UK_1973_EDITION, headers=headers
    )
    edition_id = created.json()["id"]

    resp = await client.patch(
        f"{BASE}/releases/{other_release_id}/editions/{edition_id}",
        json={"edition_name": "X"},
        headers=headers,
    )
    assert resp.status_code == 404


# --- Edition: borrado ---------------------------------------------------------------


async def test_admin_can_delete_edition(client: AsyncClient, db_session: AsyncSession):
    headers = await _admin_headers(client, db_session)
    release_id = await _create_release(client, headers)
    created = await client.post(
        f"{BASE}/releases/{release_id}/editions", json=UK_1973_EDITION, headers=headers
    )
    edition_id = created.json()["id"]

    resp = await client.delete(
        f"{BASE}/releases/{release_id}/editions/{edition_id}", headers=headers
    )
    assert resp.status_code == 204

    release = (await client.get(f"{BASE}/releases/{release_id}")).json()
    assert release["editions"] == []


# --- Image: subida ------------------------------------------------------------------


async def test_upload_image_requires_admin(client: AsyncClient, db_session: AsyncSession):
    headers = await _admin_headers(client, db_session)
    release_id, edition_id = await _create_release_and_edition(client, headers)

    resp = await client.post(
        f"{BASE}/releases/{release_id}/editions/{edition_id}/images",
        data={"image_type": "front_cover"},
        files={"file": ("cover.jpg", FAKE_JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 401


async def test_admin_can_upload_front_cover(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    release_id, edition_id = await _create_release_and_edition(client, headers)

    resp = await client.post(
        f"{BASE}/releases/{release_id}/editions/{edition_id}/images",
        data={"image_type": "front_cover"},
        files={"file": ("cover.jpg", FAKE_JPEG_BYTES, "image/jpeg")},
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["image_type"] == "front_cover"
    assert body["url"].startswith("http://testserver/media/")

    # Y aparece anidada al leer la obra completa.
    release = (await client.get(f"{BASE}/releases/{release_id}")).json()
    images = release["editions"][0]["images"]
    assert len(images) == 1
    assert images[0]["image_type"] == "front_cover"


async def test_uploading_a_new_front_cover_replaces_the_previous_one(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    release_id, edition_id = await _create_release_and_edition(client, headers)
    upload_url = f"{BASE}/releases/{release_id}/editions/{edition_id}/images"

    first = await client.post(
        upload_url,
        data={"image_type": "front_cover"},
        files={"file": ("v1.jpg", FAKE_JPEG_BYTES, "image/jpeg")},
        headers=headers,
    )
    second = await client.post(
        upload_url,
        data={"image_type": "front_cover"},
        files={"file": ("v2.jpg", FAKE_JPEG_BYTES, "image/jpeg")},
        headers=headers,
    )
    assert second.status_code == 201
    assert second.json()["url"] != first.json()["url"]

    release = (await client.get(f"{BASE}/releases/{release_id}")).json()
    images = release["editions"][0]["images"]
    # Solo queda UNA front_cover: la segunda sustituyo a la primera.
    assert len(images) == 1
    assert images[0]["url"] == second.json()["url"]


async def test_uploading_other_images_accumulates(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    release_id, edition_id = await _create_release_and_edition(client, headers)
    upload_url = f"{BASE}/releases/{release_id}/editions/{edition_id}/images"

    await client.post(
        upload_url,
        data={"image_type": "other"},
        files={"file": ("booklet-1.jpg", FAKE_JPEG_BYTES, "image/jpeg")},
        headers=headers,
    )
    await client.post(
        upload_url,
        data={"image_type": "other"},
        files={"file": ("booklet-2.jpg", FAKE_JPEG_BYTES, "image/jpeg")},
        headers=headers,
    )

    release = (await client.get(f"{BASE}/releases/{release_id}")).json()
    images = release["editions"][0]["images"]
    assert len(images) == 2


async def test_upload_rejects_unsupported_content_type(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    release_id, edition_id = await _create_release_and_edition(client, headers)

    resp = await client.post(
        f"{BASE}/releases/{release_id}/editions/{edition_id}/images",
        data={"image_type": "front_cover"},
        files={"file": ("cover.pdf", b"%PDF-1.4 ...", "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_upload_rejects_oversized_image(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    from app.core import storage

    # Bajamos el limite a 10 bytes para no tener que generar un fichero enorme.
    # La validacion vive en core/storage.py (compartida con el avatar de usuario).
    monkeypatch.setattr(storage, "MAX_IMAGE_SIZE_BYTES", 10)

    headers = await _admin_headers(client, db_session)
    release_id, edition_id = await _create_release_and_edition(client, headers)

    resp = await client.post(
        f"{BASE}/releases/{release_id}/editions/{edition_id}/images",
        data={"image_type": "front_cover"},
        files={"file": ("cover.jpg", FAKE_JPEG_BYTES, "image/jpeg")},
        headers=headers,
    )
    assert resp.status_code == 413


async def test_upload_image_on_unknown_edition_returns_404(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    release_id = await _create_release(client, headers)

    resp = await client.post(
        f"{BASE}/releases/{release_id}/editions/999/images",
        data={"image_type": "front_cover"},
        files={"file": ("cover.jpg", FAKE_JPEG_BYTES, "image/jpeg")},
        headers=headers,
    )
    assert resp.status_code == 404


# --- Image: borrado ------------------------------------------------------------------


async def test_delete_image_requires_admin(client: AsyncClient, db_session: AsyncSession):
    headers = await _admin_headers(client, db_session)
    release_id, edition_id = await _create_release_and_edition(client, headers)
    uploaded = await client.post(
        f"{BASE}/releases/{release_id}/editions/{edition_id}/images",
        data={"image_type": "front_cover"},
        files={"file": ("cover.jpg", FAKE_JPEG_BYTES, "image/jpeg")},
        headers=headers,
    )
    image_id = uploaded.json()["id"]

    resp = await client.delete(
        f"{BASE}/releases/{release_id}/editions/{edition_id}/images/{image_id}"
    )
    assert resp.status_code == 401


async def test_delete_unknown_image_returns_404(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    release_id, edition_id = await _create_release_and_edition(client, headers)

    resp = await client.delete(
        f"{BASE}/releases/{release_id}/editions/{edition_id}/images/999", headers=headers
    )
    assert resp.status_code == 404


async def test_admin_can_delete_image(client: AsyncClient, db_session: AsyncSession):
    headers = await _admin_headers(client, db_session)
    release_id, edition_id = await _create_release_and_edition(client, headers)
    uploaded = await client.post(
        f"{BASE}/releases/{release_id}/editions/{edition_id}/images",
        data={"image_type": "front_cover"},
        files={"file": ("cover.jpg", FAKE_JPEG_BYTES, "image/jpeg")},
        headers=headers,
    )
    image_id = uploaded.json()["id"]

    resp = await client.delete(
        f"{BASE}/releases/{release_id}/editions/{edition_id}/images/{image_id}",
        headers=headers,
    )
    assert resp.status_code == 204

    release = (await client.get(f"{BASE}/releases/{release_id}")).json()
    assert release["editions"][0]["images"] == []


async def _upload_image(
    client: AsyncClient, release_id: int, edition_id: int, headers: dict
) -> int:
    """Helper: sube una imagen 'other' minima y devuelve su id."""
    tiny_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
        b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
        b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    resp = await client.post(
        f"{BASE}/releases/{release_id}/editions/{edition_id}/images",
        files={"file": ("img.png", tiny_png, "image/png")},
        data={"image_type": "other"},
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def test_new_images_get_consecutive_positions(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    release_id, edition_id = await _create_release_and_edition(client, headers)

    id1 = await _upload_image(client, release_id, edition_id, headers)
    id2 = await _upload_image(client, release_id, edition_id, headers)
    id3 = await _upload_image(client, release_id, edition_id, headers)

    release = (await client.get(f"{BASE}/releases/{release_id}")).json()
    images = release["editions"][0]["images"]
    assert [img["id"] for img in images] == [id1, id2, id3]
    assert [img["position"] for img in images] == [1, 2, 3]


async def test_move_image_up(client: AsyncClient, db_session: AsyncSession):
    headers = await _admin_headers(client, db_session)
    release_id, edition_id = await _create_release_and_edition(client, headers)

    id1 = await _upload_image(client, release_id, edition_id, headers)
    id2 = await _upload_image(client, release_id, edition_id, headers)

    resp = await client.patch(
        f"{BASE}/releases/{release_id}/editions/{edition_id}/images/{id2}/position",
        json={"direction": "up"},
        headers=headers,
    )
    assert resp.status_code == 200
    images = resp.json()
    # id2 ahora es la primera
    assert images[0]["id"] == id2
    assert images[1]["id"] == id1


async def test_move_image_down(client: AsyncClient, db_session: AsyncSession):
    headers = await _admin_headers(client, db_session)
    release_id, edition_id = await _create_release_and_edition(client, headers)

    id1 = await _upload_image(client, release_id, edition_id, headers)
    id2 = await _upload_image(client, release_id, edition_id, headers)

    resp = await client.patch(
        f"{BASE}/releases/{release_id}/editions/{edition_id}/images/{id1}/position",
        json={"direction": "down"},
        headers=headers,
    )
    assert resp.status_code == 200
    images = resp.json()
    assert images[0]["id"] == id2
    assert images[1]["id"] == id1


async def test_move_image_at_first_position_returns_400(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    release_id, edition_id = await _create_release_and_edition(client, headers)
    image_id = await _upload_image(client, release_id, edition_id, headers)

    resp = await client.patch(
        f"{BASE}/releases/{release_id}/editions/{edition_id}/images/{image_id}/position",
        json={"direction": "up"},
        headers=headers,
    )
    assert resp.status_code == 400


async def test_move_image_at_last_position_returns_400(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    release_id, edition_id = await _create_release_and_edition(client, headers)
    image_id = await _upload_image(client, release_id, edition_id, headers)

    resp = await client.patch(
        f"{BASE}/releases/{release_id}/editions/{edition_id}/images/{image_id}/position",
        json={"direction": "down"},
        headers=headers,
    )
    assert resp.status_code == 400


async def test_move_image_requires_admin(client: AsyncClient, db_session: AsyncSession):
    headers = await _admin_headers(client, db_session)
    release_id, edition_id = await _create_release_and_edition(client, headers)
    image_id = await _upload_image(client, release_id, edition_id, headers)

    resp = await client.patch(
        f"{BASE}/releases/{release_id}/editions/{edition_id}/images/{image_id}/position",
        json={"direction": "up"},
    )
    assert resp.status_code == 401


# --- Label (sellos discograficos) -------------------------------------------------


async def _create_label(client: AsyncClient, headers: dict, name: str = "Virgin") -> int:
    """Helper: crea un sello y devuelve su id."""
    resp = await client.post(f"{BASE}/labels", json={"name": name}, headers=headers)
    assert resp.status_code == 201
    return resp.json()["id"]


async def test_list_labels_is_public_and_starts_empty(client: AsyncClient):
    resp = await client.get(f"{BASE}/labels")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_create_label_requires_admin(client: AsyncClient):
    resp = await client.post(f"{BASE}/labels", json={"name": "Virgin"})
    assert resp.status_code == 401


async def test_admin_can_create_and_list_label(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    resp = await client.post(
        f"{BASE}/labels", json={"name": "Virgin", "notes": "Sello de Branson"}, headers=headers
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "Virgin"
    assert resp.json()["notes"] == "Sello de Branson"

    listed = await client.get(f"{BASE}/labels")
    assert [lab["name"] for lab in listed.json()] == ["Virgin"]


async def test_duplicate_label_name_is_rejected_case_insensitively(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    await _create_label(client, headers, "Virgin")

    # Misma grafia y distinta capitalizacion: ambas deben chocar (409).
    for name in ("Virgin", "virgin", "VIRGIN"):
        resp = await client.post(f"{BASE}/labels", json={"name": name}, headers=headers)
        assert resp.status_code == 409, f"'{name}' deberia colisionar"


async def test_labels_can_be_filtered_by_name(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    await _create_label(client, headers, "Virgin")
    await _create_label(client, headers, "Mercury")

    resp = await client.get(f"{BASE}/labels", params={"q": "merc"})
    assert [lab["name"] for lab in resp.json()] == ["Mercury"]


async def test_admin_can_rename_label(client: AsyncClient, db_session: AsyncSession):
    headers = await _admin_headers(client, db_session)
    label_id = await _create_label(client, headers, "Virgin")

    resp = await client.patch(
        f"{BASE}/labels/{label_id}", json={"name": "Virgin Records"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Virgin Records"


async def test_update_unknown_label_returns_404(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    resp = await client.patch(f"{BASE}/labels/999", json={"name": "X"}, headers=headers)
    assert resp.status_code == 404


async def test_edition_carries_its_label_nested(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    label_id = await _create_label(client, headers, "Virgin")
    release_id = await _create_release(client, headers)

    resp = await client.post(
        f"{BASE}/releases/{release_id}/editions",
        json={**UK_1973_EDITION, "label_id": label_id},
        headers=headers,
    )
    assert resp.status_code == 201
    # El sello viaja como objeto anidado, no como cadena.
    label = resp.json()["label"]
    assert label["id"] == label_id
    assert label["name"] == "Virgin"
    assert label["notes"] is None
    assert label["edition_count"] == 0  # 0 porque viene del ORM sin el count calculado


async def test_edition_without_label_has_null(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    release_id, _ = await _create_release_and_edition(client, headers)

    release = (await client.get(f"{BASE}/releases/{release_id}")).json()
    assert release["editions"][0]["label"] is None


async def test_edition_with_unknown_label_id_returns_404(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    release_id = await _create_release(client, headers)

    resp = await client.post(
        f"{BASE}/releases/{release_id}/editions",
        json={**UK_1973_EDITION, "label_id": 999},
        headers=headers,
    )
    assert resp.status_code == 404


async def test_label_can_be_cleared_from_an_edition(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    label_id = await _create_label(client, headers, "Virgin")
    release_id = await _create_release(client, headers)
    created = await client.post(
        f"{BASE}/releases/{release_id}/editions",
        json={**UK_1973_EDITION, "label_id": label_id},
        headers=headers,
    )
    edition_id = created.json()["id"]

    resp = await client.patch(
        f"{BASE}/releases/{release_id}/editions/{edition_id}",
        json={"label_id": None},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["label"] is None


async def test_label_in_use_cannot_be_deleted(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    label_id = await _create_label(client, headers, "Virgin")
    release_id = await _create_release(client, headers)
    await client.post(
        f"{BASE}/releases/{release_id}/editions",
        json={**UK_1973_EDITION, "label_id": label_id},
        headers=headers,
    )

    resp = await client.delete(f"{BASE}/labels/{label_id}", headers=headers)
    assert resp.status_code == 409


async def test_unused_label_can_be_deleted(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    label_id = await _create_label(client, headers, "Sello Huerfano")

    resp = await client.delete(f"{BASE}/labels/{label_id}", headers=headers)
    assert resp.status_code == 204
    assert (await client.get(f"{BASE}/labels")).json() == []


async def test_label_edition_count_and_ordering(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(client, db_session)
    id_virgin = await _create_label(client, headers, "Virgin")
    id_emi = await _create_label(client, headers, "EMI")

    # Virgin tiene 2 ediciones, EMI tiene 1.
    for _ in range(2):
        r_id = await _create_release(client, headers)
        await client.post(
            f"{BASE}/releases/{r_id}/editions",
            json={**UK_1973_EDITION, "label_id": id_virgin},
            headers=headers,
        )
    r_id = await _create_release(client, headers)
    await client.post(
        f"{BASE}/releases/{r_id}/editions",
        json={**UK_1973_EDITION, "label_id": id_emi},
        headers=headers,
    )

    labels = (await client.get(f"{BASE}/labels")).json()
    assert labels[0]["id"] == id_virgin
    assert labels[0]["edition_count"] == 2
    assert labels[1]["id"] == id_emi
    assert labels[1]["edition_count"] == 1
