from deparadar.actualizar import validar


def test_scraping_normal_pasa():
    assert validar({"venta": 900, "alquiler": 820}, {"venta": 925, "alquiler": 844}) == []


def test_scraping_bloqueado_se_descarta():
    problemas = validar({"venta": 120, "alquiler": 844}, {"venta": 925, "alquiler": 844})
    assert len(problemas) == 1 and problemas[0].startswith("venta")


def test_minimo_absoluto_aunque_no_haya_historia():
    assert validar({"venta": 40, "alquiler": 300}, {}) == ["venta: solo 40 avisos limpios (mínimo 100)"]
