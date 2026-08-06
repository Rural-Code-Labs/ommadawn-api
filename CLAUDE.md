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
  marcha**: modelo `Release`/`Track` + endpoints de discos ya funcionando (ver tabla de
  fases y sección "Discografía" más abajo). Quedan recopilatorios/singles/bootlegs por
  poblar con datos reales y, más adelante, "directos" como tipo nuevo.
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
  distingue después si la sesión vino de contraseña o de Google.

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
│   │   └── country_codes.py    # Lista ISO 3166-1 alpha-2 + validate_country_code (compartido)
│   └── modules/
│       ├── auth/               # ✅ Fases 2-4 (bloque cerrado)
│       │   ├── models.py       # User, RefreshToken
│       │   ├── schemas.py      # Contratos Pydantic (request/response)
│       │   ├── service.py      # Lógica: registro, login, tokens, rotación
│       │   ├── dependencies.py # get_current_user, require_admin (protegen endpoints)
│       │   └── router.py       # /api/v1/auth/*
│       ├── discography/        # 🚧 Fase 5 en marcha (Release -> Edition -> Track/Image)
│       │   ├── models.py       # Release, Edition (is_primary), Track, Image (ImageType)
│       │   ├── schemas.py      # Release/Edition/Track/Image: Create, Read, Update
│       │   ├── service.py      # CRUD anidado + demotes (primary, portada) + subida
│       │   └── router.py       # /api/v1/discography/* (leer: público; escribir: admin)
│       └── concerts/           # Fase 6 (futuro)
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
- **Lógica en `service.google_login`, tres casos**:
  1. Ya existe un usuario con ese `google_id` → login normal (mismo flujo que `login_user`
     desde ahí en adelante, factorizado en el helper común `_issue_token_pair`).
  2. No existe por `google_id` pero SÍ por email → esa cuenta se creó por contraseña y no
     tiene Google vinculado. **Decisión explícita: no se auto-vincula ni se crea un
     duplicado.** Responde `409` con `{"detail": "email_conflict"}`.
  3. No existe ni por `google_id` ni por email → alta nueva, vinculada desde el primer
     momento; `full_name`/`avatar_url` se rellenan con `name`/`picture` del token si vienen
     (no es bloqueante si no vienen). El `username` no lo da Google: se deriva de la parte
     local del email (`_generate_username_from_email`), probando sufijos numéricos
     (`nombre`, `nombre1`, `nombre2`...) hasta encontrar uno libre.
- **`email_conflict` es un CÓDIGO, no una frase** — única excepción al resto de
  `app/core/exceptions.py`, donde `detail` siempre es texto humano en español. Decisión
  explícita del usuario: la app necesita distinguir este 409 de cualquier otro por el propio
  valor del campo, sin parsear un mensaje.
- **`email_verified` del token se exige `True`**: si Google no ha verificado el email (caso
  raro, pero posible con algunos proveedores federados detrás de Google), se trata igual que
  un token inválido (`401`), no se confía en un email sin verificar para vincular/crear cuenta.
- **Tests** (`tests/test_auth.py`): `verify_google_id_token` hace una petición de red real, así
  que en los tests se sustituye por un doble (`monkeypatch.setattr(service,
  "verify_google_id_token", fake)`) que devuelve un payload controlado o lanza el error que se
  quiera simular — mismo patrón que `MAX_IMAGE_SIZE_BYTES` en los tests de avatar/imágenes.
- **Vinculación/desvinculación desde perfil** (`POST`/`DELETE /auth/me/google`) queda como
  tarea posterior: no forma parte de este endpoint.

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

## Plan por fases

El proyecto se construye por fases **pequeñas y entendibles**. Cada fase se cierra (y se
entiende) antes de empezar la siguiente. Las secciones de dominio se detallarán con el usuario
sobre la marcha.

El bloque de **auth (usuarios)** se escribe **desde cero** (no se copia `identity_service`;
solo sirve de referencia de estilo) y se reparte en varias fases:

| Fase | Contenido | Estado |
|---|---|---|
| **Fase 1 — Esqueleto / schema base** | Estructura del proyecto: `pyproject.toml`, `.env`, capa `core/` (config, base de datos, `Base` ORM) y app FastAPI que arranca con `/health`. | ✅ Hecha |
| **Fase 2 — Modelo de usuario** | Model ORM `User` (tabla `users`): login por username o email (ambos únicos), `full_name` y `hashed_password` opcionales (preparado para OAuth futuro), `is_active`, `is_admin`, timestamps. Ampliado después con perfil editable (`country`, `city`, `birth_date`, avatar, `theme_preference`) y `is_super_admin` — ver "Perfil, avatar y roles" más abajo. | ✅ Hecha |
| **Fase 3 — Flujo de tokens** | Access token + refresh token con rotación, hashing de contraseñas (argon2), seguridad JWT. | ✅ Hecha |
| **Fase 4 — Endpoints de auth** | `register`, `login`, `refresh`, `logout`, `me` + tests de integración. Cierra el bloque de auth. | ✅ Hecha |
| **Fase 5 — Discografía** | Discos (álbumes de estudio), recopilatorios, singles, bootlegs, directos… y sus temas/pistas. | 🚧 En marcha (modelo + endpoints de discos listos; falta poblar y añadir "directo") |
| **Fase 6 — Conciertos** | Giras, fechas, salas, setlists. | Pendiente |
| **Fase 7 — Libros** | Bibliografía relacionada. | Pendiente |
| **Fases siguientes** | Otras secciones a acordar con el usuario. | Pendiente |

---

## Referencia

`../microservices/identity_service` es un microservicio FastAPI async ya funcional (auth con
JWT + refresh rotativo). **Se usa como referencia de estilo y patrones**, pero el auth de
`ommadawn-api` se escribe de cero e integrado como módulo interno, no se consume como servicio
externo.
