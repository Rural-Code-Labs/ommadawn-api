"""Validacion de codigos de pais ISO 3166-1 alpha-2 + supranacionales de discografia.

Compartido entre los modulos que tienen un campo `country` (auth, discography).
El validador normaliza a mayusculas antes de comprobar, de modo que "es" y "ES"
son ambos validos y se guardan siempre como "ES".
"""

ISO_3166_1_ALPHA2: frozenset[str] = frozenset({
    "AD", "AE", "AF", "AG", "AI", "AL", "AM", "AO", "AQ", "AR", "AS", "AT",
    "AU", "AW", "AX", "AZ", "BA", "BB", "BD", "BE", "BF", "BG", "BH", "BI",
    "BJ", "BL", "BM", "BN", "BO", "BQ", "BR", "BS", "BT", "BV", "BW", "BY",
    "BZ", "CA", "CC", "CD", "CF", "CG", "CH", "CI", "CK", "CL", "CM", "CN",
    "CO", "CR", "CU", "CV", "CW", "CX", "CY", "CZ", "DE", "DJ", "DK", "DM",
    "DO", "DZ", "EC", "EE", "EG", "EH", "ER", "ES", "ET", "FI", "FJ", "FK",
    "FM", "FO", "FR", "GA", "GB", "GD", "GE", "GF", "GG", "GH", "GI", "GL",
    "GM", "GN", "GP", "GQ", "GR", "GS", "GT", "GU", "GW", "GY", "HK", "HM",
    "HN", "HR", "HT", "HU", "ID", "IE", "IL", "IM", "IN", "IO", "IQ", "IR",
    "IS", "IT", "JE", "JM", "JO", "JP", "KE", "KG", "KH", "KI", "KM", "KN",
    "KP", "KR", "KW", "KY", "KZ", "LA", "LB", "LC", "LI", "LK", "LR", "LS",
    "LT", "LU", "LV", "LY", "MA", "MC", "MD", "ME", "MF", "MG", "MH", "MK",
    "ML", "MM", "MN", "MO", "MP", "MQ", "MR", "MS", "MT", "MU", "MV", "MW",
    "MX", "MY", "MZ", "NA", "NC", "NE", "NF", "NG", "NI", "NL", "NO", "NP",
    "NR", "NU", "NZ", "OM", "PA", "PE", "PF", "PG", "PH", "PK", "PL", "PM",
    "PN", "PR", "PS", "PT", "PW", "PY", "QA", "RE", "RO", "RS", "RU", "RW",
    "SA", "SB", "SC", "SD", "SE", "SG", "SH", "SI", "SJ", "SK", "SL", "SM",
    "SN", "SO", "SR", "SS", "ST", "SV", "SX", "SY", "SZ", "TC", "TD", "TF",
    "TG", "TH", "TJ", "TK", "TL", "TM", "TN", "TO", "TR", "TT", "TV", "TW",
    "TZ", "UA", "UG", "UM", "US", "UY", "UZ", "VA", "VC", "VE", "VG", "VI",
    "VN", "VU", "WF", "WS", "XK", "YE", "YT", "ZA", "ZM", "ZW",
})

# Codigos supranacionales usados habitualmente en discografia real (Discogs, MusicBrainz...).
# No son ISO 3166-1 alpha-2 estrictos pero cumplen el patron de 2 letras mayusculas.
_SUPRANATIONAL: frozenset[str] = frozenset({
    "EU",  # Union Europea — muy frecuente en lanzamientos europeos
    "XW",  # Worldwide — lanzamientos globales (convencion Discogs)
})

# Conjunto completo aceptado por el validador.
VALID_COUNTRY_CODES: frozenset[str] = ISO_3166_1_ALPHA2 | _SUPRANATIONAL

# Alias habituales que no son codigos validos pero se encuentran en datos reales.
_ALIASES: dict[str, str] = {
    "UK": "GB",
    "USA": "US",
}


def validate_country_code(value: str | None) -> str | None:
    """Normaliza y valida un codigo de pais.

    - None se devuelve tal cual (el campo es opcional).
    - El valor se convierte a mayusculas y se remapean alias conocidos.
    - Si no esta en VALID_COUNTRY_CODES, lanza ValueError con mensaje claro.
    """
    if value is None:
        return None
    normalized = value.strip().upper()
    normalized = _ALIASES.get(normalized, normalized)
    if normalized not in VALID_COUNTRY_CODES:
        raise ValueError(
            f"'{value}' no es un codigo de pais valido (ISO 3166-1 alpha-2, ej. 'ES', 'GB', 'EU')"
        )
    return normalized
