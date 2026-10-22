import pandas as pd
import pytest

from monitor import analytics, report, store


def test_ratio_is_calibrated_from_trade_data(synthetic_wide, cfg):
    res = analytics.compute(synthetic_wide, cfg)
    assert res.meta["ratio_calibrado"]
    assert res.meta["ratio_colombia_newcastle"] == pytest.approx(0.9)
    # meses sin Comtrade se estiman como Newcastle x ratio
    last = res.monthly.iloc[-1]
    assert last["carbon_col_fob_fuente"] == "nowcast_newcastle"
    assert last["carbon_col_fob"] == pytest.approx(last["carbon_newcastle_fob"] * 0.9)


def test_landed_cost_build_up(synthetic_wide, cfg):
    m = analytics.compute(synthetic_wide, cfg).monthly
    r = m.iloc[-1]
    d = cfg["destino"]
    cif = (r["carbon_col_fob"] + r["carbon_flete"]) * (1 + d["seguro_pct"] / 100)
    assert r["carbon_cif"] == pytest.approx(cif)
    port = sum(d["costos_portuarios_usd_t"].values())
    assert r["carbon_landed"] == pytest.approx(cif * (1 + d["agente_aduanas_pct"] / 100) + port)
    assert r["carbon_landed_pen"] == pytest.approx(r["carbon_landed"] * r["fx_pen_usd"])
    assert r["carbon_usd_gj"] == pytest.approx(r["carbon_landed"] / (6000 * 4.1868e-3))


def test_freight_calibrated_to_implied(synthetic_wide, cfg):
    res = analytics.compute(synthetic_wide, cfg)
    # flete implícito escoria = 40 USD/t; el modelo calibrado debe acercarse
    m = res.monthly.iloc[:-4]
    assert (m["escoria_flete"] / 40).median() == pytest.approx(1.0, rel=0.02)
    assert res.monthly.iloc[-1]["escoria_fob_fuente"] == "arrastre_ultimo_dato"


def test_manual_quotes_override(synthetic_wide, cfg):
    w = synthetic_wide.copy()
    w.loc[w.index[-1], "manual_carbon_fob"] = 99.0
    w.loc[w.index[-1], "manual_flete_escoria"] = 50.0
    r = analytics.compute(w, cfg).monthly.iloc[-1]
    assert r["carbon_col_fob"] == pytest.approx(99.0)
    assert r["escoria_flete"] == pytest.approx(50.0)


def test_alerts_on_jump_and_budget(synthetic_wide, cfg):
    w = synthetic_wide.copy()
    w.loc[w.index[-1], "carbon_newcastle_fob"] *= 1.5
    cfg["materiales"]["carbon"]["presupuesto_landed_usd_t"] = 100
    alerts = analytics.compute(w, cfg).alerts
    assert any("Newcastle" in a and "m/m" in a for a in alerts)
    assert any("supera el presupuesto" in a for a in alerts)


def test_empty_history(cfg):
    res = analytics.compute(pd.DataFrame(), cfg)
    assert res.monthly.empty and res.alerts


def test_store_roundtrip_and_report(tmp_path, synthetic_wide, cfg):
    long = synthetic_wide.stack().dropna().rename("valor").reset_index()
    long.columns = ["fecha", "serie", "valor"]
    long["unidad"], long["fuente"] = "x", "test"
    path = tmp_path / "series.csv"
    store.upsert(path, long)
    # una revisión del mismo mes sobrescribe sin duplicar
    rev = long.iloc[[0]].assign(valor=1.0)
    hist = store.upsert(path, rev)
    assert len(hist) == len(long)
    w = store.wide(hist)
    assert w.iloc[0][long.iloc[0]["serie"]] == 1.0

    res = analytics.compute(store.wide(store.load(path)), cfg)
    files = report.charts(res, tmp_path / "graficos")
    md = report.render(res, cfg, "comentario de prueba", files)
    assert "Resumen puesto en planta" in md and "carbon.png" in files
    assert "comentario de prueba" in md
