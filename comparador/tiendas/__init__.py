from comparador.tiendas import click, imeqmo, intelaf, macrosistemas

# nombre visible -> (módulo, clave de configuración)
COMPETIDORES = {
    "Intelaf": (intelaf, "intelaf"),
    "MacroSistemas": (macrosistemas, "macrosistemas"),
    "Click": (click, "click"),
}

__all__ = ["imeqmo", "COMPETIDORES"]
