"""Reporte Markdown + gráficos PNG (se renderiza directo en GitHub)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from .analytics import KEY_SERIES, RATIOS, Result  # noqa: E402

FUENTES_LEGIBLES = {
    "manual_carbon_fob": "cotización propia",
    "co_exp_carbon_pe_fob_usd_t": "Comtrade: export. Colombia→Perú (FOB)",
    "co_exp_carbon_mundo_fob_usd_t": "Comtrade: export. Colombia→mundo (FOB)",
    "carbon_bm_colombia_fob": "Banco Mundial: Coal, Colombian",
    "nowcast_newcastle": "estimado: Newcastle × ratio Colombia/Newcastle",
    "manual_escoria_fob": "cotización propia",
    "jp_exp_escoria_pe_fob_usd_t": "Comtrade: export. Japón→Perú (FOB)",
    "jp_exp_escoria_mundo_fob_usd_t": "Comtrade: export. Japón→mundo (FOB)",
    "arrastre_ultimo_dato": "último dato observado (arrastre)",
    "config_default": "valor por defecto de config.yaml",
}


def _fmt(v, nd=2, pct=False):
    if v is None or pd.isna(v):
        return "—"
    return f"{v:+.1f}%" if pct else f"{v:,.{nd}f}"


def _table(ind: pd.DataFrame, series: dict) -> str:
    sub = ind[ind["serie"].isin(series)]
    if sub.empty:
        return "_Sin datos._\n"
    lines = ["| Indicador | Mes | Último | m/m | a/a | Prom. 3m | Prom. 12m | Rango 24m | z 24m |",
             "|---|---|---:|---:|---:|---:|---:|---|---:|"]
    for _, r in sub.iterrows():
        nd = 3 if r["serie"].startswith(("ratio", "paridad", "flete_share", "fx_pen", "carbon_vs", "escoria_vs")) else 2
        lines.append(
            f"| {r['descripcion']} | {r['mes']} | **{_fmt(r['ultimo'], nd)}** | {_fmt(r['var_mensual_pct'], pct=True)} "
            f"| {_fmt(r['var_anual_pct'], pct=True)} | {_fmt(r['prom_3m'], nd)} | {_fmt(r['prom_12m'], nd)} "
            f"| {_fmt(r['min_24m'], nd)} – {_fmt(r['max_24m'], nd)} | {_fmt(r['zscore_24m'], 1)} |"
        )
    return "\n".join(lines) + "\n"


def charts(res: Result, out_dir: Path) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    m = res.monthly.tail(36)
    if m.empty:
        return []
    specs = [
        ("carbon.png", "Carbón colombiano → Conchán (USD/t)",
         {"carbon_newcastle_fob": "Newcastle FOB", "carbon_col_fob": "Colombia FOB (spec)",
          "carbon_cif": "CIF Conchán", "carbon_landed": "Puesto en planta",
          "carbon_cif_comtrade": "CIF Comtrade Perú"}),
        ("escoria.png", "Escoria japonesa → Conchán (USD/t)",
         {"escoria_fob": "Japón FOB", "escoria_cif": "CIF Conchán", "escoria_landed": "Puesto en planta",
          "escoria_cif_comtrade": "CIF Comtrade Perú", "clinker_cif_comtrade": "Clinker CIF Perú"}),
        ("fletes.png", "Fletes estimados (USD/t) y Brent (USD/bbl)",
         {"carbon_flete": "Flete Colombia→Conchán", "escoria_flete": "Flete Japón→Conchán", "brent": "Brent"}),
        ("ratios.png", "Ratios clave",
         {"ratio_col_newcastle": "Colombia/Newcastle", "ratio_escoria_clinker": "Escoria/Clinker",
          "ratio_escoria_carbon": "Escoria/Carbón", "paridad_carbon_brent": "Carbón/Brent (energía)"}),
    ]
    files = []
    for fname, title, cols in specs:
        fig, ax = plt.subplots(figsize=(9, 4))
        plotted = False
        for col, label in cols.items():
            if col in m.columns and m[col].notna().any():
                s = m[col].dropna()
                style = "o" if col.endswith("_comtrade") else "-"
                ax.plot(s.index, s.values, style, label=label, markersize=3, linewidth=1.8)
                plotted = True
        if not plotted:
            plt.close(fig)
            continue
        ax.set_title(title, fontsize=11, loc="left")
        ax.grid(alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(fontsize=8, frameon=False, ncol=3)
        fig.tight_layout()
        fig.savefig(out_dir / fname, dpi=120)
        plt.close(fig)
        files.append(fname)
    return files


def render(res: Result, cfg: dict, commentary: str | None, chart_files: list[str]) -> str:
    today = date.today().isoformat()
    meta = res.meta
    out = [f"# Monitor de insumos críticos — Puerto Conchán\n",
           f"_Actualizado: {today} · Último mes con datos de referencia: {meta.get('ultimo_mes', '—')}_\n"]

    out.append("## Alertas\n")
    out.append("\n".join(f"- {a}" for a in res.alerts) + "\n" if res.alerts else "Sin alertas.\n")

    if commentary:
        out.append("## Análisis del agente\n")
        out.append(commentary.strip() + "\n")

    if res.monthly.empty:
        return "\n".join(out)

    last = res.monthly.iloc[-1]
    ccfg, ecfg = cfg["materiales"]["carbon"], cfg["materiales"]["escoria"]
    out.append("## Resumen puesto en planta\n")
    out.append("| | Carbón Colombia | Escoria Japón |\n|---|---:|---:|")
    for label, kc, ke, nd in [
        ("FOB origen (USD/t)", "carbon_col_fob", "escoria_fob", 2),
        ("Flete (USD/t)", "carbon_flete", "escoria_flete", 2),
        ("CIF Conchán (USD/t)", "carbon_cif", "escoria_cif", 2),
        ("Puesto en planta (USD/t)", "carbon_landed", "escoria_landed", 2),
        ("Puesto en planta (PEN/t)", "carbon_landed_pen", "escoria_landed_pen", 2),
        ("Costo anual estimado (MUSD)", "carbon_impacto_anual_musd", "escoria_impacto_anual_musd", 1),
    ]:
        out.append(f"| {label} | {_fmt(last.get(kc), nd)} | {_fmt(last.get(ke), nd)} |")
    out.append(f"| Presupuesto puesto en planta (USD/t) | {_fmt(ccfg['presupuesto_landed_usd_t'])} "
               f"| {_fmt(ecfg['presupuesto_landed_usd_t'])} |")
    out.append(f"| Fuente del FOB | {FUENTES_LEGIBLES.get(meta.get('fuente_carbon_fob'), meta.get('fuente_carbon_fob'))} "
               f"| {FUENTES_LEGIBLES.get(meta.get('fuente_escoria_fob'), meta.get('fuente_escoria_fob'))} |\n")
    out.append(f"Carbón: {_fmt(last.get('carbon_usd_gj'))} USD/GJ · {_fmt(last.get('carbon_usd_gcal'))} USD/Gcal "
               f"(spec {ccfg['poder_calorifico_spec_kcal_kg']} kcal/kg NAR). "
               f"Ratio Colombia/Newcastle usado: {meta['ratio_colombia_newcastle']:.3f} "
               f"({'calibrado con Comtrade' if meta['ratio_calibrado'] else 'valor por defecto'}). "
               f"Factor de calibración de flete: carbón {meta['factor_flete_carbon']:.2f}, "
               f"escoria {meta['factor_flete_escoria']:.2f}.\n")

    out.append("## Precios y costos\n")
    out.append(_table(res.indicators, KEY_SERIES))
    out.append("## Ratios\n")
    out.append(_table(res.indicators, RATIOS))

    if chart_files:
        out.append("## Gráficos (últimos 36 meses)\n")
        out += [f"![{f}](graficos/{f})\n" for f in chart_files]

    out.append("## Frescura de datos por serie\n")
    out.append("| Serie | Último mes |\n|---|---|")
    out += [f"| `{k}` | {v} |" for k, v in sorted(meta.get("ultimo_dato_por_serie", {}).items())]
    out.append("\n---\n_Fuentes: FRED/IMF, Banco Mundial (Pink Sheet), BCRP, UN Comtrade y cotizaciones propias. "
               "Los valores modelados son estimaciones; ver README para la metodología._\n")
    return "\n".join(out)
