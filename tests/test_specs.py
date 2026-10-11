import pytest

from comparador import specs


@pytest.mark.parametrize("texto, esperado", [
    ("Intel Core i7-1355U 16GB", "I7-1355U"),
    ("Dell, Laptop Pro15 Essential, PV15250, Corei5-1334U, 16GB", "I5-1334U"),
    ("Intel Core Ultra 7 256V", "ULTRA7-256V"),
    ("HP, Laptop 15-FD2015ST, U5-225U, 8GB", "ULTRA5-225U"),
    ("Intel Core 5 120U 8GB RAM", "CORE5-120U"),
    ("Dell, Pro C5-120U, 16GB RAM DDR5", "CORE5-120U"),
    ("Lenovo, ThinkPad E14 Gen 7, i7-240H, 16GB", "CORE7-240H"),
    ("HP, Laptop 200 G2I, 5-120U, 16GB DDR5", "CORE5-120U"),
    ("AMD Ryzen 7 7735HS 16GB RAM", "RYZEN7-7735HS"),
    ("Lenovo, LOQ, AMD R7 7735HS, 16GBRAM", "RYZEN7-7735HS"),
    ("HP, OmniBook 3 16-BY0015D, R5-40, 8GB", "RYZEN5-40"),
    ("AMD Ryzen AI 5 340 16GB RAM", "RYZENAI5-340"),
    ("HP, OmniBook 16-ag1051la, Ryzen 5-340AI, 16GB RAM", "RYZENAI5-340"),
    ("Con Procesador AMD Ryzen 9 AI HX 370 W De 2 GHz", "RYZENAI9-HX370"),
    ("ASUS, TUF A16, Ryzen AI 9, 32GB", "RYZENAI9-"),
    ("Intel Celeron N150 4GB RAM", "N150"),
    ("IDEAPAD SLIM 3 15IAN8 i3-N305 8GB RAM", "N305"),
])
def test_cpu(texto, esperado):
    assert specs.cpu(texto) == esperado


@pytest.mark.parametrize("a, b, esperado", [
    ("I7-1355U", "I7-1355U", "igual"),
    ("I5-1334U", "I7-1355U", "distinto"),
    ("ULTRA7-240H", "CORE7-240H", "igual"),  # misma CPU con distinta etiqueta
    ("ULTRA7-355", "ULTRA7-355H", "igual"),
    ("RYZENAI9-", "RYZENAI9-HX370", "desconocido"),
    ("ULTRA5-", "I7-1355U", "distinto"),
    ("RYZEN7-7735HS", "", "desconocido"),
    ("RYZEN7-170", "RYZENAI7-350", "distinto"),
])
def test_comparar_cpu(a, b, esperado):
    assert specs.comparar_cpu(a, b) == esperado


@pytest.mark.parametrize("texto, ram, alm", [
    ("Lenovo LOQ 15ARP10E 15.6\" AMD Ryzen 7 7735HS 16GB RAM 1TB SSD RTX 4050 6GB", 16, 1024),
    ("Dell, Laptop, i7-1355U, 16GB, SSD 512GB, 15.6″ 2K", 16, 512),
    ("HP,15-FD0331LA,Core3,8GBRam,512GBSSD,15.6″FHD", 8, 512),
    ("Memoria RAM DDR4 De 16GB Almacenamiento De 512GB En SSD M.2", 16, 512),
    ("Laptop Gigabyte AERO X16 Ryzen AI 7 350 16 GB DDR5 1 TB SSD RTX 5070 8 GB", 16, 1024),
    ("VICTUS 15-FA2013DX I5-13420H 8GB RAM 512GB SSD RTX 3050 6GB 15.6P W11", 8, 512),
])
def test_ram_y_almacenamiento(texto, ram, alm):
    assert specs.ram_y_almacenamiento(texto) == (ram, alm)


@pytest.mark.parametrize("texto, esperado", [
    ('Laptop HP 15-fd2050wm 15.6" Intel', 15.6),
    ("Dell, Laptop, i7-1355U, 16GB, SSD 512GB, 15.6″ 2K", 15.6),
    ("RTX 4050 6GB 15.6P W11", 15.6),
    ("IDEAPAD 5 14IAL10 ULTRA 5 225U 8GB RAM 512GB SSD 14P TOUCH", 14.0),
])
def test_pantalla(texto, esperado):
    assert specs.pantalla(texto) == esperado


def test_gpu():
    assert specs.gpu("RTX 5070 8 GB") == "RTX5070"
    assert specs.gpu("NVIDIA GeForce RTX 5070 Ti") == "RTX5070TI"
    assert specs.gpu("512GB SSD Intel UHD Graphics W11") == "INTEGRADA"
    assert specs.gpu("AMD Radeon 610M") == "INTEGRADA"
    assert specs.gpu("16GB RAM 512GB SSD") == ""


def test_tactil():
    assert specs.tactil("Laptop Dell 15 DC15250 15.6\" Touchscreen Intel Core i7")
    assert specs.tactil("HP 15-FC0027CA RYZEN 7 7730U 16GB RAM 512GB SD 15.6P TOUCH WIN 11")
    assert specs.tactil("ENVY X360 14-ES1013DX") and specs.tactil("HP, OmniBook X Flip 2-in-1, U5")
    assert not specs.tactil("Laptop HP 15-fc027la 15.6\" AMD Ryzen 7 7730U 16GB RAM 512GB SSD")


def test_marca():
    assert specs.marca("VICTUS 15-FA2013DX I5-13420H", "") == "HP"
    assert specs.marca("Alienware, m15 A7, i7-240H") == "DELL"
    assert specs.marca("cualquier cosa", "Lenovo") == "LENOVO"


def test_codigos_modelo_excluye_specs():
    codigos = specs.codigos_modelo('Laptop HP 14-hu0050la 14" Intel Core 5 120U 8GB RAM 512GB SSD RTX 5060 DDR5 144Hz')
    assert "HU0050LA" in codigos and "14HU0050LA" in codigos
    for basura in ("120U", "8GB", "512GB", "RTX5060", "DDR5", "144HZ"):
        assert basura not in codigos


def test_normalizar_caracteres_especiales():
    assert specs.normalizar("HP 15‑fd0331la 15.6″") == 'HP 15-FD0331LA 15.6"'
