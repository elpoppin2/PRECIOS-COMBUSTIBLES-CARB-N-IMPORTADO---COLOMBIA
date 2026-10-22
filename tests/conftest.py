import numpy as np
import pandas as pd
import pytest

from monitor.config import load_config


@pytest.fixture
def cfg():
    return load_config()


@pytest.fixture
def synthetic_wide():
    """Histórico sintético de 30 meses con la forma que produce store.wide()."""
    idx = pd.date_range("2024-04-01", periods=30, freq="MS")
    t = np.arange(len(idx))
    newc = 120 + 10 * np.sin(t / 4)
    w = pd.DataFrame({
        "carbon_newcastle_fob": newc,
        "brent": 80 + 5 * np.cos(t / 5),
        "fx_pen_usd": 3.7 - 0.005 * t,
        "fx_jpy_usd": 150 + t * 0.2,
    }, index=idx)
    # Comtrade con rezago: sólo hasta 4 meses antes del final
    lag = slice(0, len(idx) - 4)
    w.loc[idx[lag], "co_exp_carbon_pe_fob_usd_t"] = newc[lag] * 0.9
    w.loc[idx[lag], "pe_imp_carbon_col_cif_usd_t"] = newc[lag] * 0.9 + 26
    w.loc[idx[lag], "jp_exp_escoria_pe_fob_usd_t"] = 24.0
    w.loc[idx[lag], "pe_imp_escoria_jpn_cif_usd_t"] = 24.0 + 40
    w.loc[idx[lag], "pe_imp_clinker_mundo_cif_usd_t"] = 60.0
    return w
