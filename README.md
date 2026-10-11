# Comparador de precios Imeqmo

Descarga el catálogo de **Imeqmo** (todas las categorías, salvo servicios y software) y lo compara contra los catálogos completos de **Intelaf**, **MacroSistemas** y **Click**.
Para cada producto de Imeqmo busca su equivalente en cada tienda y genera un Excel con los precios y las diferencias.

Todo corre en Python, sin navegador. Cada tienda se lee desde su propia fuente:

| Tienda | Fuente |
|---|---|
| Imeqmo | Listado HTML de cada categoría (Odoo) y página de producto (UPC y código interno) |
| Intelaf | API interna que usa su sitio web (todas las áreas del menú) y página de producto (MPN) |
| MacroSistemas | Store API pública de WooCommerce (catálogo completo) |
| Click | `products.json` público de Shopify (catálogo completo) |

**Cómo se compara según la categoría:**
- **Laptops y computadoras:** por especificaciones (CPU, RAM, almacenamiento, pantalla, GPU), además de UPC y número de parte.
- **Resto de categorías** (accesorios, UPS, toner, redes, audio, etc.): por UPC, número de parte o código de modelo. Los casos dudosos (mismo código de modelo o título parecido) los revisa la IA.

## Instalación (una vez)

```bash
pip install -r requirements.txt
```

## Uso

Todas las categorías:

```bash
python -m comparador
```

Solo algunas categorías (por el inicio de su nombre en la URL de Imeqmo):

```bash
python -m comparador laptops monitores
```

También se puede hacer doble clic en `ejecutar.bat` (todas las categorías).

- La **primera corrida** es la más larga (unos 15 minutos sin IA): lee una vez la página de cada producto de Imeqmo (UPC y código) y la de los candidatos de Intelaf (MPN). Esos datos quedan en `salidas/cache_detalles.json`.
- Las **siguientes corridas** solo leen productos nuevos. El tiempo lo domina la descarga del catálogo de Intelaf (unos 3 minutos) y la IA cuando hay casos nuevos.
- Opciones:
  - `--sin-ia`: usa solo las reglas, aunque haya credenciales de IA.
  - `--salida CARPETA`: guarda los archivos en otra carpeta.

## Qué genera (`salidas/`)

- `comparacion_todas_AAAA-MM-DD_HHMM.xlsx` (o con el nombre de las categorías elegidas), con cuatro hojas:
  - **Comparación**: una fila por producto de Imeqmo, con su **Categoría** (se puede filtrar). Por cada tienda muestra precio, diferencia (Q y %), nivel de coincidencia, producto con enlace y detalle. Al final: el precio mínimo de la competencia (solo coincidencias exactas), la tienda más barata y la posición de Imeqmo.
    - Rojo: Imeqmo está más caro. Verde: Imeqmo está más barato.
    - Gris/itálica: coincidencia "Similar", solo como referencia. No entra en los totales.
  - **Resumen**: conteos por tienda y diferencia promedio, y una tabla **por categoría**.
  - **Detalle**: los 5 mejores candidatos por tienda, con puntaje y motivo. Sirve para auditar.
  - **Catálogos**: todos los productos leídos con sus especificaciones extraídas.
- `historico.csv`: se agrega una línea por producto y tienda en cada corrida, para seguir la evolución de precios.
- `comparador.log`: registro de las corridas.

**Diferencia** = (precio Imeqmo − precio competidor) / precio competidor. Si es positiva, Imeqmo está más caro.

## Niveles de coincidencia

| Nivel | Significado |
|---|---|
| Exacto (manual) | Definido en `coincidencias_manuales.csv` |
| Exacto (no. de parte) | Coincide el UPC, el número de parte o el MPN |
| Exacto (modelo + config.) | Mismo código de modelo y misma CPU, RAM y almacenamiento |
| Exacto (IA) | La IA confirmó que es el mismo producto |
| Similar (mismo modelo, otra config.) | Mismo modelo con una sola diferencia en CPU, almacenamiento o GPU (se indica cuál) |
| Similar (mismo código de modelo) | Fuera de laptops: misma marca y mismo código de modelo en el título, sin número de parte que lo confirme. La IA decide si es el mismo producto |
| Similar (mismas specs) | Otro modelo de la misma marca con la misma CPU, RAM y almacenamiento |
| Similar (otra marca, mismas specs) | Otra marca con la misma CPU, RAM, almacenamiento, pantalla y GPU. Solo se elige si la tienda no tiene nada de la misma marca; nunca un reacondicionado |
| Similar (IA) | La IA lo considera comparable, pero no idéntico |
| Sin coincidencia | La tienda no tiene un equivalente |

**Criterio para cualquier "Similar" en laptops y computadoras**, ya sea de las reglas o de la IA:
- Mismo tamaño de pantalla.
- Misma RAM.
- No se compara GPU integrada con dedicada.
- Como máximo una diferencia entre CPU, almacenamiento o modelo de GPU.

Si la IA propone algo que no cumple este criterio, se descarta y el motivo queda en la columna Detalle.

**En las demás categorías**, la IA marca "equivalente" solo si es el mismo tipo de producto, del mismo segmento y con las características principales iguales o casi iguales (capacidad, potencia, tamaño, velocidad, rendimiento, cantidad). Puede ser de otra marca.

**En todas las categorías:** un producto de otra marca o reacondicionado nunca cuenta como "Exacto".

## Corregir coincidencias a mano

Edita `coincidencias_manuales.csv`. Estas correcciones tienen prioridad sobre las reglas y sobre la IA.

```csv
no_parte_imeqmo,tienda,url_competidor
83SC007RUS,Intelaf,https://www.intelaf.com/precios_stock_detallado/xxxx
16-BY0015DX,Click,NINGUNO
```

- `no_parte_imeqmo` es la columna "No. parte" del Excel.
- `tienda` es Intelaf, MacroSistemas o Click.
- `NINGUNO` fuerza "Sin coincidencia".

## Revisión con IA (opcional)

Si hay credenciales de Anthropic, Claude revisa **solo los casos dudosos** (los "Similar" y los "Sin coincidencia" que tienen algún candidato parecido). Puede confirmar, descartar o explicar la diferencia en español en la columna Detalle.

- Las decisiones se guardan en `salidas/cache_ia.json`, así que las corridas siguientes solo consultan productos nuevos o con cambios de precio.
- Sin credenciales, el script lo avisa y usa solo las reglas.

Para activarla, abre el archivo `.env` de esta carpeta y pega tu API key después del `=`, sin comillas:

```
ANTHROPIC_API_KEY=sk-ant-...
```

- El script lee `.env` al arrancar.
- Si la variable ya existe en Windows, esa tiene prioridad sobre el `.env`.
- El `.env` es privado. No lo compartas: está excluido en `.gitignore`, y `.env.example` es la plantilla sin clave.

Al terminar, el script muestra cuántas consultas hizo y cuántos tokens usó.

En el mismo `.env` se eligen el modelo y el esfuerzo:

```
IA_MODELO=claude-opus-5-5
IA_EFFORT=low
```

- **`IA_MODELO`**: `claude-opus-5-5` (por defecto), `claude-sonnet-5-5` o `claude-haiku-4-5`.
- **`IA_EFFORT`**: `low` (por defecto), `medium`, `high`, `xhigh` o `max`.
- **`IA_CONFIANZA_EXACTO`**: confianza mínima para que un "exacto" de la IA cuente como Exacto (por defecto `0.90`). Por debajo queda como "Similar (IA)", por ejemplo cuando solo cambia el color o la competencia no publica el número de parte.
- **`IA_MAX_CONSULTAS`**: tope de consultas nuevas por corrida (por defecto 800, unos $6 con Opus 5.5). Lo que exceda queda para la corrida siguiente; las decisiones en caché no cuentan.
- Si una línea falta o está vacía, se usa el valor por defecto.

Las consultas se hacen de 5 en 5 en paralelo (`IA_HILOS` en `config.py`).

## Configuración (`config.py`)

- `INTELAF_PRECIO`: qué precio de Intelaf se compara.
  - `"promo"` (por defecto): usa las promociones generales como "Promo ASUS", pero no los descuentos por forma de pago como "Beneficio Efectivo". Esos se muestran en la columna Detalle.
  - `"oferta"`: siempre el precio más bajo publicado.
  - `"normal"`: siempre el precio normal.
- `FUENTES`: URLs de cada tienda.
  - En `FUENTES["imeqmo"]`, `excluir` lista las categorías que no se comparan (servicios, software) y `prioridad` define a qué categoría se asigna un producto que está en varias.
  - Las categorías nuevas de Imeqmo se detectan solas.
- `CATEGORIAS_CON_SPECS`: categorías que se comparan por especificaciones de cómputo (por defecto laptops y computadoras).
- Los ajustes de IA (`IA_MODELO`, `IA_EFFORT`) y la API key van en `.env`, no en `config.py`.

## Programar la ejecución (Programador de tareas de Windows)

Ejemplo, todos los días a las 7:00:

```bash
schtasks /Create /TN "Comparador Imeqmo" /TR "C:\Proyectos\Comparador\ejecutar.bat" /SC DAILY /ST 07:00
```

## Ejecutar en Prefect Cloud (a demanda)

El archivo `flujo_prefect.py` corre la misma comparación en Prefect Cloud (plan Hobby, 500 min/mes). Como el contenedor se borra al terminar, el estado (`cache_detalles.json`, `cache_ia.json`, `historico.csv`) y los Excel se guardan en la rama **`datos`** del repositorio de GitHub:

- `reportes/`: un Excel por corrida.
- `estado/`: cachés e histórico.

La ejecución local (`python -m comparador`) sigue igual, con su propio estado en `salidas/`, separado del de Prefect.

**Preparación (una vez):**
1. Crear en GitHub un repositorio **privado** y subir este proyecto a la rama `main`.
   - El `.env` y `salidas/` no se suben: están en `.gitignore`.
   - Poner el nombre del repositorio en `REPO_DATOS` dentro de `flujo_prefect.py`.
2. Crear un *fine-grained personal access token* de GitHub solo para ese repositorio, con permisos *Contents: Read and write* y *Metadata: Read*.
3. En Prefect Cloud → **Blocks** → **Secret**, crear dos bloques:
   - `github-token`, con el token del paso 2.
   - `anthropic-api-key`, con la API key de Anthropic. Si falta, la corrida se hace sin IA.
4. (Opcional, recomendado) Subir el estado actual de la PC, para que la primera corrida en Prefect no repita la descarga de páginas ni las consultas a la IA. Requiere `GITHUB_REPO` y `GITHUB_TOKEN` en el `.env`:
   ```bash
   python -m comparador.github_datos subir-estado
   ```
5. En Prefect Cloud → **Home** → **Connect GitHub**:
   - instalar la app de Prefect solo en ese repositorio;
   - elegir el entrypoint `flujo_prefect.py:comparar_precios`;
   - indicar `requirements.txt` como dependencias.

**Uso:**
- En **Deployments**, botón **Run**.
- Parámetros:
  - `categorias`: vacío = todas; por ejemplo `["laptops", "monitores"]`.
  - `usar_ia`: activar o desactivar la revisión con IA.
- Al terminar, la corrida muestra en **Artifacts** una tabla resumen y el enlace para descargar el Excel desde GitHub.
- Los ajustes de IA son los valores por defecto de `config.py`.
- Cada corrida usa unos 7–8 minutos del plan.

## Pruebas

```bash
pip install -r requirements-dev.txt
```

```bash
python -m pytest -q
```

Las pruebas usan respuestas reales guardadas en `tests/fixtures/` y no hacen llamadas a la red ni a la IA.

## Si algo falla

- Si una tienda no responde o devuelve 0 productos, el Excel la marca como **NO DISPONIBLE** y la corrida continúa con las demás.
- Si un sitio cambia su estructura, el archivo a revisar es su módulo en `comparador/tiendas/`.
