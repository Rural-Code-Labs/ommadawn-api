# Ommadawn API

API REST que cataloga la obra de **Mike Oldfield**: discografía (álbumes de
estudio, recopilatorios, singles, directos, bootlegs…), conciertos, libros y
otras secciones. Está pensada para ser consumida por una **app móvil** (primero
iOS y, en el futuro, Android), por lo que el contrato de la API (REST + OpenAPI)
es un ciudadano de primera clase: estable y bien versionado.

> Proyecto de aprendizaje, pero construido con criterio y con la intención de
> publicarse y ser usado de verdad. Se avanza en **fases pequeñas y entendibles**
> (ver más abajo), priorizando el *por qué* de cada decisión sobre la velocidad.

---

## Stack

| Tecnología | Función |
|---|---|
| Python 3.12+ | Lenguaje |
| FastAPI | Framework web async; genera OpenAPI automáticamente |
| SQLAlchemy 2.0 (async) | ORM |
| Alembic | Migraciones de base de datos |
| Pydantic v2 + pydantic-settings | Schemas de API y configuración vía `.env` |
| passlib[argon2] | Hashing de contraseñas |
| PyJWT | Access / refresh tokens |
| SQLite (aiosqlite) | Base de datos en **desarrollo** |
| PostgreSQL (asyncpg) | Base de datos en **producción** |
| pytest + pytest-asyncio + httpx | Tests de integración |

Pasar de desarrollo a producción es **solo cambiar `DATABASE_URL`** en `.env`,
sin tocar código.

---

## Arquitectura

**Monolito modular** (no microservicios): una única aplicación FastAPI dividida
en **módulos por dominio** (`auth`, `discography`, `concerts`…). La adaptabilidad
se consigue con **fronteras limpias entre módulos**, no separando en procesos:

- Cada módulo es autocontenido: tiene sus propios `models`, `schemas`,
  `service` y `router`.
- Los módulos **no** acceden a las tablas de otro módulo directamente: se
  comunican a través de la capa de `service`. Esto permite, el día que haga
  falta, extraer un módulo a un servicio independiente con poca fricción.
- Lo compartido (config, engine de BD, `Base` ORM, seguridad) vive en `core/`.

**Arquitectura en capas** dentro de cada módulo — `router → service → model`,
con `schema` como contrato de entrada/salida:

- **router**: define endpoints y dependencias (auth, sesión de BD). Sin lógica
  de negocio.
- **service**: toda la lógica de negocio y el acceso a datos. No sabe nada de HTTP.
- **model**: tablas SQLAlchemy.
- **schema**: modelos Pydantic para request/response. Los models ORM nunca se
  exponen directamente en la API.

**Versionado desde el día 1**: todos los endpoints cuelgan de `/api/v1/...`. Un
cambio incompatible implica una nueva versión (`/api/v2`), no romper la existente.

---

## Estructura del proyecto

```
ommadawn_api/
├── app/
│   ├── main.py                 # App FastAPI, lifespan, montaje de routers
│   ├── core/
│   │   ├── config.py           # Settings vía pydantic-settings (.env)
│   │   ├── database.py         # Engine async, sesión, Base ORM, get_session
│   │   ├── security.py         # argon2 (hashing) + JWT + refresh tokens
│   │   └── exceptions.py       # HTTPExceptions reutilizables
│   └── modules/
│       └── auth/
│           ├── models.py       # User, RefreshToken
│           ├── schemas.py      # Contratos Pydantic (request/response)
│           ├── service.py      # Lógica: registro, login, tokens, rotación
│           ├── dependencies.py # get_current_user (protege endpoints)
│           └── router.py       # Endpoints /api/v1/auth/*
├── tests/
│   ├── conftest.py             # Fixtures (cliente HTTP + BD en memoria)
│   └── test_auth.py            # Tests de integración de auth
├── .env.example
└── pyproject.toml
```

---

## Puesta en marcha

```bash
# Entorno e instalación
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Configuración
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(64))"   # generar SECRET_KEY
# …y pégala en la variable SECRET_KEY de tu .env

# Arrancar el servidor (docs interactivas en http://localhost:8000/docs)
uvicorn app.main:app --reload
```

En **desarrollo** las tablas se crean solas al arrancar (`create_all`); en
**producción** el esquema se gestiona siempre con migraciones Alembic.

### Tests

```bash
pytest tests/ -v
pytest tests/test_auth.py::test_login -v        # un solo test
```

---

## Sistema de autenticación (tokens)

Se manejan **dos tokens con roles distintos**:

| | Access token | Refresh token |
|---|---|---|
| Qué es | Un **JWT** firmado | Una cadena aleatoria **opaca** |
| Dónde vive la verdad | En el propio token (*stateless*) | En la **base de datos** (hasheado) |
| Duración | Corta (~15 min) | Larga (~30 días) |
| ¿Se puede revocar? | No (hasta que caduque) | Sí |
| Se usa para… | Autenticar cada petición | Renovar el access token |

- Las **contraseñas** se hashean con **argon2** (nunca se guardan en claro).
- Los **refresh tokens** se guardan **hasheados** (SHA-256): quien lea la BD no
  puede reutilizarlos.
- **Rotación**: cada renovación revoca el refresh token usado y emite uno nuevo,
  de forma atómica. Un token robado deja de servir en cuanto el usuario legítimo
  renueva.

### Endpoints

| Método | Ruta | Protegido | Descripción |
|---|---|---|---|
| `POST` | `/api/v1/auth/register` | — | Crea un usuario (devuelve el perfil, `201`) |
| `POST` | `/api/v1/auth/login` | — | Login por username **o** email; devuelve el par de tokens |
| `POST` | `/api/v1/auth/refresh` | — | Rota el refresh token y emite un par nuevo |
| `POST` | `/api/v1/auth/logout` | 🔒 | Revoca el refresh token (`204`) |
| `GET` | `/api/v1/auth/me` | 🔒 | Devuelve el usuario autenticado |

🔒 = requiere `Authorization: Bearer <access token>`.

### Flujo: del login al logout

```mermaid
sequenceDiagram
    participant App as App móvil
    participant API as Ommadawn API
    participant DB as Base de datos

    note over App,DB: 1 · Login
    App->>API: usuario + contraseña
    API->>DB: verifica hash argon2 · guarda hash del refresh token
    API-->>App: access token (JWT, ~15 min) + refresh token (~30 días)

    note over App,DB: 2 · Petición autenticada (se repite ~15 min)
    App->>API: GET /api/v1/... · Authorization: Bearer <access token>
    API->>API: valida firma y caducidad del JWT (sin tocar la BD)
    API-->>App: datos

    note over App,DB: 3 · Renovación con rotación (el access token caducó)
    App->>API: refresh token → /api/v1/auth/refresh
    API->>DB: valida · revoca el actual · emite uno nuevo (atómico)
    API-->>App: nuevo access token + nuevo refresh token

    note over App,DB: 4 · Logout
    App->>API: refresh token → /api/v1/auth/logout
    API->>DB: marca el token como revocado
    API-->>App: sesión cerrada
```

---

## Plan por fases

El proyecto se construye por fases pequeñas; cada una se cierra (y se entiende)
antes de empezar la siguiente.

| Fase | Contenido | Estado |
|---|---|---|
| **1 — Esqueleto** | Estructura del proyecto, capa `core/` (config, base de datos, `Base` ORM) y app FastAPI con `/health`. | ✅ Hecha |
| **2 — Modelo de usuario** | Model ORM `User`: login por username o email (únicos), `full_name` y `hashed_password` opcionales (preparado para OAuth), `is_active`, `is_admin`, timestamps. | ✅ Hecha |
| **3 — Flujo de tokens** | Hashing argon2, JWT access token y refresh token con rotación. | ✅ Hecha |
| **4 — Endpoints de auth** | `register`, `login`, `refresh`, `logout`, `me` + tests de integración. Cierra el bloque de auth. | ✅ Hecha |
| **5 — Discografía** | Álbumes de estudio, recopilatorios, singles, bootlegs, directos… y sus temas/pistas. | ⏭️ Siguiente |
| **6 — Conciertos** | Giras, fechas, salas, setlists. | Pendiente |
| **7 — Libros** | Bibliografía relacionada. | Pendiente |
