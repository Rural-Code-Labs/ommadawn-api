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

# 403 -> el usuario esta autenticado, pero no es administrador. La usan los
# endpoints de escritura de los modulos de catalogo (discografia, conciertos...):
# leer es publico, curar el contenido exige ser admin.
admin_required_exception = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="Se requieren permisos de administrador",
)

# 403 -> el usuario es admin, incluso, pero no SUPERadministrador. La usan los
# endpoints que gestionan el rol de otros usuarios (quien es admin).
superadmin_required_exception = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="Se requieren permisos de superadministrador",
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

# 401 -> el ID token de Google no supera la verificacion (firma, caducidad,
# audiencia distinta al Web Client ID, emisor incorrecto, o email no
# verificado en la cuenta de Google). Mensaje generico a proposito, mismo
# criterio que credentials_exception: no da pistas de por que ha fallado.
invalid_google_token_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="ID token de Google invalido",
)

# 409 -> el email del token de Google ya pertenece a un usuario registrado por
# contrasena (sin Google vinculado). Deliberadamente NO se auto-vincula (seria
# vincular una cuenta a ciegas solo por coincidir el email) ni se crea un
# usuario duplicado. El `detail` es un CODIGO corto, no una frase (a
# diferencia del resto de excepciones de este fichero): la app necesita
# distinguir este caso de un 401/422 generico por el propio valor del campo,
# sin tener que parsear un texto humano.
google_email_conflict_exception = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="email_conflict",
)
