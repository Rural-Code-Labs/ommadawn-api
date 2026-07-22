"""Excepciones HTTP reutilizables.

Son objetos `HTTPException` de FastAPI ya construidos, listos para lanzar desde
la capa de `service`. Centralizarlos aqui evita repetir el mismo codigo/mensaje
por todo el proyecto y garantiza que un mismo tipo de error responde SIEMPRE con
el mismo status y el mismo formato.

Ojo con lo que revelan los mensajes: en el login usamos UN SOLO error generico
(`credentials_exception`) tanto si el usuario no existe como si la contrasena es
incorrecta. Asi un atacante no puede averiguar que usernames/emails existen.
"""

from fastapi import HTTPException, status
from pydantic import BaseModel


class ErrorMessage(BaseModel):
    """Forma del cuerpo de una respuesta de error.

    FastAPI devuelve los errores como `{"detail": "..."}`. Declarar este modelo
    permite que la documentacion (OpenAPI/Swagger) muestre exactamente esa forma,
    para que el cliente (la app movil) sepa que esperar en cada error.
    """

    detail: str

# 401 -> el login ha fallado. Mensaje deliberadamente vago (ver docstring).
# La cabecera WWW-Authenticate es la forma estandar de indicar que se espera un
# token "Bearer".
credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="No se han podido validar las credenciales",
    headers={"WWW-Authenticate": "Bearer"},
)

# 401 -> el refresh token no sirve: no existe, esta revocado o ha caducado.
invalid_refresh_token_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Refresh token invalido o caducado",
)

# 403 -> las credenciales eran correctas, pero la cuenta esta desactivada.
inactive_user_exception = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="Usuario inactivo",
)

# 409 Conflict -> intentar registrar algo que ya existe. Separamos username de
# email para que la app pueda decirle al usuario que campo cambiar.
username_taken_exception = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="El nombre de usuario ya esta en uso",
)

email_taken_exception = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="El email ya esta registrado",
)
