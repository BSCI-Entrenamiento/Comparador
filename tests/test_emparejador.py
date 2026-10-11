from comparador import emparejador as em


def _emparejar(catalogos, no_parte, tienda, manuales=None):
    im, comp = catalogos
    return em.emparejar(im[no_parte], comp[tienda], tienda, manuales)


def test_mismo_no_parte_en_click_y_macro(catalogos):
    c = _emparejar(catalogos, "16-BY0015DX", "Click")
    assert c.nivel == em.EXACTO_ID and c.producto.precio == 4499
    c = _emparejar(catalogos, "16-BY0015DX", "MacroSistemas")
    assert c.nivel == em.EXACTO_ID and c.producto.precio == 4849


def test_hp_14_hu0050la(catalogos):
    assert _emparejar(catalogos, "D4EU0LA-ABM", "MacroSistemas").producto.precio == 5266
    c = _emparejar(catalogos, "D4EU0LA-ABM", "Intelaf")
    assert c.nivel in em.EXACTOS and "14-HU0050LA" in c.producto.nombre


def test_hp_victus_15_fa2014la(catalogos):
    for tienda in ("MacroSistemas", "Intelaf"):
        c = _emparejar(catalogos, "BA1U5LA-ABM", tienda)
        assert c.nivel in em.EXACTOS
        assert "FA2014LA" in c.producto.nombre.upper()


def test_lenovo_loq_otra_configuracion_en_click(catalogos):
    c = _emparejar(catalogos, "83S0001KGJ", "Click")
    assert c.nivel == em.SIMILAR_CONFIG
    assert "1 TB → 512 GB" in c.diferencias
    assert _emparejar(catalogos, "83S0001KGJ", "MacroSistemas").nivel in em.EXACTOS


def test_dell_pv15250_distingue_cpu(catalogos):
    c = _emparejar(catalogos, "F8T7Y", "Intelaf")  # Imeqmo i5-1334U vs Intelaf i7-1355U
    assert c.nivel == em.SIMILAR_CONFIG and "CPU" in c.diferencias
    c = _emparejar(catalogos, "9KP97", "Intelaf")  # Imeqmo i7-1355U
    assert c.nivel in em.EXACTOS


def test_no_empareja_solo_por_cpu(catalogos):
    im, comp = catalogos
    msi = next(p for p in comp["Intelaf"] if "Thin A15" in p.nombre)
    nivel, *_ = em.evaluar(im["83S0001KGJ"], msi)  # Lenovo LOQ vs MSI con la misma CPU
    assert nivel == em.SIN


def test_gpu_integrada_vs_dedicada_no_es_similar(catalogos):
    im, comp = catalogos
    nitro = next(p for p in comp["Click"] if "ANV15-52-778V" in p.nombre)
    nivel, _, _, difs = em.evaluar(im["NX-D4CAL-008"], nitro)
    assert nivel == em.SIN and "GPU" in difs


def test_otra_marca_con_mismas_specs(catalogos):
    # Dell 15 i5-1334U 8GB 512GB: MacroSistemas no tiene ese Dell, pero sí un ASUS equivalente
    c = _emparejar(catalogos, "LDC15250-5434BLK-PUS", "MacroSistemas")
    assert c.nivel == em.SIMILAR_OTRA_MARCA
    assert c.producto.specs["marca"] == "ASUS" and "Marca DELL → ASUS" in c.diferencias
    assert c.nivel in em.SIMILARES and c.nivel not in em.EXACTOS  # no entra en los totales


def test_misma_marca_tiene_prioridad_sobre_otra_marca(catalogos):
    c = _emparejar(catalogos, "83GW004UFJ", "Click")  # Lenovo V15 i5-13420H 16GB 512GB
    assert c.nivel == em.SIMILAR_SPECS and c.producto.specs["marca"] == "LENOVO"


def test_otra_marca_no_compara_gamer_con_oficina(catalogos):
    # Lenovo LOQ con RTX 5050 vs ASUS Vivobook con la misma CPU/RAM/SSD pero sin GPU dedicada
    assert _emparejar(catalogos, "83VA001PUS", "Intelaf").nivel != em.SIMILAR_OTRA_MARCA


def test_otra_marca_excluye_reacondicionados(catalogos):
    im, comp = catalogos
    reacondicionado = next(p for p in comp["Intelaf"] if p.nombre.startswith("Refurbished") and "HP" in p.nombre)
    nivel, _, _, difs = em.evaluar(im["1WH93USC94AH"], reacondicionado)
    assert nivel == em.SIN and "Reacondicionado" in difs


def test_mismo_modelo_con_otra_ram_no_es_similar(catalogos):
    # Dell 15 DC15250 i7 8GB vs el mismo modelo con 16GB: antes "Similar", ahora no
    c = _emparejar(catalogos, "83NM8", "Intelaf")
    assert c.nivel == em.SIN
    assert any("otra RAM" in motivo for _, _, _, motivo, _ in c.candidatos)


def test_mismo_modelo_con_dos_diferencias_no_es_similar(catalogos):
    # Alienware AC16250: Click trae otro SSD y otra GPU
    assert _emparejar(catalogos, "LAC16250-7469BLU-PUS", "Click").nivel == em.SIN


def test_diferencias_mayores():
    base = {"cpu": "I5-1334U", "ram": 16, "almacenamiento": 512, "pantalla": 15.6, "gpu": ""}
    assert em.diferencias_mayores(base, dict(base, almacenamiento=1024)) == []
    assert em.diferencias_mayores(base, dict(base, cpu="I7-1355U")) == []
    assert em.diferencias_mayores(base, dict(base, ram=8)) == ["otra RAM"]
    assert em.diferencias_mayores(base, dict(base, pantalla=14.0)) == ["otra pantalla"]
    assert em.diferencias_mayores(dict(base, gpu="INTEGRADA"), dict(base, gpu="RTX4050")) == [
        "GPU integrada vs. dedicada"]
    assert em.diferencias_mayores(base, dict(base, cpu="I7-1355U", almacenamiento=1024)) == [
        "más de una diferencia (CPU, almacenamiento)"]
    assert em.diferencias_mayores(base, dict(base, ram=None, pantalla=None)) == []  # datos faltantes no descartan


def test_correccion_manual(catalogos):
    im, comp = catalogos
    destino = comp["Click"][0]
    manuales = {("1WH93USC94AH", "click"): destino.url}
    c = _emparejar(catalogos, "1WH93USC94AH", "Click", manuales)
    assert c.nivel == em.EXACTO_MANUAL and c.producto is destino
    manuales = {("16BY0015DX", "click"): "NINGUNO"}
    assert _emparejar(catalogos, "16-BY0015DX", "Click", manuales).producto is None


def test_cargar_manuales(tmp_path):
    ruta = tmp_path / "m.csv"
    ruta.write_text("no_parte_imeqmo,tienda,url_competidor\n16-by0015dx,Click,NINGUNO\n,,\n", encoding="utf-8")
    assert em.cargar_manuales(ruta) == {("16BY0015DX", "click"): "NINGUNO"}
