"""Configuracion de la aplicacion.

Toda la configuracion se lee de variables de entorno (o del fichero .env en
desarrollo). Nada de valores "hardcodeados" repartidos por el codigo: cualquier
parametro que cambie entre entornos (dev / produccion) vive aqui.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings de la app, validados por Pydantic al arrancar.

    Si falta una variable obligatoria (p.ej. SECRET_KEY sin valor por defecto),
    la app fallara al iniciar en vez de romper mas tarde en runtime.
    """

    # --- Metadatos de la API (se muestran en /docs) ---
    app_name: str = "Ommadawn API"
    app_version: str = "0.1.0"

    # --- Base de datos ---
    # En desarrollo usamos SQLite; en produccion basta cambiar esta URL a
    # PostgreSQL en el .env, sin tocar codigo.
    database_url: str = "sqlite+aiosqlite:///./ommadawn.db"

    # --- Almacenamiento de ficheros (portadas, contraportadas...) ---
    # "local" en desarrollo (disco, servido por la propia API en /media); en
    # produccion sera "gcs" (Google Cloud Storage, pendiente de implementar).
    # Se elige por config, igual que database_url: cambiar de backend no toca
    # codigo. Ver app/core/storage.py.
    storage_backend: str = "local"
    media_root: str = "./media"
    media_base_url: str = "http://localhost:8000/media"

    # --- Seguridad / JWT ---
    secret_key: str  # obligatorio: sin valor por defecto
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

    # --- Envio de correo (verificacion de email) ---
    # "console" en desarrollo (escribe el correo en el log, ver
    # app/core/email.py); un proveedor real (SMTP/SendGrid) queda pendiente de
    # implementar hasta tener una cuenta real contra la que probarlo.
    email_backend: str = "console"

    # --- Login con Google (OAuth) ---
    # El "Web Client ID" del proyecto en Google Cloud Console. La app iOS (y en
    # el futuro Android) configura el SDK con `serverClientID` = este mismo
    # valor, asi que el `aud` del ID token que envian coincide con el, no con
    # el "iOS Client ID" (ese solo lo usa el SDK para el flujo nativo, la API
    # nunca lo ve). Un unico Web Client ID sirve como audiencia comun para
    # cualquier plataforma cliente. Obligatorio: sin valor por defecto.
    google_web_client_id: str

    # Lee variables desde .env; ignora las que no esten declaradas aqui.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Devuelve la instancia de Settings (cacheada).

    Se lee del entorno una sola vez y se reutiliza. Usar esta funcion (en vez de
    una variable global) permite sobrescribir la config facilmente en los tests.
    """
    return Settings()  # type: ignore[call-arg]
