# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Qué es este proyecto

`ommadawn-api` es una **API REST** que cataloga la obra de **Mike Oldfield**: discografía
(álbumes de estudio, recopilatorios, singles, directos, bootlegs…), conciertos, libros y
otras secciones que se irán definiendo.

Está pensada para ser consumida por una **app móvil**: primero iOS y, en el futuro, Android.
Por eso el contrato de la API (REST + OpenAPI) es un ciudadano de primera clase y debe
mantenerse estable y bien versionado.

**Contexto de trabajo — importante:**
- Es un proyecto **de aprendizaje**, pero con la intención de **publicarse** y ser usado por
  gente real. Las decisiones deben ser sólidas, no solo "que funcione".
- **No se trabaja en modo vibe coding.** Prioriza que el usuario entienda *qué* se está
  haciendo y *por qué*. Explica las decisiones, no generes grandes cantidades de código de
  golpe sin contexto. Es preferible ir despacio y con criterio.

---

## Estado actual

> **Este archivo (y el `README`) son la "memoria" del repo: mantenlos actualizados
> según avanza el proyecto.** Si cambia el estado, las decisiones o el flujo de
> trabajo, actualiza aquí antes de dar una tarea por cerrada.

- **Repositorio**: `github.com/Rural-Code-Labs/ommadawn-api` (organización
  *Rural-Code-Labs*, no la cuenta personal). Carpeta local: `~/development/python/ommadawn-api`.
- **Nombre**: proyecto / carpeta / repo van con **guion** (`ommadawn-api`); el **paquete
  Python importable es `app`** (Python no admite guion en un `import`). No existe
  `ommadawn_api` en el código, solo aparecía en prosa.
- **Progreso**: **Fases 1–4 (bloque de auth) cerradas** ✅. **Fase 5 (Discografía) en
  marcha**: modelo `Release`/`Track` + endpoints de discos ya funcionando (ver sección
  "Discografía" más abajo). Quedan recopilatorios/singles/bootlegs por poblar con datos
  reales y, más adelante, "directos" como tipo nuevo. **Fase 6 (Colecciones de ediciones)
  cerrada** ✅: `Collection` agrupa ediciones de obras distintas bajo un nombre común
  (ver sección "Colecciones de ediciones" más abajo). **Las fases se gestionan desde el
  repo de la app** (`ommadawn-ios`); aquí solo se aplica lo que se pida en cada una.
- **Base de datos en desarrollo = PostgreSQL local en Docker** (`docker compose up -d`),
  el mismo motor que en producción. SQLite queda como alternativa rápida (línea comentada
  en `.env` / `.env.example`).
- **El esquema lo gestiona SIEMPRE Alembic** (dev y prod igual): la app **no** crea tablas
  al arrancar. `migrations/env.py` lee la `DATABASE_URL` de `Settings` (una sola fuente) e
  importa `Base.metadata`; **al añadir un módulo nuevo hay que importar sus `models` en
  `env.py`** o `autogenerate` no verá sus tablas.
- **Edición de perfil y roles en auth (ver sección "Perfil, avatar y roles" más abajo)**:
  `PATCH /auth/me` (perfil), avatar (`POST`/`DELETE /auth/me/avatar`, reutiliza
  `StorageBackend` de discografía) y un rol de **superadministrador** que gestiona quién es
  `admin` (`GET`/`PATCH /auth/users...`). Ninguno de los dos roles (`is_admin`,
  `is_super_admin`) tiene forma de auto-asignarse por API: **verificado con un test** que
  registrarse con esos campos en el body no escala privilegios (Pydantic los ignora).
- **Login/registro con Google (ver sección "Login con Google" más abajo)**: `POST
  /auth/google` recibe el ID token que obtiene el SDK `GoogleSignIn` en el cliente, lo
  verifica contra Google, y emite el MISMO `TokenPair` que `/auth/login` — la app no
  distingue después si la sesión vino de contraseña o de Google. Bloque de Google/contraseña
  completo (5.1–5.4): login/alta, vincular/desvincular, poner/quitar contraseña.
- **Verificación de email (ver sección "Verificación de email" más abajo, tarea 5.5)**: código
  numérico de 6 dígitos por email (no enlace), `POST /auth/verify-email/request` +
  `/confirm`, con límite de 5 intentos fallidos en ventana móvil de 24h. `EmailBackend`
  (`app/core/email.py`) es el mismo patrón puerto/adaptador que `StorageBackend`: solo
  `ConsoleEmailBackend` (log) por ahora, un proveedor real queda pendiente.
- **Recuperación de contraseña (ver sección propia más abajo, tarea 5.6)**: mismo patrón de
  código de 6 dígitos, pero sin autenticar (`POST /auth/password-reset/request` + `/confirm`),
  con dos matices de seguridad: no revela si una cuenta existe (ni por respuesta ni por límite
  de intentos) y, al acertar, loguea automáticamente (mismo `TokenPair` que `/login`).

---

## Stack

| Tecnología | Función |
|---|---|
| Python 3.12+ | Lenguaje |
| FastAPI | Framework web async, genera OpenAPI automáticamente |
| SQLAlchemy 2.0 (async) | ORM |
| Alembic | Migraciones de base de datos |
| Pydantic v2 + pydantic-settings | Schemas de API y configuración vía `.env` |
| argon2-cffi | Hashing de contraseñas (argon2id) |
| PyJWT | Access / refresh tokens |
| google-auth | Verifica el ID token de Google (`POST /auth/google`) |
| PostgreSQL (asyncpg) | Base de datos en **desarrollo** (Docker) y **producción** |
| SQLite (aiosqlite) | Alternativa rápida en local (sin instalar nada) |
| pytest + pytest-asyncio + httpx | Tests de integración |

El objetivo es que pasar de dev a producción sea **solo cambiar `DATABASE_URL`** en `.env`,
sin tocar código (mismo patrón que el proyecto hermano `../microservices/identity_service`,
que sirve de referencia de estilo).

---

## Decisiones de arquitectura

### Monolito modular (no microservicios)

Una única aplicación FastAPI dividida en **módulos por dominio**. La adaptabilidad se consigue
con **fronteras limpias entre módulos**, no separando en procesos:

- Cada módulo es autocontenido: tiene sus propios `models`, `schemas`, `services` y `router`.
- **Los módulos NO acceden a las tablas/models de otro módulo directamente.** Se comunican a
  través de la capa de `services` del otro módulo. Esta regla es la que permite, el día que
  haga falta, extraer un módulo a un servicio independiente con poca fricción.
- Lo compartido (config, engine de BD, `Base` ORM, seguridad, excepciones) vive en `core/`.

### Arquitectura en capas (dentro de cada módulo)

`router` → `service` → `model`, con `schema` como contrato de entrada/salida:

- **router**: define endpoints y dependencias (auth, sesión de BD). **Sin lógica de negocio.**
- **service**: toda la lógica de negocio y el acceso a datos. No conoce nada de HTTP.
- **model**: tablas SQLAlchemy.
- **schema**: modelos Pydantic para request/response. Nunca se exponen los models ORM
  directamente en la API.

### Versionado de API desde el día 1

Todos los endpoints cuelgan de `/api/v1/...`. La app móvil dependerá de este contrato, así que
un cambio incompatible implica una nueva versión (`/api/v2`), no romper la existente.

### Contrato OpenAPI apto para el cliente iOS

La app iOS genera su cliente HTTP con **swift-openapi-generator** a partir del `openapi.json`.
Ese generador **no soporta el tipo nulo** de JSON Schema (`{"type": "null"}`) que Pydantic v2
emite para los campos `T | None`, y **descarta el campo**. Por eso `app/core/openapi.py`
post-procesa el esquema: convierte "anulable" en "opcional" (quita la rama `null` y saca el
campo de `required`), de modo que salga como propiedad Swift opcional (`String?`). Es global:
**cualquier campo opcional futuro queda cubierto sin hacer nada**. No cambia las respuestas en
runtime, solo cómo se describe el contrato.

---

## Estructura del proyecto

> Estado real del repo. Los módulos marcados como *(futuro)* aún no existen; se
> crearán en su fase (patrón inspirado en `identity_service`, monolito modular).

```
ommadawn-api/
├── app/
│   ├── main.py                 # App FastAPI, lifespan, montaje de routers de cada módulo
│   ├── core/
│   │   ├── config.py           # Settings vía pydantic-settings (.env)
│   │   ├── database.py         # Engine async, sesión, Base ORM, dependencia get_session
│   │   ├── security.py         # argon2 (hashing) + PyJWT + refresh tokens
│   │   ├── exceptions.py       # HTTPExceptions reutilizables
│   │   ├── openapi.py          # Post-proceso del openapi.json (opcionales aptos para iOS)
│   │   ├── storage.py          # StorageBackend (Local ahora; GCS pendiente)
│   │   ├── email.py            # EmailBackend (Console ahora; SMTP/SendGrid pendiente)
│   │   └── country_codes.py    # Lista ISO 3166-1 alpha-2 + validate_country_code (compartido)
│   └── modules/
│       ├── auth/               # ✅ Fases 2-4 (bloque cerrado) + Google/verificación/reset (5.1-5.6)
│       │   ├── models.py       # User, RefreshToken, EmailVerificationAttempt, PasswordResetAttempt
│       │   ├── schemas.py      # Contratos Pydantic (request/response)
│       │   ├── service.py      # Lógica: registro, login, tokens, rotación, Google, email
│       │   ├── dependencies.py # get_current_user, require_admin (protegen endpoints)
│       │   └── router.py       # /api/v1/auth/*
│       ├── discography/        # 🚧 Fase 5 en marcha (Release -> Edition -> Track/Image)
│       │   ├── models.py       # Release, Edition (is_primary), Track, Image, Collection
│       │   ├── schemas.py      # Release/Edition/Track/Image: Create, Read, Update
│       │   ├── service.py      # CRUD anidado + demotes (primary, portada) + subida
│       │   └── router.py       # /api/v1/discography/* (leer: público; escribir: admin)
│       └── concerts/           # Fase 9 (futuro)
├── migrations/                 # Alembic: env.py (async) + versions/
├── tests/                      # Tests de integración por módulo (conftest.py, test_auth.py)
├── docker-compose.yml          # PostgreSQL local para desarrollo
├── alembic.ini
├── .env.example
└── pyproject.toml
```

---

## Comandos

```bash
# Entorno e instalación
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
# NOTA: el .venv guarda rutas absolutas. Si mueves/renombras la carpeta del
# proyecto, el venv queda roto -> recréalo (rm -rf .venv && ...) y reinstala.

# Configuración
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(64))"   # generar SECRET_KEY

# Base de datos local (PostgreSQL en Docker)
docker compose up -d                            # levantar Postgres (localhost:5432)
docker compose down                             # parar (conserva datos)
docker compose down -v                          # parar y BORRAR datos (empezar de cero)

# Arrancar el servidor (docs interactivas en http://localhost:8000/docs)
uvicorn app.main:app --reload

# Tests
pytest tests/ -v
pytest tests/test_auth.py::test_login -v        # un solo test

# Migraciones (Alembic)
alembic revision --autogenerate -m "descripcion"
alembic upgrade head
alembic history
```

El esquema lo gestiona **siempre Alembic**, igual en desarrollo que en producción: la app
no crea tablas al arrancar. Tras tocar un modelo: `alembic revision --autogenerate` y luego
`alembic upgrade head`. En desarrollo se usa un PostgreSQL local vía `docker compose`.

---

## Perfil, avatar y roles (auth)

Ampliación sobre el bloque de auth ya cerrado (Fases 1–4): editar el propio perfil, subir un
avatar, y un rol de **superadministrador** que decide quién es `admin`.

- **`PATCH /auth/me`** edita `full_name`, `country`, `city`, `birth_date`, `theme_preference`.
  El campo `country` acepta **códigos ISO 3166-1 alpha-2** (ej. `"ES"`, `"GB"`, `"US"`):
  `validate_country_code` (en `app/core/country_codes.py`) normaliza a mayúsculas, remapea
  alias habituales (`"UK"` → `"GB"`, `"USA"` → `"US"`) y devuelve 422 si el código no existe.
  El OpenAPI refleja el contrato con `minLength: 2`, `maxLength: 2` y `pattern: "^[A-Z]{2}$"`,
  lo que permite que swift-openapi-generator genere el tipo correcto en el cliente iOS.
  — un PATCH real (`model_dump(exclude_unset=True)`, mismo patrón que `ReleaseUpdate`).
  Deliberadamente **no** toca `username`, `email`, contraseña, avatar ni roles: cada uno tiene
  sus propias reglas (unicidad, verificación, permisos) y se aborda aparte si hace falta.
- **`theme_preference`** (`ThemePreference`: `light` / `dark` / `system`, por defecto
  `system`): preferencia de apariencia de la app. Mismo patrón enum-como-texto que
  `ReleaseType`/`ImageType`/`EditionFormat`, pero es el **primer campo así en `auth`**. A
  diferencia de `country`/`city`/`birth_date`, la columna **no es nullable**: es un ajuste que
  siempre tiene un valor concreto, no un dato "desconocido" por rellenar. Por eso en
  `UserUpdate` NO es `ThemePreference | None`: tiene un valor por defecto (no `None`), lo que
  permite que `exclude_unset` lo ignore si se omite en el `PATCH`, y que un `null` explícito
  en el body dé **422** (Pydantic lo rechaza por tipo) en vez de reventar en el `commit` con
  un `IntegrityError`.
- **Avatar** (`POST`/`DELETE /auth/me/avatar`): reutiliza `StorageBackend` y
  `validate_image_upload` de discografía (ver más abajo el porqué de esa extracción). A
  diferencia de `Image` en discografía (varias imágenes por edición, con `image_type`), aquí
  basta un simple `User.avatar_url` nullable: un usuario tiene como mucho un avatar. Subir uno
  nuevo sustituye al anterior (fichero incluido); `DELETE` es idempotente.
- **`is_super_admin`**: campo independiente de `is_admin`. `require_admin` (la dependencia
  que ya protegía discografía) ahora acepta `is_admin` **o** `is_super_admin` — un superadmin
  tiene automáticamente los poderes de admin sin necesitar las dos banderas a la vez. Una
  nueva dependencia `require_superadmin` protege exclusivamente `GET /auth/users` (listar,
  para elegir a quién promover) y `PATCH /auth/users/{id}` (cambia el `is_admin` de otro
  usuario). **No** permite tocar `is_super_admin` de nadie: nombrar a un superadmin sigue
  siendo solo por BD, igual que hoy con `is_admin`.
- **Validación de imágenes compartida**: al construir el avatar se detectó que iba a duplicar
  la misma lógica (content-type permitido, tamaño máximo) que ya vivía en
  `discography/service.py`. Se extrajo a `app/core/storage.py`
  (`validate_image_upload`, `ALLOWED_IMAGE_CONTENT_TYPES`, `MAX_IMAGE_SIZE_BYTES`): cualquier
  módulo que suba imágenes se comporta igual, sin repetir la regla.
- **Gotcha de migraciones a recordar**: añadir una columna `NOT NULL` a una tabla que **ya
  tiene filas** (como `users` aquí) necesita `server_default` en la migración — a diferencia
  de cuando `is_admin` se creó en la migración inicial, con la tabla recién creada y vacía.
  Sin ese `server_default`, Postgres no sabe qué poner en las filas existentes y la migración
  falla.

---

## Login con Google

`POST /auth/google` (tarea 5.1.1 del backlog): la app iOS (SDK `GoogleSignIn-iOS`) obtiene un
ID token de Google y se lo manda a la API; la API lo verifica y emite el MISMO `TokenPair`
que `POST /auth/login` — la app no distingue después si la sesión vino de contraseña o de
Google.

- **`google_web_client_id`** (`Settings`, obligatorio, sin valor por defecto — mismo criterio
  que `secret_key`): es el "Web Client ID" del proyecto en Google Cloud Console (*Rural Code
  Labs*), y es la **audiencia** (`aud`) contra la que se valida el ID token. La app iOS
  configura el SDK con `serverClientID` = este mismo valor (no el "iOS Client ID", que solo
  usa el SDK para el flujo nativo y la API nunca ve). Un único Web Client ID sirve de audiencia
  común para cualquier plataforma cliente futura (Android incluido). No es un secreto (va
  incrustado en apps públicas), pero se configura por `.env` igual que el resto: cambiar de
  proyecto de Google no debe tocar código.
- **`app/core/security.py::verify_google_id_token`**: verifica firma, caducidad, emisor y
  audiencia llamando a Google (`google.oauth2.id_token.verify_oauth2_token`), usando el paquete
  `google-auth[requests]` (el extra `[requests]` hace falta: `google.auth.transport.requests`
  importa la librería `requests`, que NO es una dependencia transitiva de `google-auth` a
  secas). Vive junto al resto de verificación de tokens en `security.py` porque, igual que
  `decode_access_token`, es pura VERIFICACIÓN — no toca BD ni sabe de HTTP — aunque a
  diferencia de esa, sí hace una petición de red (a los certificados públicos de Google).
- **`User.google_id`** (nullable, unique, indexado): el `sub` del ID token (identificador
  estable de la cuenta de Google), NO el email — el email puede cambiar en Google, el `sub`
  no. La mayoría de usuarios (login por contraseña) lo tienen a `None`.
- **`UserRead.has_google`** / **`UserRead.has_password`**: booleanos calculados
  (`google_id is not None` / `hashed_password is not None`), NO columnas en BD — son
  `@property` en el modelo `User` que `from_attributes=True` lee igual que un campo normal
  (mismo patrón que `Track.title`/`duration_seconds`/`credits` en discografía, que "aplanan"
  `Recording` hacia `Track`). Salen en `/register` y `/me` (los únicos endpoints que devuelven
  `UserRead`; `/login` y `/google` devuelven `TokenPair`, no el perfil); ninguno necesita
  migración porque no son columnas. `has_password` existe para que la app pueda
  ocultar el campo "contraseña actual" en el formulario de `POST /auth/me/password` cuando la
  cuenta es solo-Google, en vez de mostrarlo vacío con una nota.
- **Lógica en `service.google_login`, tres casos**:
  1. Ya existe un usuario con ese `google_id` → login normal (mismo flujo que `login_user`
     desde ahí en adelante, factorizado en el helper común `_issue_token_pair`).
  2. No existe por `google_id` pero SÍ por email → esa cuenta se creó por contraseña y no
     tiene Google vinculado. **Decisión explícita: no se auto-vincula ni se crea un
     duplicado.** Responde `409` con `{"detail": "email_conflict"}`.
  3. No existe ni por `google_id` ni por email → alta nueva, vinculada desde el primer
     momento; `full_name`/`avatar_url` se rellenan con `name`/`picture` del token si vienen
     (no es bloqueante si no vienen). El `username` NO lo da Google ni se deriva del email:
     se genera al azar (`_generate_random_username`, `"user-" + 6 dígitos`,
     `secrets.randbelow`), reintentando con otro número si ya existe. La persona no lo elige
     en este paso — ver "Username provisional" más abajo.
- **`email_conflict` es un CÓDIGO, no una frase** — misma excepción al resto de
  `app/core/exceptions.py`, donde `detail` siempre es texto humano en español (comparte
  criterio con `username_already_set`, ver abajo). Decisión explícita del usuario: la app
  necesita distinguir este 409 de cualquier otro por el propio valor del campo, sin parsear
  un mensaje.
- **`email_verified` del token se exige `True`**: si Google no ha verificado el email (caso
  raro, pero posible con algunos proveedores federados detrás de Google), se trata igual que
  un token inválido (`401`), no se confía en un email sin verificar para vincular/crear cuenta.
- **Tests** (`tests/test_auth.py`): `verify_google_id_token` hace una petición de red real, así
  que en los tests se sustituye por un doble (`monkeypatch.setattr(service,
  "verify_google_id_token", fake)`) que devuelve un payload controlado o lanza el error que se
  quiera simular — mismo patrón que `MAX_IMAGE_SIZE_BYTES` en los tests de avatar/imágenes.
  Para probar el reintento por colisión de username se mockea `service.secrets.randbelow` con
  una secuencia fija de valores.
- **Vinculación/desvinculación desde perfil** (`POST`/`DELETE /auth/me/google`, tarea 5.3 del
  backlog): ver sección propia "Vincular/desvincular Google desde el perfil" más abajo.

### Vincular/desvincular Google desde el perfil

`POST`/`DELETE /auth/me/google` operan sobre una sesión YA AUTENTICADA (por contraseña o por
Google) — a diferencia de `POST /auth/google`, esto no es un login: el usuario viene de
`get_current_user`, no del token.

- **`service.link_google_account`**: verifica el ID token igual que `google_login` (firma,
  audiencia, `email_verified`), pero NO busca por email ni da de alta a nadie — el usuario ya
  existe (`current_user`). Solo comprueba que el `google_id` del token no pertenezca YA a otra
  fila (`User.google_id == google_id AND User.id != current_user.id`) antes de guardarlo. No
  toca `email` ni `username`: vincular es estrictamente añadir el `google_id`.
  - **`google_already_linked_exception`** (`409`, `detail: "google_already_linked"`, mismo
    criterio de código corto que `email_conflict`/`username_already_set`): dos usuarios no
    pueden compartir la misma cuenta de Google. Si el `google_id` ya es el del propio
    `current_user` (re-vincular la misma cuenta), no hay conflicto — es un no-op.
- **`service.unlink_google_account`**: pone `google_id=None`. Bloqueado
  (`google_only_access_exception`, `409`, `detail: "google_only_access"`) si
  `hashed_password is None` — esa cuenta se creó puramente por Google (ver `google_login` caso
  3) y desvincular la dejaría sin NINGUNA forma de volver a entrar. **No pide reautenticarse
  con contraseña antes** (decisión explícita del backlog): se confía en que la sesión Bearer ya
  demuestra que es el dueño de la cuenta, mismo criterio que el resto de `PATCH`/`DELETE
  /me...` (perfil, avatar). Si el usuario no tenía Google vinculado, es idempotente (mismo
  criterio que `delete_avatar`): no falla, simplemente no cambia nada.
- **Tests**: reutilizan `_mock_google_token`/`_google_payload` ya existentes de
  `google_login`. El caso de conflicto se prueba vinculando la misma cuenta de Google (mismo
  `sub` de `_google_payload`) desde DOS usuarios distintos.

### Cambiar contraseña (o ponerla por primera vez)

`POST /auth/me/password` cubre DOS casos con la misma lógica en `service.change_password`, sin
un flag explícito en el body — se decide según el estado real de la cuenta:

- **La cuenta ya tiene contraseña** (`hashed_password` no es `None`): `current_password` es
  obligatoria y se verifica con `verify_password` — el MISMO mecanismo que usa `login_user`
  para comprobar credenciales. Si no coincide (o no se envía), `invalid_current_password_exception`
  (`401`).
- **La cuenta se creó puramente por Google** (`hashed_password is None`, ver `google_login`
  caso 3): no hay nada que verificar. `current_password` se ignora si llega — el `service` ni
  la mira. Se hashea `new_password` y se guarda directamente. Es la forma de que esa cuenta
  deje de depender solo de Google: a partir de ahí también puede hacer `login_user` normal.
- **`invalid_current_password_exception` NO reutiliza `credentials_exception`** pese a ser
  también un `401`: si compartieran el mismo objeto (mismo status, mismo `detail`, misma
  cabecera `WWW-Authenticate`), la app no podría distinguir "contraseña actual incorrecta" de
  "sesión caducada" (`get_current_user` también lanza `credentials_exception` en `401` si el
  Bearer no es válido). Con un `detail` propio en PROSA (no un código corto: aquí no hace falta
  — es el único motivo de `401` posible una vez pasado el Bearer, a diferencia de
  `email_conflict`/`username_already_set`/`google_already_linked`, donde el mismo status podía
  significar varias cosas) la distinción es automática.
- **`PasswordUpdate.current_password` es `str | None`** (no `Field(min_length=...)` como
  `new_password`): la validación de si hace falta o no depende del ESTADO EN BD
  (`hashed_password`), no de la forma del body, así que Pydantic no puede decidirlo — lo valida
  el `service`.
- **Sin migración**: no toca el modelo, solo reescribe `User.hashed_password` (columna ya
  existente, nullable desde el principio — pensada para OAuth desde antes de que existiera
  Google login).
- Respuesta `204 No Content`: no hay nada nuevo que enseñar (a diferencia de
  `update_profile`/`link_google_account`, que devuelven `UserRead`).

`DELETE /auth/me/password` (tarea 5.4 del backlog) es el ESPEJO exacto de `DELETE
/auth/me/google`, con los roles de Google/contraseña invertidos:

- **`service.remove_password`**: bloqueado (`password_only_access_exception`, `409`,
  `detail: "password_only_access"`) si `google_id is None` — sin Google vinculado, quitar la
  contraseña dejaría la cuenta sin NINGUNA forma de entrar. Si hay Google vinculado, pone
  `hashed_password=None` directamente. Misma estructura que `unlink_google_account`
  (`google_only_access_exception` si `hashed_password is None`), con la condición cambiada.
- **No pide `current_password` para quitarla** ni reautenticación previa — mismo criterio que
  el resto de `PATCH`/`DELETE /me...`: se confía en que la sesión Bearer ya demuestra quién es
  el dueño de la cuenta.
- **No es idempotente** como `delete_avatar`/`unlink_google_account` sin Google vinculado: si
  la cuenta YA no tenía contraseña, seguiría sin Google → seguiría dando `409`. La única forma
  de "no-op" sería no tener Google Y no tener contraseña, estado que no puede existir (algún
  método de acceso siempre queda).
- Sin migración: mismo motivo que `change_password`, reescribe una columna ya existente.

### Username provisional (altas por Google)

Una cuenta creada por `POST /auth/google` no elige su `username` en el momento del alta (a
diferencia del registro por contraseña, donde se pide explícitamente): se genera uno al azar
y `User.username_is_default=True` marca que es provisional. `PATCH /auth/me` deja cambiarlo
**una única vez**, sin límite de tiempo, a partir de ese momento queda fijo como el de
cualquier otra cuenta.

- **`User.username_is_default`** (`Boolean`, NOT NULL, default `False`): `True` solo para
  cuentas de Google recién creadas; `False` para todo lo demás (registro por contraseña
  desde el alta, o una cuenta de Google que ya gastó su único cambio). Migración
  `f0ee802141d7` — necesitó `server_default='false'` porque `users` ya tenía filas (mismo
  gotcha que `is_admin`/`is_super_admin` en su día, ver "Perfil, avatar y roles" arriba).
- **`UserUpdate.username`**: NO es `str | None` pese a ser opcional en el PATCH — mismo
  patrón que `theme_preference` (la columna no es nullable, un username no se "vacía"): un
  valor por defecto (`""`, nunca validado porque Pydantic no valida defaults salvo
  `validate_default=True`, y `exclude_unset` lo descarta si se omite) hace que un `null`
  explícito en el body dé **422** en vez de intentar dejar el campo vacío.
- **`service.update_profile` trata `username` aparte** del resto de campos (no es un
  `setattr` genérico como `full_name`/`country`/etc.):
  1. Si `username_is_default` es `False` → **rechaza** con `409` y
     `{"detail": "username_already_set"}` (código corto, mismo criterio que `email_conflict`:
     la app necesita distinguirlo sin parsear texto). No se ignora en silencio ni da un 422
     genérico.
  2. Si es `True` → valida unicidad (mismo `username_taken_exception` que en el registro, con
     `detail` en prosa — este SÍ es el mensaje humano habitual, no un código), aplica el
     cambio y pone `username_is_default=False`.
- **No hay ventana de tiempo**: el cambio único no caduca; solo se consume al USARSE.

---

## Verificación de email

`POST /auth/verify-email/request` y `POST /auth/verify-email/confirm` (tarea 5.5 del
backlog): verificación de email por **código numérico de 6 dígitos**, no por enlace — la API
no sirve ninguna página HTML, todo queda en JSON + la app.

- **`User.email_verified`** (`Boolean`, NOT NULL, default `False`): `False` desde el alta para
  registro por contraseña; `True` desde el alta para cuentas creadas por `google_login`
  (reutiliza la comprobación de `email_verified: true` del ID token que ya existía —
  `google_login` nunca da de alta a nadie sin ella). Migración `8cbfa5b0ea40` — necesitó
  `server_default='false'` (mismo gotcha de siempre) y un **backfill de datos**: las cuentas
  que YA tenían `google_id` al aplicar la migración se marcaron `email_verified=true`, porque
  su email ya estaba verificado por Google desde que se crearon/vincularon — no tendría
  sentido pedirles reverificar algo ya comprobado.
- **`User.email_verification_code_hash` / `_expires_at`** (ambos nullable): el código
  PENDIENTE, asociado directamente al usuario (no una tabla de códigos con histórico). Pedir
  un código nuevo **sobrescribe** estas dos columnas — así se invalida automáticamente
  cualquier código anterior, sin necesitar borrar nada aparte. Se guarda el HASH
  (`security.hash_verification_code`, SHA-256), no el código en claro; a diferencia del hash
  de un refresh token, aquí el hash NO protege de fuerza bruta offline (6 dígitos son solo un
  millón de combinaciones, recorrerlas todas es instantáneo) — se hashea igualmente por
  consistencia con el resto del repo y para que una fuga de la fila no exponga directamente un
  código aún válido.
- **`EmailVerificationAttempt`** (tabla nueva, solo intentos FALLIDOS): cada fila es un intento
  que no coincidió (o había caducado). El límite ("máximo 5 intentos fallidos en una ventana
  MÓVIL de 24h") se calcula con una consulta directa
  (`COUNT(*) WHERE user_id = ... AND created_at > ahora - 24h`) en vez de un contador con
  reseteo manual — así la ventana es de verdad móvil (una fila de hace 25h deja de contar sola,
  sin tener que decidir cuándo "reiniciar" nada). El límite es **por usuario, no por código**:
  pedir un código nuevo NO borra estas filas (`request_email_verification` no las toca), tal y
  como pide el backlog explícitamente. Un ACIERTO sí las borra todas (`DELETE ... WHERE
  user_id = ...` en `confirm_email_verification`): verificado el email, no tiene sentido seguir
  arrastrando intentos fallidos previos.
- **Orden de comprobaciones en `confirm_email_verification`**: el límite de intentos se mira
  **antes** que el código en sí — un usuario bloqueado por el límite recibe `429` sin que el
  `service` llegue a comparar hashes, así la respuesta no puede filtrar por temporización si el
  código que mandó (bloqueado) era correcto o no.
- **Dos excepciones nuevas, mismo criterio de código corto que `email_conflict`/
  `username_already_set`**: `too_many_verification_attempts_exception` (`429`,
  `detail: "too_many_attempts"`) y `invalid_verification_code_exception` (`401`,
  `detail: "invalid_code"` — un único error genérico para "no coincide", "caducado" o "no
  había ninguno pendiente": la app no necesita distinguir cuál de los tres fue).
- **`POST /verify-email/request` es un no-op (204) si `email_verified` ya es `True`**: decisión
  tomada porque la app no necesita distinguirlo de un 204 normal (no debería llamar a este
  endpoint en ese estado). El commit del código nuevo ocurre **después** de que
  `EmailBackend.send` tenga éxito, no antes: si el envío falla, no queda en BD un código
  "fantasma" que el usuario nunca recibió.
- **`app/core/email.py` — puerto `EmailBackend`**, mismo patrón que `StorageBackend` en
  `storage.py`: `ConsoleEmailBackend` (desarrollo, escribe el correo en el log) es la única
  implementación por ahora; un backend real (SMTP/SendGrid) queda **pendiente de implementar**
  hasta tener una cuenta/proyecto real contra el que probarlo (mismo criterio que
  `GCSStorageBackend`: código no verificable no se escribe a ciegas). Se elige por
  `Settings.email_backend` (`.env`), igual que `storage_backend` elige el backend de ficheros.
- **Gotcha real que se dio la primera vez**: `ConsoleEmailBackend.send` usa
  `logger.info(...)` sobre `logging.getLogger("app.email")`, pero sin configurar el logging de
  la app ese `INFO` no llega a ningún sitio — el logger raíz de Python, sin config explícita,
  solo emite `WARNING` para arriba y no tiene ningún *handler* que escriba a la terminal (se ve
  la petición HTTP porque esa la loguea uvicorn con su propia config, pero no el cuerpo del
  email). Arreglado con `logging.basicConfig(level=logging.INFO, force=True)` en
  `app/main.py`, al principio del fichero (antes de crear la `app`). `force=True` es
  necesario para que se aplique pase lo que pase se haya importado ya antes (p. ej. bajo
  `uvicorn --reload`), en vez de depender de que nadie más haya llamado a `basicConfig` primero
  (esa función "no hace nada si el logger raíz ya tiene *handlers*", salvo `force=True`).
- **`_is_past`** (antes `_is_expired`, en `service.py`): se generalizó para aceptar un
  `datetime` cualquiera en vez de solo una fila de `RefreshToken`, y así reutilizar la misma
  normalización UTC (SQLite naive vs. Postgres aware) al comprobar la caducidad del código de
  verificación.
- **Tests** (`tests/test_auth.py`): `conftest.py` gana un backend de email de test
  (`RecordingEmailBackend`, fixture `email_backend`) que no envía nada de verdad, solo guarda
  el cuerpo del correo — los tests sacan el código de ahí con una regex, igual que la app real
  lo sacaría del correo recibido. Mismo patrón que `LocalStorageBackend` apuntando a una
  carpeta temporal en los tests de avatar/imágenes.

---

## Recuperación de contraseña

`POST /auth/password-reset/request` + `/confirm` (tarea 5.6 del backlog): mismo patrón que
verificación de email (código de 6 dígitos, no enlace), pero **sin autenticar** — es justo el
caso de estar deslogueado — con dos matices de seguridad propios de un endpoint público:
**no debe poder averiguarse por la respuesta (ni por límite de intentos) qué emails/usernames
están registrados.**

- **Constantes compartidas, renombradas**: `VERIFICATION_CODE_EXPIRES_AFTER` (2h),
  `VERIFICATION_ATTEMPTS_WINDOW` (24h) y `VERIFICATION_MAX_ATTEMPTS` (5) — antes tenían el
  prefijo `EMAIL_VERIFICATION_`, generalizadas al añadir este flujo porque comparten política
  exacta con la verificación de email; duplicar los números arriesgaba que divergieran sin
  querer con el tiempo. Igual con la excepción `too_many_verification_attempts_exception` →
  **`too_many_code_attempts_exception`**, ahora compartida por los dos `/confirm`.
- **`User.password_reset_code_hash` / `_expires_at`**: mismo diseño que el par de verificación
  de email (hash + caducidad, sobrescribible), pero en sus PROPIAS columnas — son conceptos
  distintos (verificar el email vs. demostrar que sigues siendo el dueño de la cuenta) y pueden
  tener un código pendiente cada uno a la vez sin pisarse. Migración `5f145a02d004`, sin
  `server_default` (todo nullable, no hace falta backfill).
- **`PasswordResetAttempt` NO tiene FK a `users`** — a diferencia de `EmailVerificationAttempt`.
  Se cuenta por `identifier` (el `username_or_email` tal cual se envió), no por `user_id`:
  el límite de intentos tiene que aplicar TAMBIÉN cuando la cuenta no existe, y no puede haber
  un `user_id` para una cuenta que no existe. Es la pieza clave que permite que "5 intentos
  fallidos" bloquee igual a un atacante probando contra un email real que contra uno inventado.
- **`invalid_password_reset_exception`**: excepción PROPIA (no reutiliza
  `invalid_verification_code_exception` directamente, aunque comparten el mismo `detail:
  "invalid_code"`) porque aquí fusiona a propósito "cuenta no existe" con "código incorrecto/
  caducado" — algo que no aplica a la verificación de email (ahí el usuario ya está
  autenticado, la cuenta siempre existe). `service.confirm_password_reset` calcula el hash del
  código enviado **siempre**, exista o no la cuenta (`hash_verification_code(data.code)` antes
  de mirar si `user is None`), para no delatar la diferencia por timing tampoco ahí.
- **`request_password_reset` hace el mismo "trabajo de mentira"** (generar y hashear un código
  que se descarta) cuando la cuenta no existe, por el mismo motivo. Mitigación PARCIAL y
  documentada como tal en el código: con un backend de email real (I/O de red), la rama que sí
  envía seguiría siendo más lenta — resolver eso del todo es un problema mayor, fuera de
  alcance aquí.
- **Éxito → login automático**: `confirm_password_reset` devuelve el mismo `TokenPair` que
  `login_user` (via el helper compartido `_issue_token_pair`), para que la app no tenga que
  pedir un segundo login tras recuperar el acceso. Antes de emitir tokens comprueba
  `user.is_active` (mismo criterio que `login_user`): una cuenta desactivada SÍ puede cambiar
  su contraseña por este flujo (ya demostró ser su dueña con el código), pero no recibe sesión
  — evita que este endpoint sea una vía para saltarse una desactivación/baneo.
- **Sin `AuthMiddleware` que excluir**: la API no tiene ningún middleware global de
  autenticación (`grep add_middleware` en `app/` no devuelve nada) — la protección es siempre
  por endpoint, vía `Depends(get_current_user)` en cada ruta. Estos dos endpoints simplemente
  no llevan esa dependencia, igual que `/register`, `/login` o `/google`. Del lado de la app
  (`AuthMiddleware.swift`) sí hay que añadirlos a la exclusión — eso es responsabilidad del
  repo de la app, no de este.

---

## Discografía (Fase 5)

Discos, recopilatorios, singles, bootlegs y directos oficiales se modelan bajo un único
concepto: **`Release`** (la obra, p. ej. "Tubular Bells"), con un campo `release_type` que
los distingue (`studio` / `compilation` / `single` / `bootleg` / `live`). `bootleg` es para
grabaciones no oficiales (fans); `live` para directos publicados por el sello.

**Jerarquía de cuatro niveles:**

```
Release     (la obra abstracta: título, tipo, description)
  └── Edition   (publicación CONCRETA: país, sello, edition_name, nº catálogo,
                 fecha, formato, créditos, notas, is_primary)
        ├── Track   (aparición de una grabación en ESA edición:
        │             position, disc_number, side → Recording)
        │     └── Recording  (la grabación real: title, duration_seconds, credits
        │                     COMPARTIDA entre ediciones que incluyan el mismo tema)
        └── Image   (portada, contraportada... con position reordenable)
```

Se introdujo `Edition` porque un mismo disco puede tener varias publicaciones reales. Se
introdujo `Recording` separada de `Track` para poder compartir la misma grabación entre
varias ediciones (p. ej. "Tubular Bells Part One" en la edición original UK y en *Boxed*)
sin duplicar créditos.

Decisiones de diseño fijadas (para no repensarlas en cada fase futura):

- **`Release.description`** (opcional, `Text`, nullable): texto libre para la historia e
  información de la obra — contexto de grabación, curiosidades, relevancia… A diferencia de
  `Edition.credits`/`notes` (que son por publicación concreta), este texto describe la obra
  abstracta y no varía entre ediciones. Se crea/edita junto al resto de campos del `Release`
  vía `POST`/`PATCH /releases`.
- **Una tabla `releases` con `release_type`, no una tabla por tipo.** `studio` /
  `compilation` / `single` / `bootleg`, en vez de herencia con JOIN. Se añadirá una tabla de
  detalle solo si un tipo necesita de verdad un campo exclusivo — hoy no hay ninguno conocido.
- **`release_type` es texto validado por Python + `CHECK`, no un enum nativo de PostgreSQL.**
  El conjunto puede crecer si hace falta; añadir un valor a un `CHECK` es una migración más
  simple que la de un tipo nativo (`ALTER TYPE ... ADD VALUE`). La columna guarda el *valor*
  del enum (`"studio"`), no el nombre (`"STUDIO"`).
- **Los `CHECK` hay que pedirlos explícitamente: `create_constraint=True`.** Durante un tiempo
  estos cuatro campos se documentaron como "validados por Python + `CHECK`" pero el `CHECK`
  **no existía en la BD**: `Enum(native_enum=False)` de SQLAlchemy trae `create_constraint=False`
  por defecto desde la 1.4, así que solo validaba Python y un `UPDATE` a mano en `psql` podía
  colar cualquier cadena. Se corrigió en la migración `f6d9ebe87c0b`, que añade los cuatro
  (`ck_releases_release_type`, `ck_editions_format`, `ck_images_image_type`,
  `ck_users_theme_preference`). **Consecuencia a recordar**: añadir un valor nuevo a uno de
  estos enums ahora **sí requiere migración** (DROP + CREATE del `CHECK` con la lista nueva).
  Antes la migración salía vacía — de hecho al añadir `live` se generó una migración vacía que
  hubo que borrar, y ese fue el síntoma que destapó el problema.
- **Ojo con el ancho del `varchar`**: el enum se guarda con la anchura del valor más largo
  (`compilation` → `varchar(11)`, `system` → `varchar(6)`). Un valor nuevo más largo necesita
  además ensanchar la columna. Alembic lo detecta, así que no es silencioso, pero es un paso
  extra fácil de olvidar. También quedan anchos heredados: `country` sigue en `varchar(100)` en
  `users` y `editions` aunque hoy solo admita códigos ISO de 2 letras.
- **`Edition.is_primary`** marca qué edición mostrar por defecto (p. ej. la portada en una
  lista) cuando un `Release` tiene varias. Se garantiza "como mucho una principal por obra"
  con un **índice único parcial** (`uq_editions_release_primary`, `WHERE is_primary`) — no un
  enum nativo ni un booleano sin restricción. Al marcar una edición como principal, el
  `service` (`_demote_other_primary_editions`) desmarca automáticamente la anterior *antes* de
  guardar: el admin nunca choca con el índice en el uso normal, solo actúa de red de seguridad.
- **`Edition.format`** (`EditionFormat`, opcional): formato físico — `vinyl` / `cd` / `single`
  / `maxi_single` / `cd_single` / `cassette`. Mismo patrón que `release_type`/`image_type`
  (texto validado por Python + `CHECK`, no enum nativo). **Ojo al añadir un campo así**: si el
  `service` construye el modelo con kwargs explícitos (como `create_edition`, a diferencia de
  `update_edition` que usa `model_dump(exclude_unset=True)` + `setattr` genérico), hay que
  acordarse de pasar el campo nuevo a mano — se nos olvidó una vez y quedó cubierto por un test.
- **`Edition.country`** acepta **códigos ISO 3166-1 alpha-2** (ej. `"GB"`, `"JP"`), igual que
  `User.country`. El validador vive en `app/core/country_codes.py` y es compartido por ambos
  módulos. Normaliza a mayúsculas y remapea alias (`"UK"` → `"GB"`, `"USA"` → `"US"`); un
  código desconocido devuelve 422. Los datos previos (nombres completos de país) se migraron
  a NULL en la migración `cec3117a2e5d`.
- **`Edition.catalog_number`/`credits`/`notes`** (todos opcionales): la referencia del sello
  para esa edición concreta (`catalog_number`, acotado a 100 caracteres, como `label`) y dos
  campos de texto libre sin límite de longitud (`Text`, no `String(n)`) para créditos
  (músicos, producción...) y notas generales sobre la edición.
- **`Track` y `Recording` están separados** (relación N:M a través de `Track`): una `Recording`
  puede aparecer en varios `Track` de distintas ediciones. `Track` guarda `position`,
  `disc_number` (default 1) y `side` (nullable, solo vinilos: `"A"`, `"B"`…). Al crear una
  edición, cada tema del array acepta dos formas excluyentes: `title` (nueva `Recording`) o
  `recording_id` (reutilizar existente). La unicidad de posición se garantiza con dos índices
  parciales (uno cuando `side IS NULL`, otro cuando `side IS NOT NULL`) porque PostgreSQL trata
  NULL≠NULL en restricciones UNIQUE, lo que dejaría pasar duplicados con `side=NULL` si fuera
  un único índice. `GET /discography/recordings?q=...` permite buscar por título para localizar
  el `recording_id` antes de reutilizar; cada resultado incluye `usages` con la lista de
  ediciones donde aparece (`release_title`, `edition_name`, `release_date`). El service
  construye el DTO manualmente (`_build_recording_read`) cargando `Recording → tracks →
  edition → release` con `selectinload`. La FK `Track.recording_id` usa `ondelete=RESTRICT`
  para que borrar una `Recording` falle si sigue siendo referenciada — protección de datos.
- **Cadena vacía → null en campos de texto opcionales**: `edition_name` (y cualquier campo
  similar en el futuro) tiene un `field_validator(mode="before")` que convierte `""` a `None`.
  Motivo: swift-openapi-generator declara los campos opcionales como `String?`, y un `String?`
  en nil se omite del JSON en vez de enviarse como `null`. Para que el cliente iOS pueda
  *borrar* un campo, envía `""` — la API lo interpreta como "limpiar el valor". No hace falta
  tocar el esquema OpenAPI ni el post-proceso de `openapi.py`.
- **Leer el catálogo es público; crear/editar/borrar exige ser administrador**
  (`require_admin`, en `auth/dependencies.py`, reutilizable por futuros módulos de catálogo).
  No hay endpoint para promover a admin: se hace directamente en BD (o en los tests, vía sesión
  directa — ver `tests/conftest.py::db_session`).
- **Los temas se crean anidados** en el body de `POST .../editions` (`tracks: [...]`), no en un
  endpoint aparte: así es como se cura el catálogo en la práctica, una edición siempre trae su
  tracklist consigo. `POST /releases` en cambio NO lleva `tracks`: crea solo la obra (título +
  tipo); las ediciones se añaden después.

Endpoints actuales:

| Método | Ruta | Acceso |
|---|---|---|
| `GET` | `/api/v1/discography/labels` | Público (filtro `?q=` por nombre; orden: `edition_count DESC`, nombre ASC) |
| `POST` / `PATCH` / `DELETE` | `/api/v1/discography/labels[/{id}]` | Admin (409 en DELETE si en uso) |
| `GET` | `/api/v1/discography/recordings?q=` | Público (búsqueda por título; devuelve `usages` con release_title, edition_name, release_date) |
| `PATCH` | `/api/v1/discography/recordings/{id}` | Admin |
| `DELETE` | `/api/v1/discography/recordings/{id}` | Admin (409 si hay tracks que la referencian) |
| `GET` | `/api/v1/discography/releases` | Público (filtro `?type=`) |
| `GET` | `/api/v1/discography/releases/{id}` | Público (con ediciones, temas e imágenes anidados) |
| `POST` / `PATCH` / `DELETE` | `/api/v1/discography/releases[/{id}]` | Admin |
| `POST` / `PATCH` / `DELETE` | `/api/v1/discography/releases/{id}/editions[/{edition_id}]` | Admin |
| `POST` / `DELETE` | `.../editions/{edition_id}/images[/{image_id}]` | Admin |
| `PATCH` | `.../editions/{edition_id}/images/{image_id}/position` | Admin |

**`PATCH` (en `Release` y en `Edition`) es un PATCH de verdad**: usa
`model_dump(exclude_unset=True)` para distinguir un campo *omitido* (no se toca) de uno
*enviado como `null`* (se aplica, p. ej. borrar una `release_date` que resultó incierta). Si el
body de una edición incluye `tracks`, reemplaza la tracklist entera (se apoya en
`cascade="all, delete-orphan"` del modelo). Detalle de implementación a recordar: al reemplazar
la colección hay que vaciarla y hacer `flush()` **antes** de añadir los temas nuevos, o
SQLAlchemy puede emitir los `INSERT` antes que los `DELETE` de los viejos y chocar con el
`UNIQUE(edition_id, position)` cuando se repite un número de pista.

### Sellos discográficos (Label)

`Label` es una entidad propia (`labels`), no un texto libre en `Edition`. Lo motiva poder
crear/renombrar sellos desde la app y que varias ediciones que pertenecen al mismo sello
apunten a la misma fila real.

- **Unicidad insensible a mayúsculas**: índice funcional `uq_labels_name_lower` sobre
  `lower(name)`. Evita que "Virgin" y "virgin" coexistan como sellos distintos. Consecuencia:
  el 409 en `POST`/`PATCH /labels` compara siempre en minúsculas.
- **`Edition.label_id`** (FK nullable, `ondelete=RESTRICT`): el sello no siempre se conoce, de
  ahí que sea opcional. La restricción `RESTRICT` impide borrar un sello que siga siendo
  referenciado, pero el service lo verifica con un `SELECT` explícito antes de hacer el
  `DELETE` (no depende del `IntegrityError` de BD, para que el test con SQLite pase igual).
- **Migración `5677cd83477c`**: crea la tabla `labels`, migra los valores de texto existentes
  en `editions.label` (agrupando variantes de mayúsculas con `MIN + GROUP BY lower(...)`) y
  elimina la columna de texto original.
- `EditionRead.label` es un objeto `LabelRead` anidado (no solo un `id`), para que el cliente
  iOS reciba nombre y notas sin necesidad de un segundo request.
- **`LabelRead.edition_count`**: número de ediciones que usan ese sello. `GET /labels` lo
  calcula con un `outerjoin + GROUP BY` y ordena por él (`edition_count DESC`, nombre ASC).
  Cuando `LabelRead` viaja anidado en una `EditionRead` (serializado desde ORM sin ese
  cálculo), el campo vale `0` por defecto — es el único contexto donde ese valor no es exacto.

### Imágenes (portadas, contraportadas...) y almacenamiento

`Image` cuelga de `Edition` (no de `Release`): la portada puede variar por edición. Guarda
`image_type` (`front_cover` / `back_cover` / `other`), la `url` y un campo `position` (entero,
no nulo) que determina el orden de visualización dentro de la edición — **la base de datos nunca
guarda los bytes**, solo la URL que devuelve el backend de almacenamiento al subir el fichero.

- **`app/core/storage.py`** define el puerto `StorageBackend` (`save`/`delete`), con
  `LocalStorageBackend` como única implementación por ahora (disco local, servido por la propia
  API en `/media`, fuera de `/api/v1` a propósito: no es un recurso JSON versionado). El backend
  se elige por `Settings.storage_backend` (`.env`), igual que `database_url` elige el motor de
  BD — cambiar a GCS en producción será tocar `.env` y añadir `GCSStorageBackend`, no los
  endpoints. **GCS queda pendiente de implementar** hasta tener un proyecto/bucket real contra
  el que probarlo (código no verificable no se escribe a ciegas).
- Escribir a disco bloquea: `LocalStorageBackend` delega en `anyio.to_thread.run_sync` para no
  congelar el *event loop* async.
- **`front_cover`/`back_cover` se SUSTITUYEN al subir una nueva** (se borra la fila y el fichero
  viejo antes de guardar el nuevo): el admin no acumula portadas sueltas, basta con volver a
  subir para "reemplazar". `other` sí se acumula (varias páginas de un librillo, fotos sueltas).
  No hay restricción `UNIQUE` en BD para esto — lo gestiona el `service`, igual que el *demote*
  de `is_primary`.
- **`position`**: al subir una imagen nueva se le asigna `max(posiciones existentes) + 1`; al
  reemplazar una `front_cover`/`back_cover`, la nueva hereda la posición de la sustituida (no
  salta al final). El endpoint `PATCH .../images/{id}/position` mueve la imagen un puesto arriba
  o abajo intercambiando posición con la adyacente; devuelve la lista completa reordenada. Sin
  restricción `UNIQUE` en BD (complicaría el swap): el `service` gestiona el orden.
- Subida vía `multipart/form-data` (`UploadFile` + `Form`), primera vez que la API usa este
  patrón (requiere la dependencia `python-multipart`). Content-type restringido a
  JPEG/PNG/WEBP (422 si no) y tamaño máximo 10 MB (413 si se supera).
- En los tests, `get_storage_backend` se sobreescribe (en `conftest.py::client`) para apuntar a
  una carpeta temporal de pytest, no a la carpeta real de desarrollo (`./media`, en
  `.gitignore`).

### Colecciones de ediciones (Fase 6)

`Collection` (`/api/v1/discography/collections`, migración `904b404a095b`) agrupa ediciones de
**obras distintas** bajo un nombre común (p. ej. "Remasterizaciones HDCD": la edición HDCD de
*Tubular Bells*, la de *Hergest Ridge*... cada una en su propio `Release`). **No** es una caja
física de varios discos del MISMO álbum — eso ya es una `Edition` normal (o un `Release` tipo
`compilation`); una `Collection` es un agrupamiento TRANSVERSAL para navegación en la app, sin
país/sello/fecha/formato propios.

- **`collection_editions` es una `Table` de Core, NO una clase ORM** — a diferencia de
  `Track`/`Recording` (que sí necesitan una clase porque `Track` guarda datos propios:
  posición, disco, cara). Aquí no hay NINGÚN campo extra: el orden dentro de una colección se
  calcula siempre a partir de `Edition.release_date` (cronológico), nunca se guarda una
  posición manual. Clave primaria compuesta `(collection_id, edition_id)`, ambas FK
  `ondelete=CASCADE`.
- **`Edition.collections` (relación inversa) SIN `cascade="all, delete-orphan"`** — a
  diferencia de `tracks`/`images` en `Edition`, que sí son propiedad exclusiva de la edición y
  se borran con ella. Borrar una `Edition` no debe borrar la(s) `Collection`(s) a las que
  pertenece, solo la fila puente (de eso ya se encarga el `ondelete=CASCADE` de la FK en
  `collection_editions`).
- **Orden "las sin fecha, al final"**: `_sorted_by_release_date` usa como clave
  `(release_date is None, release_date)` en vez de confiar en el `ORDER BY` de cada motor —
  PostgreSQL pone los `NULL` al final en `ASC` por defecto, SQLite los pone al principio;
  ordenar en Python con esa clave da el mismo resultado en dev (SQLite) y producción
  (PostgreSQL) sin depender del comportamiento de cada motor. La tupla nunca compara `None`
  contra una fecha real directamente: dentro de cada grupo (`True`/`False`) los valores son
  homogéneos.
- **`GET /collections` construye `sample_cover_urls` tomando las 3 primeras ediciones por
  fecha y quedándose con las que SÍ tienen `front_cover`** (busca en `Edition.images`, mismo
  criterio de "primera imagen `front_cover`" que usa `Image` en el resto del módulo) — si
  alguna de esas 3 no tiene portada, se omite sin más: la lista puede salir con menos de 3
  elementos, o vacía. No se sigue buscando más allá de esas 3 para "rellenar el hueco".
- **`GET /collections/{id}` construye el DTO manualmente** (`_build_collection_detail_read`,
  mismo patrón que `_build_recording_read` para `RecordingRead.usages`): cada
  `CollectionEditionRead` mezcla campos de `Edition` con `release_id`/`release_title`/
  `release_type` de su `Release` — no se puede hacer con `from_attributes=True` directo porque
  la forma no coincide con ningún modelo ORM tal cual.
- **`POST .../editions` es IDEMPOTENTE** (decisión propia, no especificada explícitamente en el
  backlog): añadir una edición que ya estaba en la colección no es un error, simplemente no
  hace nada — encaja con el uso esperado en la app (un botón "añadir a colección" tipo toggle),
  y evita inventar un código de conflicto para un caso que no es realmente un conflicto de
  datos. **`DELETE .../editions/{edition_id}` SÍ da 404** si esa edición no estaba en la
  colección — aquí sí hay un caso claro de "esto no existe", mismo criterio que
  `image_not_found_exception` para un sub-recurso bajo un padre.
- **Nombre único, `unique=True` simple** (no el índice funcional insensible a mayúsculas que
  usa `Label`): el backlog no señaló el mismo riesgo de variantes de capitalización que llevó
  a esa decisión en `Label`, así que no se añadió la complejidad extra sin que se pidiera.
- **Crear una colección reutiliza el patrón de `Label`** (`session.add` + `commit` +
  capturar `IntegrityError` del `UNIQUE` de BD → 409), no un `SELECT` previo por nombre: más
  robusto ante condiciones de carrera que buscar-antes-de-insertar.
- **`PATCH /collections/{id}` (`service.update_collection`) es el mismo patrón que
  `update_label`**: PATCH real (`model_dump(exclude_unset=True)`), captura `IntegrityError`
  del `UNIQUE` → 409 en vez de un `SELECT` previo por nombre. Mantener el mismo nombre no
  choca con el `UNIQUE` (Postgres compara contra el resto de filas, no consigo misma), así
  que no hace falta un `id != other.id` explícito. Al final llama a `get_collection` (en vez
  de un `session.refresh` manual) para devolver el `CollectionDetailRead` completo con las
  ediciones ya cargadas — mismo truco que usa `add_edition_to_collection`.
- **`EditionRead.collections` (relación INVERSA, campo pedido a posteriori)**: qué
  colecciones incluyen esta edición — precarga los tags del formulario de edición en la app
  y sirve para un enlace "Parte de: X" en su detalle. Shape `CollectionSummaryRead` (solo
  `id` + `name`), deliberadamente MÁS LIGERO que `CollectionListRead`: no repite
  `edition_count`/`sample_cover_urls` (datos del listado de colecciones, no de una edición
  concreta) ni obliga a calcularlos en cada carga de una edición. Requirió añadir
  `selectinload(Edition.collections)` a `_RELEASE_WITH_EDITIONS`/`_EDITION_WITH_CHILDREN`
  (mismo sitio que `Edition.label`) y `"collections"` a los `session.refresh(edition,
  attribute_names=[...])` de `create_edition`/`update_edition` — sin ninguno de los dos,
  acceder a `edition.collections` tras crear/editar habría disparado un lazy-load asíncrono
  no soportado. Sin migración: reutiliza la relación `Edition.collections` que ya existía.

---

## Entorno de preproducción

Raspberry Pi (Ubuntu 24.04) en la red local (`192.168.1.54`, hostname `adarga`), expuesta en
internet bajo el dominio `api.pre.ommadawn.es` (CNAME → `ommadawn-api.ddns.net` vía No-IP).

**Stack en la Pi:**
- **Gunicorn** (2 workers, `UvicornWorker`) corriendo en `127.0.0.1:8000`, gestionado por
  systemd (`ommadawn-api.service`). Arranque automático con la máquina.
- **Caddy** como reverse proxy en los puertos 80/443, con TLS automático vía Let's Encrypt
  (`ommadawn-bot.service`). Certificado de `api.pre.ommadawn.es` se renueva solo.
- **PostgreSQL 16** nativo (no Docker). BD: `ommadawn_pre`, usuario: `ommadawn`.
- **`.env`** en `/home/vattenbit/ommadawn-api/.env` — incluye `MEDIA_BASE_URL=https://api.pre.ommadawn.es/media`
  (crítico: sin esto las URLs de imágenes apuntan a `localhost`).

**Despliegue:** `./deploy/pre.sh` desde el Mac — hace `git pull` + `pip install` +
`alembic upgrade head` + `systemctl restart ommadawn-api` vía SSH.

**Acceso SSH:** clave en `~/.ssh/id_ed25519` (Mac → Pi sin contraseña).
Deploy key del repo en la Pi: `~/.ssh/id_ed25519` (solo lectura en GitHub).

**Bot de Telegram** (`ommadawn-bot.service`): controla el servicio desde el móvil.
Script en `/home/vattenbit/ommadawn-bot.py`. Comandos: `/status`, `/on`, `/off`, `/restart`.
Solo responde al chat ID autorizado — el token y el chat ID viven en el script (no en el repo).

---

## Referencia

`../microservices/identity_service` es un microservicio FastAPI async ya funcional (auth con
JWT + refresh rotativo). **Se usa como referencia de estilo y patrones**, pero el auth de
`ommadawn-api` se escribe de cero e integrado como módulo interno, no se consume como servicio
externo.
