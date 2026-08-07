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

# 409 -> intenta cambiar el username por PATCH /auth/me pero ya no puede: o
# bien lo eligio en el registro por contrasena, o bien ya gasto su UNICO cambio
# permitido (una cuenta creada por Google empieza con un username provisional
# generado al azar, cambiable una sola vez). Mismo criterio que
# `google_email_conflict_exception`: `detail` es un CODIGO corto, no una
# frase, para que la app pueda explicarle a la persona por que no puede tocarlo
# sin tener que parsear un texto humano.
username_already_set_exception = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="username_already_set",
)

# 409 -> POST /auth/me/google: la cuenta de Google del ID token (su `sub`) ya
# esta vinculada a OTRO usuario. Igual que con el email en el login (no se
# auto-vincula a ciegas), aqui tampoco se permite que dos usuarios compartan
# la misma cuenta de Google. Mismo criterio de CODIGO corto que el resto de
# conflictos de Google/username en este fichero.
google_already_linked_exception = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="google_already_linked",
)

# 409 -> DELETE /auth/me/google: el usuario no tiene contrasena
# (`hashed_password is None`), es decir, Google es su UNICA forma de entrar.
# Desvincular lo dejaria sin ninguna manera de autenticarse. Mismo criterio de
# CODIGO corto.
google_only_access_exception = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="google_only_access",
)

# 401 -> POST /auth/me/password: la cuenta YA tiene contrasena y la
# `current_password` enviada no coincide. Deliberadamente NO reutiliza
# `credentials_exception`: si reutilizara el mismo objeto (mismo status,
# mismo detail, misma cabecera), la app no podria distinguir esto de una
# sesion caducada (ambos serian un 401 identico). Con un `detail` propio en
# prosa (no un codigo: aqui no hace falta, es el UNICO motivo de 401 posible
# en este endpoint una vez pasado el Bearer) la distincion es automatica.
invalid_current_password_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="La contrasena actual no es correcta",
)

# 409 -> DELETE /auth/me/password: la cuenta no tiene Google vinculado
# (`google_id is None`), es decir, la contrasena es su UNICA forma de entrar.
# Quitarla la dejaria sin ninguna manera de autenticarse. Espejo exacto de
# `google_only_access_exception` (que bloquea desvincular Google cuando no
# hay contrasena); mismo criterio de CODIGO corto.
password_only_access_exception = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="password_only_access",
)

# 429 -> POST /auth/verify-email/confirm: 5 intentos fallidos ya consumidos en
# las ultimas 24h (ventana movil: no se resetea al pedir un codigo nuevo, solo
# al acertar o al ir "envejeciendo" los intentos antiguos fuera de la
# ventana). Se rechaza SIN comprobar el codigo enviado, para no filtrar por
# temporizacion si el codigo era correcto o no una vez bloqueado.
too_many_verification_attempts_exception = HTTPException(
    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
    detail="too_many_attempts",
)

# 401 -> POST /auth/verify-email/confirm: el codigo no coincide con el
# pendiente, o ha caducado (2h), o no habia ninguno pendiente. Un solo error
# generico para los tres casos (mismo criterio que credentials_exception): no
# hay motivo para que la app sepa CUAL de los tres fue.
invalid_verification_code_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="invalid_code",
)
