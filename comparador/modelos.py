from dataclasses import dataclass, field


@dataclass
class Producto:
    tienda: str
    nombre: str
    precio: float | None
    url: str
    no_parte: str = ""
    upc: str = ""  # código de barras (UPC/EAN)
    mpn: str = ""  # número de parte del fabricante, si la tienda lo publica
    marca: str = ""
    precio_lista: float | None = None  # precio anterior / tachado, si existe
    precio_alterno: float | None = None  # p. ej. precio efectivo de Intelaf
    nota_precio: str = ""
    disponible: bool | None = None
    texto: str = ""  # texto extra para buscar códigos (descripción, slug, sku)
    categoria: str = ""  # categoría en la tienda (en Imeqmo, el slug sin el id: "laptops")
    categoria_nombre: str = ""
    specs: dict = field(default_factory=dict)


@dataclass
class Coincidencia:
    producto: Producto | None
    nivel: str  # ver emparejador.NIVELES
    puntaje: float = 0.0
    motivo: str = ""
    diferencias: str = ""
    nota_ia: str = ""
    candidatos: list = field(default_factory=list)  # [(puntaje, nivel, Producto, motivo)]
