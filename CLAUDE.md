# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Qué es este proyecto

`ommadawn_api` es una **API REST** que cataloga la obra de **Mike Oldfield**: discografía
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

## Stack

| Tecnología | Función |
|---|---|
| Python 3.12+ | Lenguaje |
| FastAPI | Framework web async, genera OpenAPI automáticamente |
| SQLAlchemy 2.0 (async) | ORM |
| Alembic | Migraciones de base de datos |
| Pydantic v2 + pydantic-settings | Schemas de API y configuración vía `.env` |
| passlib[argon2] | Hashing de contraseñas |
| PyJWT | Access / refresh tokens |
| SQLite (aiosqlite) | Base de datos en **desarrollo** |
| PostgreSQL (asyncpg) | Base de datos en **producción** |
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

---

## Estructura prevista

> El repositorio está **vacío** todavía. Esta es la estructura objetivo hacia la que
> construir (patrón inspirado en `identity_service`, adaptado a monolito modular).

```
ommadawn_api/
├── app/
│   ├── main.py                 # App FastAPI, lifespan, montaje de routers de cada módulo
│   ├── core/
│   │   ├── config.py           # Settings vía pydantic-settings (.env)
│   │   ├── database.py         # Engine async, sesión, Base ORM, dependencia get_session
│   │   ├── security.py         # argon2, PyJWT, helpers de hashing
│   │   └── exceptions.py       # HTTPExceptions reutilizables
│   └── modules/
│       ├── auth/               # Fases 2-4 (modelo, tokens, endpoints)
│       │   ├── models.py
│       │   ├── schemas.py
│       │   ├── service.py
│       │   └── router.py       # /api/v1/auth/*
│       ├── discography/        # Fase 5 (futuro)
│       └── concerts/           # Fase 6 (futuro)
├── migrations/                 # Alembic (env.py async, versions/)
├── tests/                      # Tests de integración por módulo
├── .env.example
├── alembic.ini
└── pyproject.toml
```

---

## Comandos

> Aún no existe código; estos son los comandos objetivo del stack elegido.

```bash
# Entorno e instalación
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Configuración
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(64))"   # generar SECRET_KEY

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

En **desarrollo** las tablas pueden crearse al arrancar; en **producción** el esquema se
gestiona siempre con Alembic.

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
| **Fase 2 — Modelo de usuario** | Model ORM `User` (tabla `users`): login por username o email (ambos únicos), `full_name` y `hashed_password` opcionales (preparado para OAuth futuro), `is_active`, `is_admin`, timestamps. | ✅ Hecha |
| **Fase 3 — Flujo de tokens** | Access token + refresh token con rotación, hashing de contraseñas (argon2), seguridad JWT. | ✅ Hecha |
| **Fase 4 — Endpoints de auth** | `register`, `login`, `refresh`, `logout`, `me` + tests de integración. Cierra el bloque de auth. | ✅ Hecha |
| **Fase 5 — Discografía** | Discos (álbumes de estudio), recopilatorios, singles, bootlegs, directos… y sus temas/pistas. | ⏭️ Siguiente |
| **Fase 6 — Conciertos** | Giras, fechas, salas, setlists. | Pendiente |
| **Fase 7 — Libros** | Bibliografía relacionada. | Pendiente |
| **Fases siguientes** | Otras secciones a acordar con el usuario. | Pendiente |

---

## Referencia

`../microservices/identity_service` es un microservicio FastAPI async ya funcional (auth con
JWT + refresh rotativo). **Se usa como referencia de estilo y patrones**, pero el auth de
`ommadawn_api` se escribe de cero e integrado como módulo interno, no se consume como servicio
externo.
