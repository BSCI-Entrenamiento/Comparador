"""Extracción de marca, códigos y especificaciones desde títulos y descripciones."""
import math
import re
import unicodedata
from collections import Counter

MARCAS = ["HP", "DELL", "LENOVO", "ASUS", "ACER", "MSI", "GIGABYTE", "APPLE", "SAMSUNG",
          "HUAWEI", "MICROSOFT", "TOSHIBA", "DYNABOOK", "GATEWAY", "XIAOMI", "LG"]
SERIES_MARCA = {
    "HP": r"OMNIBOOK|VICTUS|OMEN|PAVILION|ELITEBOOK|PROBOOK|ENVY|SPECTRE|ZBOOK",
    "LENOVO": r"IDEAPAD|THINKPAD|THINKBOOK|LOQ|LEGION|YOGA",
    "ASUS": r"VIVOBOOK|ZENBOOK|TUF|ROG|PROART|EXPERTBOOK",
    "DELL": r"INSPIRON|LATITUDE|VOSTRO|XPS|ALIENWARE",
    "ACER": r"ASPIRE|NITRO|PREDATOR|SWIFT|TRAVELMATE",
    "MSI": r"KATANA|CYBORG|PRESTIGE|STEALTH|RAIDER|CROSSHAIR|SWORD|BRAVO",
    "APPLE": r"MACBOOK",
    "GIGABYTE": r"AORUS",
}
RAM_VALIDAS = {4, 8, 12, 16, 18, 24, 32, 36, 48, 64, 96, 128}


def normalizar(texto: str) -> str:
    t = texto or ""
    for a, b in (("‑", "-"), ("‐", "-"), ("–", "-"), ("—", "-"),
                 ("″", '"'), ("”", '"'), ("“", '"'), ("′′", '"'), ("''", '"')):
        t = t.replace(a, b)
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t.upper()).strip()


def compacto(texto: str) -> str:
    """Solo letras y números: 'D5CD0UA#ABA' -> 'D5CD0UAABA'."""
    return re.sub(r"[^A-Z0-9]", "", normalizar(texto))


# ---------------------------------------------------------------- marca
# Las marcas se comparan en forma compacta ("TP LINK" = "TP-Link" = "TPLINK").
_ALIAS_MARCA = {"HEWLETTPACKARD": "HP", "HPINC": "HP", "HPE": "HP", "LAMBORGHIN": "LAMBORGHINI"}
_NO_SON_MARCA = {"CLICK", "GENERICO", "GENERICA", "OTROS", "OTRO", "VARIOS", "NA", "SINMARCA", "DEFAULT"}
_vocabulario: dict[str, str] = {}  # frase normalizada -> marca canónica
_patron_vocabulario = None


def _solo_palabras(texto: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", normalizar(texto)).strip()


def canonica_marca(nombre: str) -> str:
    c = compacto(nombre)
    c = _ALIAS_MARCA.get(c, c)
    for mk, patron in SERIES_MARCA.items():  # submarcas: "ALIENWARE" -> DELL, "ROG" -> ASUS
        if re.fullmatch(patron, c):
            return mk
    return "" if c in _NO_SON_MARCA else c


def registrar_marcas(nombres) -> None:
    """Agrega al vocabulario las marcas declaradas por las tiendas (para detectarlas en títulos)."""
    global _patron_vocabulario
    for n in nombres:
        frase, canon = _solo_palabras(n), canonica_marca(n)
        if canon and len(canon) >= 3 and not canon.isdigit():
            _vocabulario[frase] = canon
            _vocabulario[canon] = canon  # "KLIPXTREME" también se reconoce escrito junto
    _patron_vocabulario = None


_PATRON_MARCAS = re.compile(r"\b(" + "|".join(MARCAS) + r")\b")
_PATRONES_SERIE = [(mk, re.compile(rf"\b(?:{p})\b")) for mk, p in SERIES_MARCA.items()]


def _patron_del_vocabulario():
    global _patron_vocabulario
    if _patron_vocabulario is None and _vocabulario:
        frases = sorted(_vocabulario, key=len, reverse=True)
        _patron_vocabulario = re.compile(r"\b(" + "|".join(re.escape(f) for f in frases) + r")\b")
    return _patron_vocabulario


def marca(texto: str, marca_declarada: str = "") -> str:
    """Marca canónica: la declarada por la tienda o, si no hay, la primera que aparece en el título
    ("Cargador Klip Xtreme para laptop HP" -> KLIPXTREME)."""
    declarada = canonica_marca(marca_declarada) if marca_declarada else ""
    if declarada:
        return declarada
    t = _solo_palabras(texto)  # "TP-Link" -> "TP LINK", igual que el vocabulario
    encontradas = []  # (posición, marca)
    m = _PATRON_MARCAS.search(t)
    if m:
        encontradas.append((m.start(), m[1]))
    for mk, patron in _PATRONES_SERIE:
        m = patron.search(t)
        if m:
            encontradas.append((m.start(), mk))
    vocab = _patron_del_vocabulario()
    m = vocab.search(t) if vocab else None
    if m:
        encontradas.append((m.start(), _vocabulario[m[1]]))
    return min(encontradas)[1] if encontradas else ""


# ---------------------------------------------------------------- palabras (similitud de títulos)
_VACIAS = {"DE", "CON", "PARA", "Y", "EL", "LA", "LOS", "LAS", "EN", "A", "POR", "DEL", "AL", "UN", "UNA",
           "MARCA", "MODELO", "COLOR", "TIPO", "INCLUYE", "PROCESADOR", "MEMORIA", "ALMACENAMIENTO"}


def palabras(texto: str) -> list[str]:
    """Palabras significativas de un título, para la similitud TF-IDF."""
    t = re.sub(r"[^A-Z0-9.]+", " ", normalizar(texto))
    return [w.strip(".") for w in t.split() if w.strip(".") and w.strip(".") not in _VACIAS]


class IndiceTitulos:
    """Similitud coseno TF-IDF entre títulos, con índice invertido (sin dependencias externas)."""

    def __init__(self, documentos: list[list[str]]):
        n = len(documentos)
        df = Counter(w for doc in documentos for w in set(doc))
        self.idf = {w: math.log((n + 1) / (c + 1)) + 1 for w, c in df.items()}
        self.invertido: dict[str, list[tuple[int, float]]] = {}
        for i, doc in enumerate(documentos):
            for w, peso in self._vector(doc).items():
                self.invertido.setdefault(w, []).append((i, peso))

    def _vector(self, doc: list[str]) -> dict[str, float]:
        tf = Counter(doc)
        v = {w: c * self.idf.get(w, 0.0) for w, c in tf.items() if w in self.idf}
        norma = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {w: x / norma for w, x in v.items()}

    def similares(self, doc: list[str], k: int = 20, minimo: float = 0.15) -> list[tuple[int, float]]:
        puntajes: Counter = Counter()
        for w, peso in self._vector(doc).items():
            for i, p in self.invertido.get(w, ()):
                puntajes[i] += peso * p
        return [(i, s) for i, s in puntajes.most_common(k) if s >= minimo]


# ---------------------------------------------------------------- CPU
_CPU_PATRONES = [
    # Intel Core Ultra: "CORE ULTRA 7 256V", "ULTRA 5 225U", "U5-225U", "U7 255U"
    (r"\b(?:CORE\s*)?(?:ULTRA\s*|U)([579])[\s-]+(\d{3}[A-Z]{0,2})\b", lambda m: f"ULTRA{m[1]}-{m[2]}"),
    # Intel Core i: "I7-1355U", "COREI5-1334U", "CORE I5 13420H"
    (r"(?:\b|CORE)I([3579])[\s-]*(\d{4,5}[A-Z]{0,3})\b", lambda m: f"I{m[1]}-{m[2]}"),
    # Intel Core (serie 1/2): "CORE 5 120U", "C5-120U", "CORE 9-270H", "CORE 3 100U"
    (r"\b(?:CORE\s*|C)([3579])[\s-]+(\d{3}[A-Z]{1,2})\b", lambda m: f"CORE{m[1]}-{m[2]}"),
    # Intel Core serie 2 escrito como "i7-240H"
    (r"(?:\b|CORE)I([3579])-(\d{3}[A-Z]{1,2})\b", lambda m: f"CORE{m[1]}-{m[2]}"),
    # "RYZEN 5-340AI"
    (r"\bRYZEN\s*([3579])[\s-]+(\d{3})\s*AI\b", lambda m: f"RYZENAI{m[1]}-{m[2]}"),
    # AMD Ryzen AI: "RYZEN AI 7 350", "RYZEN AI 9 HX 370", "RYZEN 9 AI HX 370"
    (r"\bRYZEN\s*(?:AI\s*([3579])|([3579])\s*AI)\s*(HX\s*)?(\d{3})\b",
     lambda m: f"RYZENAI{m[1] or m[2]}-{'HX' if m[3] else ''}{m[4]}"),
    # AMD Ryzen: "RYZEN 7 7735HS", "R7 7735HS", "R5-7530U", "RYZEN 5 40", "RYZEN 7 170"
    (r"\b(?:RYZEN\s*|R)([3579])[\s-]+(\d{2,4}[A-Z]{0,2})\b", lambda m: f"RYZEN{m[1]}-{m[2]}"),
    # Intel Core sin la palabra "Core": ", 5-120U,", ", 9-270H,"
    (r"(?:^|[,;]\s*)([3579])-(\d{3}[UHPV]{1,2})\b", lambda m: f"CORE{m[1]}-{m[2]}"),
    # Intel N / Celeron: "CELERON N150", "I3-N305", "INTEL N100"
    (r"\b(?:CELERON|PENTIUM|INTEL|I3)[\s-]*(N\d{3,4})\b", lambda m: m[1]),
    # Apple: "CHIP M4 PRO", "APPLE M3"
    (r"\b(?:CHIP|APPLE)\s+(M[1-9])(\s+(?:PRO|MAX))?\b", lambda m: f"APPLE-{m[1]}{(m[2] or '').strip()}"),
    # Snapdragon X
    (r"\b(X1[EP])[\s-]*(\d{2})[\s-]*(\d{3})\b", lambda m: f"SNAPDRAGON-{m[1]}{m[2]}{m[3]}"),
]


# Solo la familia, cuando el título no trae el modelo: "RYZEN AI 9,", "U5,", "CORE I7,"
_CPU_FAMILIA = [
    (r"\bRYZEN\s*AI\s*([3579])\b", lambda m: f"RYZENAI{m[1]}-"),
    (r"\b(?:CORE\s*)?(?:ULTRA\s*|U)([579])\b", lambda m: f"ULTRA{m[1]}-"),
    (r"\b(?:RYZEN\s*|R)([3579])\b", lambda m: f"RYZEN{m[1]}-"),
    (r"(?:\b|CORE\s*)I([3579])\b", lambda m: f"I{m[1]}-"),
    (r"\bCORE\s*([3579])\b", lambda m: f"CORE{m[1]}-"),
]


def cpu(texto: str) -> str:
    """CPU canónica 'FAMILIA-MODELO' (p. ej. 'I7-1355U'); 'FAMILIA-' si falta el modelo."""
    t = normalizar(texto)
    for patron, fmt in _CPU_PATRONES:
        m = re.search(patron, t)
        if m:
            return fmt(m)
    for patron, fmt in _CPU_FAMILIA:
        m = re.search(patron, t)
        if m:
            return fmt(m)
    return ""


def comparar_cpu(a: str, b: str) -> str:
    """'igual', 'distinto' o 'desconocido' (falta el dato o solo se conoce la familia)."""
    if not a or not b:
        return "desconocido"
    va, ta, ma = _partes_cpu(a)
    vb, tb, mb = _partes_cpu(b)
    if va != vb:
        return "distinto"
    if not ma or not mb:
        return "distinto" if (ta and tb and ta != tb) else "desconocido"
    # Intel reutiliza el número de modelo con distintas etiquetas ("Core 7 240H" /
    # "Core Ultra 7 240H"): se compara solo el número y el sufijo.
    if va != "INTEL" and ta != tb:
        return "distinto"
    da, sa = re.match(r"([A-Z]*\d+)([A-Z]*)", ma).groups() if re.match(r"[A-Z]*\d+", ma) else (ma, "")
    db, sb = re.match(r"([A-Z]*\d+)([A-Z]*)", mb).groups() if re.match(r"[A-Z]*\d+", mb) else (mb, "")
    if da != db:
        return "distinto"
    return "igual" if (sa == sb or not sa or not sb) else "distinto"


def _partes_cpu(c: str) -> tuple[str, str, str]:
    """'ULTRA7-255U' -> ('INTEL', '7', '255U'); 'RYZENAI5-340' -> ('AMD-AI', '5', '340')."""
    familia, _, modelo = c.partition("-")
    m = re.match(r"(ULTRA|CORE|I|RYZENAI|RYZEN)(\d)$", familia)
    if not m:
        return familia, "", modelo
    vendor = {"ULTRA": "INTEL", "CORE": "INTEL", "I": "INTEL", "RYZENAI": "AMD-AI", "RYZEN": "AMD"}[m[1]]
    return vendor, m[2], modelo


# ---------------------------------------------------------------- RAM / almacenamiento
_CTX_RAM = re.compile(r"RAM|DDR|MEMORIA|LPDDR")
_CTX_GPU = re.compile(r"RTX|GTX|GDDR|VIDEO|GRAFICOS|RADEON RX|ARC")


def ram_y_almacenamiento(texto: str) -> tuple[int | None, int | None]:
    t = normalizar(texto)
    ram, alm, sin_clasificar = [], [], []
    for m in re.finditer(r"(\d{1,4})\s*(GB|TB)\b|(\d{1,4})\s*(GB|TB)(?=[A-Z])", t):
        valor = int(m[1] or m[3])
        unidad = m[2] or m[4]
        gb = valor * 1024 if unidad == "TB" else valor
        antes, despues = t[max(0, m.start() - 28):m.start()], t[m.end():m.end() + 14]
        antes_cerca = t[max(0, m.start() - 12):m.start()]
        if _CTX_GPU.search(antes_cerca) and not _CTX_RAM.search(antes_cerca):
            continue
        if (unidad == "TB" or re.match(r"\s*(EN\s+)?(SSD|EMMC|UFS|HDD|NVME|M\.2|PCIE|DE ALMACENAMIENTO)", despues)
                or re.search(r"(SSD|ALMACENAMIENTO|HDD|EMMC|UFS)\W*(DE\s*)?$", antes)):
            alm.append(gb)
        elif (re.match(r"\s*(DE\s+)?(RAM|DDR|LPDDR|MEMORIA)", despues)
                or re.search(r"(RAM|MEMORIA|DDR\d X?)[^,;]*$", antes[-20:])):
            ram.append(gb)
        else:
            sin_clasificar.append(gb)
    for gb in sin_clasificar:
        if not ram and gb in RAM_VALIDAS and gb < 128:
            ram.append(gb)
        elif not alm and gb >= 128:
            alm.append(gb)
    return (ram[0] if ram else None), (max(alm) if alm else None)


# ---------------------------------------------------------------- pantalla / GPU
def pantalla(texto: str) -> float | None:
    t = normalizar(texto)
    m = re.search(r'\b(1[0-8](?:[.,]\d)?)\s*(?:"|PULGADAS|PULG|P\b|IN\b|INCH|PANTALLA)', t)
    if not m:
        m = re.search(r"PANTALLA\s+(?:DE\s+)?(1[0-8](?:[.,]\d)?)\b", t)
    return float(m[1].replace(",", ".")) if m else None


_GPU_INTEGRADA = re.compile(
    r"\b(INTEL\s+(UHD|IRIS|ARC|GRAPHICS|GRAFICOS)|UHD\s+GRAPHICS|IRIS\s+XE|RADEON\s+(GRAPHICS|\d{3}M)"
    r"|AMD\s+RADEON(?!\s+RX)|GRAFICOS\s+INTEGRADOS|INTEGRATED)"
)


def gpu(texto: str) -> str:
    """'RTX5060', 'INTEGRADA' si el título declara gráficos integrados, o '' si no lo dice."""
    t = normalizar(texto)
    m = re.search(r"\b(RTX|GTX)\s*(?:A)?(\d{4})(\s*TI)?\b", t)
    if m:
        return f"{m[1]}{m[2]}{'TI' if m[3] else ''}"
    return "INTEGRADA" if _GPU_INTEGRADA.search(t) else ""


# ---------------------------------------------------------------- códigos de modelo
_NO_ES_CODIGO = re.compile(
    r"^(\d{2,5}[A-Z]{0,3}"  # 7735HS, 13620H, 225U
    r"|[IUCR][3579]\d{3,5}[A-Z]{0,3}"  # I71355U, U5225U, R77735HS
    r"|(ULTRA|CORE|RYZEN|INTEL|AMD|AI)\w*"
    r"|\d+(GB|TB|HZ|W|WH|MAH|MP|MM|NITS|RPM)"
    r"|(LP)?DDR\d+X?|GDDR\d+X?"
    r"|(RTX|GTX|RX)\d+\w*"
    r"|WIN1[01]\w*|W1[01]\w*"
    r"|\d+X\d+"
    r"|GEN\d+\w*|WIFI\d\w*|USB\w*|HDMI\w*|PCIE\w*|NVME\w*|M2\w*"
    r"|N\d{3,4}|X1[EP]\d+|I[3579]N\d{3,4}|\d+[MG]BPS|GEFORCE\w*|RADEON\w*)$"
)


def _es_codigo(token_compacto: str) -> bool:
    return (
        len(token_compacto) >= 5
        and re.search(r"[A-Z]", token_compacto) is not None
        and re.search(r"\d", token_compacto) is not None
        and not _NO_ES_CODIGO.match(token_compacto)
    )


def codigos_modelo(texto: str) -> set[str]:
    """Tokens que parecen códigos de modelo/parte, en forma compacta."""
    t = normalizar(texto)
    codigos = set()
    for token in re.findall(r"[A-Z0-9]+(?:[-/#.][A-Z0-9]+)*", t):
        partes = [token] + re.split(r"[-/#.]", token)
        for parte in partes:
            c = re.sub(r"[^A-Z0-9]", "", parte)
            if _es_codigo(c):
                codigos.add(c)
    return codigos


_TACTIL = re.compile(r"\b(TOUCH\w*|TACTIL|X360|FLIP|2[\s-]*(EN|IN)[\s-]*1)\b")


def tactil(texto: str) -> bool:
    """True si el título declara pantalla táctil o convertible."""
    return bool(_TACTIL.search(normalizar(texto)))


def extraer(nombre: str, marca_declarada: str = "", extra: str = "") -> dict:
    """Specs de un producto. `extra` (descripción) solo se usa si el nombre no trae el dato."""
    ram, alm = ram_y_almacenamiento(nombre)
    ram_x, alm_x = ram_y_almacenamiento(extra) if extra else (None, None)
    cpu_titulo = cpu(nombre)
    return {
        "marca": marca(nombre, marca_declarada),
        # computadora: el título trae CPU o RAM y almacenamiento (para comparar entre marcas por specs)
        "es_computo": bool(cpu_titulo) or (ram is not None and alm is not None),
        "palabras": palabras(nombre),
        "cpu": cpu_titulo or (cpu(extra) if extra else ""),
        "ram": ram if ram is not None else ram_x,
        "almacenamiento": alm if alm is not None else alm_x,
        "pantalla": pantalla(nombre) or (pantalla(extra) if extra else None),
        "gpu": gpu(nombre) or (gpu(extra) if extra else ""),
        "tactil": tactil(nombre),
        "codigos": codigos_modelo(nombre),
    }
