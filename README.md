# Monitor de insumos críticos — Puerto Conchán

Bot/agente que sigue cada semana la evolución de precios de dos insumos críticos
importados por **Puerto Conchán (Lima, Perú)**:

| Insumo | Origen | Partida |
|---|---|---|
| Carbón térmico | Colombia | HS 2701.12 |
| Escoria granulada de alto horno (GBFS) | Japón | HS 2618.00 |

Combina **información pública gratuita** con tus **cotizaciones propias**, arma el
**costo puesto en planta** (FOB → flete → CIF → planta, en USD y PEN), calcula
**ratios** de seguimiento, dispara **alertas** y, si configuras una API key de Claude,
un **agente analista** redacta el comentario de mercado con noticias públicas recientes.

👉 Reporte vigente: [`reports/ultimo_reporte.md`](reports/ultimo_reporte.md)

---

## Fuentes públicas

| Fuente | Qué aporta | Frecuencia / rezago |
|---|---|---|
| **FRED / IMF** (`PCOALAUUSDM`, `MCOILBRENTEU`, `EXJPUS`, `COLCCUSMA02STM`) | Carbón Newcastle FOB (benchmark), Brent (proxy de bunker), USD/JPY, USD/COP | Mensual, ~1 mes |
| **Banco Mundial – Pink Sheet** | Carbón Australia, Sudáfrica (y Colombia si se publica), Brent | Mensual, ~1 mes |
| **BCRP** (`PD04638PD`) | Tipo de cambio interbancario PEN/USD | Diario → promedio mensual |
| **UN Comtrade** | Valores unitarios reales: CIF de Perú (importaciones desde Colombia/Japón, clinker), FOB de Colombia y Japón (exportaciones a Perú y al mundo), volúmenes | Mensual, 2–4 meses |
| **Tus cotizaciones** (`data/manual/*.csv`) | Precios de proveedores/brokers/Argus/Platts y fletes cotizados | Cuando las cargues |

> No existe una fuente pública gratuita en tiempo real para el API2/Colombia FOB ni para
> la escoria japonesa. Por eso el modelo **calibra ratios** con los datos de comercio
> exterior (reales pero rezagados) y los aplica a los benchmarks que sí son oportunos.

## Metodología

**Carbón Colombia FOB** (en orden de prioridad)
1. Tu cotización FOB (normalizada a la kcal de referencia).
2. Valor unitario FOB de exportaciones Colombia→Perú (o →mundo) de Comtrade.
3. Pink Sheet “Coal, Colombian”, si existe.
4. **Nowcast**: Newcastle × *ratio Colombia/Newcastle*, donde el ratio es la mediana de
   los últimos 12 meses observados (si no hay datos usa `ratio_colombia_newcastle_default`).

Se ajusta a la especificación del contrato: `FOB_spec = FOB_ref × kcal_spec / kcal_ref`.

**Escoria Japón FOB**: tu cotización → FOB Japón→Perú (Comtrade) → FOB Japón→mundo →
arrastre del último dato → valor por defecto de la config.

**Flete**: `flete_base × (Brent / Brent_base)^elasticidad`, recalibrado con el flete
implícito de Comtrade (`CIF Perú − FOB origen` del mismo flujo). Tu cotización de flete
siempre tiene prioridad.

**Costo puesto en planta**
```
CIF     = (FOB + flete) × (1 + seguro%)
Landed  = CIF × (1 + arancel% + agente%) + descarga + almacenaje + transporte a planta
PEN/t   = Landed × TC BCRP
```
El IGV (18%) es crédito fiscal y no se suma al costo.

### Ratios que se monitorean

| Ratio | Para qué sirve |
|---|---|
| Carbón Colombia FOB / Newcastle | Descuento/prima del carbón colombiano vs. el benchmark del Pacífico |
| Carbón vs Brent (USD/GJ) | Competitividad del carbón frente a combustibles líquidos |
| Carbón USD/GJ y USD/Gcal | Costo energético real según tu spec |
| Flete / CIF (carbón y escoria) | Exposición al mercado de fletes; en la escoria suele ser > 50% |
| Escoria CIF / Clinker CIF importado | Economía de sustitución de clinker por escoria (< 1 favorable) |
| Escoria landed / Carbón landed | Relación de costos entre ambos insumos |
| CIF modelo / CIF Comtrade Perú | Control de calidad del modelo vs. lo que efectivamente pagó el mercado peruano |

Para cada serie se calcula: último valor, variación mensual y anual, promedios 3m/12m,
rango y z-score de 24 meses.

### Alertas (config → `alertas`)
- Variación mensual mayor a `variacion_mensual_pct`.
- Valor fuera de rango histórico (|z| ≥ `zscore`).
- Costo puesto en planta por encima de `presupuesto_landed_usd_t`.

## Uso

```bash
pip install -r requirements.txt
python -m monitor update        # descarga datos → data/historico/series.csv
python -m monitor report        # calcula, grafica y escribe reports/ultimo_reporte.md
python -m monitor all           # todo + notificación Telegram
python -m monitor report --sin-agente   # sin llamar a Claude
python -m pytest -q             # pruebas
```

### Cargar tus cotizaciones
Agrega filas a `data/manual/cotizaciones.csv` (bases FOB, CFR o CIF) y
`data/manual/fletes.csv`. Al hacer push de esos archivos, GitHub Actions regenera el
reporte automáticamente.

```csv
fecha,material,base,precio_usd_t,poder_calorifico_kcal_kg,proveedor,comentario
2026-10-15,carbon,FOB,118.5,6000,Proveedor X,Puerto Nuevo
2026-10-15,escoria,FOB,26,,Proveedor Y,Kashima
```

### Ajustar supuestos
Todo está en [`config/config.yaml`](config/config.yaml): kcal de tu contrato, costos
portuarios en Conchán, fletes base, consumos anuales, presupuestos y umbrales de
alerta. Los valores marcados con **AJUSTAR** son supuestos iniciales.

## Automatización (GitHub Actions)

El workflow [`actualizar.yml`](.github/workflows/actualizar.yml) corre **cada lunes
07:17 (Lima)**, al cargar cotizaciones nuevas y manualmente desde *Actions → Run
workflow*. Guarda el histórico y el reporte en el repositorio (quedan versionados).

Secretos opcionales (*Settings → Secrets and variables → Actions*):

| Secreto | Uso |
|---|---|
| `ANTHROPIC_API_KEY` | Agente analista con Claude (comentario + búsqueda de noticias) |
| `COMTRADE_API_KEY` | Clave gratuita de [comtradedeveloper.un.org](https://comtradedeveloper.un.org) para más cuota |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Resumen y alertas por Telegram |

Sin ningún secreto el bot funciona igual con las fuentes públicas.

## Estructura

```
config/config.yaml          supuestos, umbrales y fuentes
data/manual/                tus cotizaciones y fletes
data/historico/series.csv   histórico (generado)
monitor/sources/            conectores: fred, worldbank, bcrp, comtrade, manual
monitor/analytics.py        costo puesto en planta, ratios, indicadores y alertas
monitor/agent.py            agente analista (Claude)
monitor/report.py           reporte Markdown + gráficos
reports/                    reporte vigente, historial, CSV del modelo (generado)
```

## Ideas para extender
- SUNAT (ADUANET): DUAs de importación por Conchán (precio real por embarque).
- ANM Colombia: precio base de liquidación de regalías del carbón (trimestral).
- Índices de fletes (Baltic Supramax/Handysize) y bunker VLSFO Panamá/Singapur si
  dispones de suscripción.
- Restricciones de calado del Canal de Panamá (ACP) como alerta de flete.
