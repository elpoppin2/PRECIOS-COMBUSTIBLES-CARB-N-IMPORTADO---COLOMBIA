"""CLI del monitor.

    python -m monitor update     # descarga fuentes públicas + manuales y actualiza el histórico
    python -m monitor report     # calcula ratios, genera reporte (y comentario del agente)
    python -m monitor all        # update + report + notificación
"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import date

import pandas as pd

from . import agent, analytics, notify, report, store
from .config import HIST_PATH, MANUAL_DIR, REPORTS_DIR, load_config
from .sources import bcrp, comtrade, fred, manual, worldbank

log = logging.getLogger("monitor")


def update(cfg: dict) -> pd.DataFrame:
    f = cfg["fuentes"]
    start = f["inicio"]
    steps = [
        ("fred", lambda: fred.fetch(start)),
        ("banco_mundial", lambda: worldbank.fetch(start)),
        ("bcrp", lambda: bcrp.fetch(start)),
        ("comtrade", lambda: comtrade.fetch(f.get("comtrade_meses", 24))),
        ("manual", lambda: manual.fetch(MANUAL_DIR, cfg)),
    ]
    frames = []
    for name, fn in steps:
        if not f.get(name, True):
            continue
        df = fn()
        log.info("%-14s %5d observaciones", name, len(df))
        frames.append(df)
    new = pd.concat([d for d in frames if not d.empty], ignore_index=True) if any(
        not d.empty for d in frames) else pd.DataFrame(columns=store.COLUMNS)
    return store.upsert(HIST_PATH, new)


def build_report(cfg: dict, use_agent: bool = True) -> analytics.Result:
    res = analytics.compute(store.wide(store.load(HIST_PATH)), cfg)
    text = agent.commentary(res, cfg) if use_agent else None
    files = report.charts(res, REPORTS_DIR / "graficos")
    md = report.render(res, cfg, text, files)
    REPORTS_DIR.mkdir(exist_ok=True)
    (REPORTS_DIR / "ultimo_reporte.md").write_text(md, encoding="utf-8")
    (REPORTS_DIR / "historial").mkdir(exist_ok=True)
    (REPORTS_DIR / "historial" / f"{date.today().isoformat()}.md").write_text(
        md.replace("](graficos/", "](../graficos/"), encoding="utf-8")
    if not res.monthly.empty:
        res.monthly.to_csv(REPORTS_DIR / "modelo_mensual.csv", date_format="%Y-%m", float_format="%.4f")
        res.indicators.to_csv(REPORTS_DIR / "indicadores.csv", index=False, float_format="%.4f")
    log.info("Reporte generado: %s (%d alertas)", REPORTS_DIR / "ultimo_reporte.md", len(res.alerts))
    return res


def main() -> None:
    p = argparse.ArgumentParser(prog="monitor", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("comando", choices=["update", "report", "all"])
    p.add_argument("--sin-agente", action="store_true", help="no llamar a Claude")
    p.add_argument("--config", default=None, help="ruta alternativa a config.yaml")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config) if args.config else load_config()

    if args.comando in ("update", "all"):
        update(cfg)
    if args.comando in ("report", "all"):
        res = build_report(cfg, use_agent=not args.sin_agente)
        if args.comando == "all":
            notify.telegram(res, cfg, os.environ.get("REPORT_URL"))


if __name__ == "__main__":
    main()
