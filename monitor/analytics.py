"""Modelo de costo puesto en Conchán, ratios e indicadores.

Lógica de precios (de mayor a menor prioridad):

Carbón Colombia FOB
  1. Cotización propia FOB (data/manual)
  2. Valor unitario FOB de exportaciones de Colombia a Perú / al mundo (Comtrade)
  3. Pink Sheet "Coal, Colombian" (si el Banco Mundial la publica)
  4. Nowcast: Newcastle (IMF/FRED) x ratio Colombia/Newcastle calibrado
Escoria Japón FOB
  1. Cotización propia FOB
  2. Valor unitario FOB de exportaciones de Japón a Perú / al mundo (Comtrade)
  3. Último dato conocido (arrastre) o valor por defecto de la config
Flete
  1. Cotización propia
  2. Modelo flete_base x (Brent / Brent_base)^elasticidad, recalibrado con el
     flete implícito CIF Perú - FOB origen de Comtrade
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

KCAL_TO_GJ = 4.1868e-6          # GJ por kcal
GJ_PER_BBL = 6.12               # contenido energético aproximado de un barril de Brent

KEY_SERIES = {
    "carbon_newcastle_fob": "Carbón Newcastle FOB (USD/t)",
    "carbon_col_fob": "Carbón Colombia FOB, spec contrato (USD/t)",
    "carbon_flete": "Flete Colombia→Conchán (USD/t)",
    "carbon_cif": "Carbón CIF Conchán (USD/t)",
    "carbon_landed": "Carbón puesto en planta (USD/t)",
    "carbon_landed_pen": "Carbón puesto en planta (PEN/t)",
    "carbon_usd_gj": "Carbón puesto en planta (USD/GJ)",
    "escoria_fob": "Escoria Japón FOB (USD/t)",
    "escoria_flete": "Flete Japón→Conchán (USD/t)",
    "escoria_cif": "Escoria CIF Conchán (USD/t)",
    "escoria_landed": "Escoria puesta en planta (USD/t)",
    "escoria_landed_pen": "Escoria puesta en planta (PEN/t)",
    "brent": "Brent (USD/bbl)",
    "fx_pen_usd": "Tipo de cambio (PEN/USD)",
    "fx_jpy_usd": "Tipo de cambio (JPY/USD)",
    "fx_cop_usd": "Tipo de cambio (COP/USD)",
}

RATIOS = {
    "ratio_col_newcastle": "Carbón Colombia FOB / Newcastle",
    "paridad_carbon_brent": "Carbón vs Brent (USD/GJ ÷ USD/GJ)",
    "flete_share_carbon": "Flete / CIF carbón",
    "flete_share_escoria": "Flete / CIF escoria",
    "ratio_escoria_clinker": "Escoria CIF / Clinker CIF importado",
    "ratio_escoria_carbon": "Escoria landed / Carbón landed",
    "carbon_vs_cif_comtrade": "Carbón CIF modelo / CIF Comtrade Perú",
    "escoria_vs_cif_comtrade": "Escoria CIF modelo / CIF Comtrade Perú",
}


@dataclass
class Result:
    monthly: pd.DataFrame
    indicators: pd.DataFrame
    alerts: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


def _col(w: pd.DataFrame, name: str) -> pd.Series:
    return w[name] if name in w.columns else pd.Series(np.nan, index=w.index, dtype=float)


def _first(w: pd.DataFrame, names: list[str]) -> tuple[pd.Series, pd.Series]:
    """Combina series por prioridad. Devuelve (valor, nombre de la fuente usada)."""
    value = pd.Series(np.nan, index=w.index, dtype=float)
    source = pd.Series(None, index=w.index, dtype=object)
    for n in names:
        s = _col(w, n)
        fill = value.isna() & s.notna()
        value[fill] = s[fill]
        source[fill] = n
    return value, source


def _recent_median(s: pd.Series, n: int = 12) -> float | None:
    s = s.replace([np.inf, -np.inf], np.nan).dropna()
    return float(s.tail(n).median()) if not s.empty else None


def _freight(brent: pd.Series, fcfg: dict, implied: pd.Series,
             manual: pd.Series) -> tuple[pd.Series, float]:
    model = fcfg["base_usd_t"] * (brent / fcfg["brent_base_usd_bbl"]) ** fcfg["elasticidad_bunker"]
    model = model.fillna(fcfg["base_usd_t"])
    implied = implied.where((implied > 3) & (implied < 150))     # descarta valores absurdos
    scale = _recent_median(implied / model) or 1.0
    scale = float(np.clip(scale, 0.5, 2.0))
    return manual.combine_first(model * scale), scale


def _landed(cif: pd.Series, dcfg: dict, arancel_pct: float) -> pd.Series:
    port = sum(dcfg["costos_portuarios_usd_t"].values())
    return cif * (1 + arancel_pct / 100 + dcfg["agente_aduanas_pct"] / 100) + port


def compute(w: pd.DataFrame, cfg: dict) -> Result:
    if w.empty:
        return Result(pd.DataFrame(), pd.DataFrame(), ["Sin datos todavía: ejecuta `python -m monitor update`."])

    w = w.sort_index()
    dcfg = cfg["destino"]
    ccfg, ecfg = cfg["materiales"]["carbon"], cfg["materiales"]["escoria"]
    seguro = dcfg["seguro_pct"] / 100
    m = pd.DataFrame(index=w.index)

    # --- Mercado y tipos de cambio -------------------------------------------------
    m["carbon_newcastle_fob"], _ = _first(w, ["carbon_newcastle_fob", "carbon_bm_australia_fob"])
    m["brent"], _ = _first(w, ["brent", "brent_bm"])
    m["brent"] = m["brent"].ffill()
    for fx in ("fx_pen_usd", "fx_jpy_usd", "fx_cop_usd"):
        m[fx] = _col(w, fx).ffill()

    # --- Carbón Colombia ----------------------------------------------------------
    trade_fob, _ = _first(w, ["co_exp_carbon_pe_fob_usd_t", "co_exp_carbon_mundo_fob_usd_t",
                              "carbon_bm_colombia_fob"])
    ratio = _recent_median(trade_fob / m["carbon_newcastle_fob"]) or ccfg["ratio_colombia_newcastle_default"]
    observed, src = _first(w, ["manual_carbon_fob", "co_exp_carbon_pe_fob_usd_t",
                               "co_exp_carbon_mundo_fob_usd_t", "carbon_bm_colombia_fob"])
    nowcast = m["carbon_newcastle_fob"] * ratio
    src = src.where(observed.notna(), np.where(nowcast.notna(), "nowcast_newcastle", None))
    cv_adj = ccfg["poder_calorifico_spec_kcal_kg"] / ccfg["poder_calorifico_ref_kcal_kg"]
    m["carbon_col_fob"] = observed.combine_first(nowcast) * cv_adj
    m["carbon_col_fob_fuente"] = src
    m["ratio_col_newcastle"] = (observed.combine_first(nowcast)) / m["carbon_newcastle_fob"]

    implied_c = _col(w, "pe_imp_carbon_col_cif_usd_t") - _col(w, "co_exp_carbon_pe_fob_usd_t")
    m["carbon_flete"], scale_c = _freight(m["brent"], ccfg["flete"], implied_c,
                                          _col(w, "manual_flete_carbon"))
    cif_model = (m["carbon_col_fob"] + m["carbon_flete"]) * (1 + seguro)
    m["carbon_cif"] = _col(w, "manual_carbon_cif").combine_first(cif_model)
    m["carbon_landed"] = _landed(m["carbon_cif"], dcfg, ccfg["arancel_pct"])
    m["carbon_landed_pen"] = m["carbon_landed"] * m["fx_pen_usd"]
    gj_per_t = ccfg["poder_calorifico_spec_kcal_kg"] * 1000 * KCAL_TO_GJ
    m["carbon_usd_gj"] = m["carbon_landed"] / gj_per_t
    m["carbon_usd_gcal"] = m["carbon_landed"] / (ccfg["poder_calorifico_spec_kcal_kg"] / 1000)
    m["paridad_carbon_brent"] = (m["carbon_col_fob"] / gj_per_t) / (m["brent"] / GJ_PER_BBL)
    m["flete_share_carbon"] = m["carbon_flete"] / m["carbon_cif"]
    m["carbon_cif_comtrade"] = _col(w, "pe_imp_carbon_col_cif_usd_t")
    m["carbon_vs_cif_comtrade"] = m["carbon_cif"] / m["carbon_cif_comtrade"]
    m["carbon_impacto_anual_musd"] = m["carbon_landed"] * ccfg["consumo_anual_t"] / 1e6

    # --- Escoria Japón ------------------------------------------------------------
    observed_e, src_e = _first(w, ["manual_escoria_fob", "jp_exp_escoria_pe_fob_usd_t",
                                   "jp_exp_escoria_mundo_fob_usd_t"])
    carried = observed_e.ffill()
    src_e = src_e.where(observed_e.notna(), np.where(carried.notna(), "arrastre_ultimo_dato", "config_default"))
    m["escoria_fob"] = carried.fillna(ecfg["fob_default_usd_t"])
    m["escoria_fob_fuente"] = src_e

    implied_e = _col(w, "pe_imp_escoria_jpn_cif_usd_t") - _col(w, "jp_exp_escoria_pe_fob_usd_t")
    m["escoria_flete"], scale_e = _freight(m["brent"], ecfg["flete"], implied_e,
                                           _col(w, "manual_flete_escoria"))
    cif_e = (m["escoria_fob"] + m["escoria_flete"]) * (1 + seguro)
    m["escoria_cif"] = _col(w, "manual_escoria_cif").combine_first(cif_e)
    m["escoria_landed"] = _landed(m["escoria_cif"], dcfg, ecfg["arancel_pct"])
    m["escoria_landed_pen"] = m["escoria_landed"] * m["fx_pen_usd"]
    m["flete_share_escoria"] = m["escoria_flete"] / m["escoria_cif"]
    m["escoria_cif_comtrade"] = _col(w, "pe_imp_escoria_jpn_cif_usd_t")
    m["escoria_vs_cif_comtrade"] = m["escoria_cif"] / m["escoria_cif_comtrade"]
    m["clinker_cif_comtrade"] = _col(w, "pe_imp_clinker_mundo_cif_usd_t")
    m["ratio_escoria_clinker"] = m["escoria_cif"] / m["clinker_cif_comtrade"].ffill()
    m["ratio_escoria_carbon"] = m["escoria_landed"] / m["carbon_landed"]
    m["escoria_impacto_anual_musd"] = m["escoria_landed"] * ecfg["consumo_anual_t"] / 1e6

    # Volúmenes importados por Perú (contexto de mercado)
    m["pe_imp_carbon_col_vol_t"] = _col(w, "pe_imp_carbon_col_cif_vol_t")
    m["pe_imp_escoria_jpn_vol_t"] = _col(w, "pe_imp_escoria_jpn_cif_vol_t")

    # Recorta meses finales sin precio de referencia de carbón (aún no publicados)
    last = m["carbon_newcastle_fob"].last_valid_index()
    if last is not None:
        m = m.loc[:last]

    indicators = build_indicators(m)
    meta = {
        "ratio_colombia_newcastle": ratio,
        "ratio_calibrado": bool(trade_fob.notna().any()),
        "factor_flete_carbon": scale_c,
        "factor_flete_escoria": scale_e,
        "ultimo_mes": m.index.max().strftime("%Y-%m") if not m.empty else None,
        "fuente_carbon_fob": m["carbon_col_fob_fuente"].iloc[-1] if not m.empty else None,
        "fuente_escoria_fob": m["escoria_fob_fuente"].iloc[-1] if not m.empty else None,
        "ultimo_dato_por_serie": {c: w[c].last_valid_index().strftime("%Y-%m")
                                  for c in w.columns if w[c].notna().any()},
    }
    return Result(m, indicators, build_alerts(m, indicators, cfg), meta)


def build_indicators(m: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for col, label in {**KEY_SERIES, **RATIOS}.items():
        if col not in m.columns:
            continue
        s = pd.to_numeric(m[col], errors="coerce").dropna()
        if s.empty:
            continue
        last, date = s.iloc[-1], s.index[-1]

        def pct(periods: int) -> float | None:
            ref = s.shift(periods).iloc[-1] if len(s) > periods else np.nan
            return float((last / ref - 1) * 100) if pd.notna(ref) and ref else None

        tail = s.tail(24)
        z = float((last - tail.mean()) / tail.std()) if len(tail) >= 6 and tail.std() > 0 else None
        rows.append({
            "serie": col, "descripcion": label, "mes": date.strftime("%Y-%m"), "ultimo": float(last),
            "var_mensual_pct": pct(1), "var_anual_pct": pct(12),
            "prom_3m": float(s.tail(3).mean()), "prom_12m": float(s.tail(12).mean()),
            "min_24m": float(tail.min()), "max_24m": float(tail.max()), "zscore_24m": z,
        })
    return pd.DataFrame(rows)


def build_alerts(m: pd.DataFrame, ind: pd.DataFrame, cfg: dict) -> list[str]:
    acfg = cfg["alertas"]
    alerts = []
    watched = ["carbon_newcastle_fob", "carbon_col_fob", "carbon_landed", "escoria_fob",
               "escoria_landed", "carbon_flete", "escoria_flete", "fx_pen_usd", "brent"]
    for _, r in ind[ind["serie"].isin(watched)].iterrows():
        if r["var_mensual_pct"] is not None and abs(r["var_mensual_pct"]) >= acfg["variacion_mensual_pct"]:
            arrow = "▲" if r["var_mensual_pct"] > 0 else "▼"
            alerts.append(f"{arrow} {r['descripcion']}: {r['var_mensual_pct']:+.1f}% m/m ({r['ultimo']:,.2f}, {r['mes']})")
        if r["zscore_24m"] is not None and abs(r["zscore_24m"]) >= acfg["zscore"]:
            alerts.append(f"⚠ {r['descripcion']} fuera de rango histórico: z={r['zscore_24m']:+.1f} vs 24 meses")
    for mat in ("carbon", "escoria"):
        budget = cfg["materiales"][mat]["presupuesto_landed_usd_t"]
        s = m[f"{mat}_landed"].dropna()
        if budget and not s.empty:
            limit = budget * (1 + acfg["margen_presupuesto_pct"] / 100)
            if s.iloc[-1] > limit:
                alerts.append(f"💰 {mat.capitalize()} puesto en planta {s.iloc[-1]:,.1f} USD/t supera el "
                              f"presupuesto de {budget:,.1f} USD/t ({(s.iloc[-1] / budget - 1) * 100:+.1f}%)")
    return alerts
