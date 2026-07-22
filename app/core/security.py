"""Primitivas de seguridad: hashing de contrasenas y tokens.

Este modulo contiene funciones PURAS: no tocan la base de datos ni saben nada
de HTTP. Solo transforman datos (una contrasena en un hash, un id de usuario en
un JWT, etc.). Toda la logica que necesita BD (guardar un refresh token,
revocarlo, rotarlo) vive en el `service` del modulo de auth, no aqui.

Se manejan DOS tipos de token, con proposito distinto:

  - Access token: un JWT firmado, de vida corta (~15 min). El servidor lo valida
    solo con la firma, sin consultar la BD (es "stateless"). Rapido, pero no se
    puede revocar antes de que caduque -> por eso dura poco.

  - Refresh token: una cadena aleatoria opaca (NO un JWT), de vida larga
    (~30 dias). Su "verdad" vive en la BD, donde se guarda HASHEADO. Al estar en
    BD si se puede revocar -> es lo que permite cerrar sesion de verdad y rotar.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings

settings = get_settings()

# Hasher de argon2 (a traves de argon2-cffi directamente, sin passlib de por
# medio). Con sus parametros por defecto usa argon2id, el modo recomendado.
# `PasswordHasher` genera un `salt` aleatorio en cada hash, asi que dos usuarios
# con la misma contrasena tendran hashes distintos.
password_hasher = PasswordHasher()


# --- Contrasenas ---------------------------------------------------------------


def hash_password(password: str) -> str:
    """Devuelve el hash argon2id de una contrasena en claro.

    Nunca se guarda la contrasena en claro: solo este hash.
    """
    return password_hasher.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Comprueba si una contrasena en claro corresponde a un hash guardado.

    No se "deshashea" (es imposible): argon2 vuelve a derivar el hash con el
    mismo salt y lo compara. `argon2-cffi` LANZA excepcion cuando no coincide (o
    si el hash esta mal formado); aqui la traducimos a un `bool` limpio para que
    quien llame no tenga que preocuparse de excepciones.

    Nota: el orden de los argumentos en argon2-cffi es `verify(hash, password)`,
    al reves que en passlib.
    """
    try:
        return password_hasher.verify(hashed, plain)
    except (VerifyMismatchError, InvalidHashError):
        return False


# --- Access token (JWT) --------------------------------------------------------


def create_access_token(user_id: int) -> str:
    """Crea un access token JWT firmado para un usuario.

    El "payload" (contenido del token) lleva:
      - sub  : el "subject", a quien pertenece el token (el id de usuario).
               Por convencion del estandar JWT es una cadena, no un int.
      - exp  : instante de caducidad. PyJWT lo valida solo al decodificar.
      - type : marca que es un token de tipo "access". Es una defensa extra
               para no aceptar por error otro tipo de token donde toca un access.

    El token va firmado con `SECRET_KEY`: cualquiera puede LEER su contenido
    (no va cifrado), pero nadie puede FABRICAR uno valido sin la clave secreta.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> dict:
    """Verifica la firma y la caducidad de un access token y devuelve su payload.

    IMPORTANTE: esta funcion LANZA excepcion si el token no es valido:
      - jwt.ExpiredSignatureError -> el token ha caducado.
      - jwt.InvalidTokenError     -> firma incorrecta, formato invalido, etc.
    Quien la llame (el service / la dependencia de auth) es responsable de
    capturar esas excepciones y traducirlas a un 401. Aqui no sabemos de HTTP.
    """
    return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])


# --- Refresh token (cadena opaca guardada hasheada en BD) ----------------------


def generate_refresh_token() -> str:
    """Genera un refresh token nuevo: 64 bytes aleatorios en base64 url-safe.

    No es un JWT ni codifica informacion: es un secreto aleatorio imposible de
    adivinar. Este valor en claro se le entrega UNA vez al cliente; en la BD solo
    guardaremos su hash (ver `hash_refresh_token`).
    """
    return secrets.token_urlsafe(64)


def hash_refresh_token(token: str) -> str:
    """Devuelve el hash SHA-256 (hex) de un refresh token, para guardarlo en BD.

    Aqui SHA-256 es suficiente (no hace falta argon2): el token ya es largo y
    totalmente aleatorio, no una contrasena elegida por un humano, asi que no hay
    que defenderse de ataques de fuerza bruta / diccionario. Guardar el hash (y
    no el token) evita que quien lea la BD pueda reutilizar los tokens.
    """
    return hashlib.sha256(token.encode()).hexdigest()
