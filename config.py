"""Configuración del comparador: fuentes por tienda y categoría, y ajustes de IA.

Los valores privados o propios de cada equipo (API key, modelo de IA) se leen del archivo .env.
"""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent


def cargar_env(ruta: Path) -> bool:
    """Carga variables desde .env sin pisar las ya definidas en el sistema."""
    if not ruta.exists():
        return False
    from dotenv import load_dotenv

    load_dotenv(ruta, override=False)
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "IA_MODELO", "IA_EFFORT"):
        if var in os.environ and not os.environ[var].strip():
            del os.environ[var]  # una línea vacía en .env equivale a no definirla
    return True


cargar_env(RAIZ / ".env")

# Hora de Guatemala (UTC-6, sin horario de verano) para nombres de archivo, reportes e histórico.
# Prefect corre en servidores con hora UTC; así las fechas no dependen de dónde se ejecute.
ZONA_HORARIA = timezone(timedelta(hours=-6), "America/Guatemala")


def ahora() -> datetime:
    """Fecha y hora actual en Guatemala (sin zona adjunta, para formatear igual que antes)."""
    return datetime.now(ZONA_HORARIA).replace(tzinfo=None)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
TIMEOUT_S = 30
PAUSA_ENTRE_PAGINAS_S = 1.0
PAUSA_DETALLE_S = 0.5  # entre páginas de producto (solo productos nuevos; el resto sale de caché)

# Intelaf publica "Precio normal" y a veces un precio de oferta ("Promo ASUS", "Beneficio Efectivo").
#   "promo":  usa la oferta solo si es una promoción general; los beneficios por forma de pago
#             (efectivo, contado, tarjeta) no cuentan, porque Imeqmo publica un solo precio.
#   "oferta": usa siempre el precio más bajo publicado.
#   "normal": usa siempre el precio normal.
INTELAF_PRECIO = "promo"
FORMAS_DE_PAGO = ("EFECTIVO", "CONTADO", "TARJETA", "CUOTAS", "DEPOSITO", "TRANSFERENCIA")

TIENDAS_COMPETENCIA = ["Intelaf", "MacroSistemas", "Click"]

# Fuentes. Imeqmo se recorre por categoría (descubiertas automáticamente en la tienda);
# de la competencia se descarga el catálogo completo y se buscan equivalentes en todo él.
FUENTES = {
    "imeqmo": {
        "url_tienda": "https://imeqmo.com/shop",
        "ppg": 100,
        # Prefijos de categorías que no se comparan (no tienen equivalente en estas tiendas)
        "excluir": ("servicios-corporativos", "software", "vapes"),
        # Si un producto está en varias categorías, se queda con la primera de esta lista
        "prioridad": ("laptops", "computadoras", "tablets", "monitores", "impresoras", "componentes"),
    },
    "click": {
        "url": "https://click.gt/products.json",
        "base_producto": "https://click.gt/products/",
    },
    "macrosistemas": {
        "url": "https://www.macrosistemas.com/wp-json/wc/store/v1/products",
        "categoria": None,  # None = catálogo completo
    },
    "intelaf": {
        "url": "https://api.intelaf.com:2053/app/api/producto/busqueda",
        "url_menu": "https://api.intelaf.com:2053/app/api/Menu",
        "areas": "todas",  # o una lista, p. ej. ["notebooks"]
        "base_producto": "https://www.intelaf.com/precios_stock_detallado/",
        "pausa": 0.15,
    },
}

# Categorías de Imeqmo que se comparan por especificaciones (CPU, RAM, almacenamiento, pantalla, GPU).
# El resto se compara por identificadores (UPC, número de parte, modelo) y similitud de título.
CATEGORIAS_CON_SPECS = ("laptops", "computadoras")

HILOS_DETALLE = 4  # páginas de producto descargadas en paralelo (solo productos nuevos)

# Repositorio de GitHub donde Prefect guarda reportes y estado (rama "datos")
GITHUB_REPO = os.getenv("GITHUB_REPO", "").strip() or "BSCI-Entrenamiento/Comparador"

INTELAF_HEADERS = {
    "content-type": "application/json",
    "app-name": "intelaf-web",
    "app-version": "1.2.2",
    "Origin": "https://www.intelaf.com",
    "Referer": "https://www.intelaf.com/",
}

# --- Revisión opcional con IA (Claude) ---
# Se definen en .env (IA_MODELO, IA_EFFORT); estos son los valores si no están ahí.
IA_MODELO = os.getenv("IA_MODELO", "claude-opus-5-5").strip()
IA_EFFORT = os.getenv("IA_EFFORT", "low").strip().lower()
if IA_EFFORT not in ("low", "medium", "high", "xhigh", "max"):
    raise ValueError(f"IA_EFFORT inválido en .env: {IA_EFFORT!r} (usa low, medium, high, xhigh o max)")
IA_MAX_CANDIDATOS = 5
IA_MAX_TOKENS = 8000
IA_HILOS = 5  # consultas simultáneas
# Tope de consultas NUEVAS por corrida (las de caché no cuentan), para acotar el costo.
# ~$0,008 por consulta con Opus 5.5. Lo que exceda se revisa en la corrida siguiente.
IA_MAX_CONSULTAS = int(os.getenv("IA_MAX_CONSULTAS", "800"))
# Confianza mínima para que un "exacto" de la IA cuente como Exacto; por debajo queda como Similar
# (p. ej. otro color, o la competencia no publica el número de parte).
IA_CONFIANZA_EXACTO = float(os.getenv("IA_CONFIANZA_EXACTO", "0.90"))
