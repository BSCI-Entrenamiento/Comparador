import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config


def nueva_sesion(reintentar_500: bool = True) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": config.USER_AGENT, "Accept-Language": "es-GT,es;q=0.9"})
    reintentos = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504) if reintentar_500 else (429, 502, 503, 504),
        allowed_methods=("GET", "POST"),
    )
    s.mount("https://", HTTPAdapter(max_retries=reintentos))
    return s


def pausa(segundos: float | None = None):
    time.sleep(config.PAUSA_ENTRE_PAGINAS_S if segundos is None else segundos)
