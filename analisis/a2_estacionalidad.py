"""Análisis 2. ¿Hay estacionalidad? ¿A qué nivel conviene calcularla?

Respalda la decisión de repartir el año con el patrón de la línea (pasos 5 a 8).
Correr: py analisis/a2_estacionalidad.py   (necesita haber corrido hasta el paso 4)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import comun as c  # noqa: E402

cfg = c.cargar_config()
c.titulo("ANÁLISIS 2. ESTACIONALIDAD")
base = c.leer_cache(cfg, "base", "04_base.py")
real = base[(base["version"] == "REAL") & (base["clase_et"] != "AJUSTE SIN PRODUCTO")]
ANIOS = [a for a in sorted(real["anio"].unique()) if real[real["anio"] == a]["mes"].nunique() == 12]
PRUEBA, ENTRENA = ANIOS[-1], ANIOS[:-1]
print(f"Años completos: {ANIOS}. Se calcula el patrón con {ENTRENA} y se prueba en {PRUEBA}.")

c.subtitulo("1. Índice mensual por línea (1.00 = un mes promedio)")
pesos = c.patron_mensual(real, anios=ANIOS)
print((pesos * 12).round(2).to_string())
m = real[real["anio"].isin(ANIOS)].groupby(["linea", "anio", "mes"])["venta"].sum().unstack("mes")
idx = m.div(m.mean(axis=1), axis=0)
print("\n¿Se repite el patrón de un año al siguiente? Correlación promedio entre años (1 = idéntico, 0 = nada):")
for linea, g in idx.groupby(level=0):
    cor = g.droplevel(0).T.corr().values
    print(f"  {linea:22s} {(cor.sum() - len(cor)) / (len(cor) * (len(cor) - 1)):.2f}")
print("\nCONCLUSIÓN 1: lo único constante es diciembre bajo y enero alto. El resto cambia de un año a otro.")

c.subtitulo(f"2. Prueba: repartir el total real de {PRUEBA} en meses con distintos patrones")
pesos_prueba = c.patron_mensual(real, anios=ENTRENA)        # el patrón se calcula sin el año de prueba


def tabla(cols):
    t = real.groupby(cols + ["anio", "mes"])["venta"].sum().unstack("mes").fillna(0)
    return t


def error(cols, etiqueta):
    t = tabla(cols)
    r = t.xs(PRUEBA, level="anio")
    r = r[r.sum(axis=1) > 0]
    total = r.sum(axis=1)
    ent = t[t.index.get_level_values("anio").isin(ENTRENA)].groupby(level=list(range(len(cols)))).sum()
    propio = ent.div(ent.sum(axis=1).replace(0, np.nan), axis=0).reindex(r.index)
    linea = pd.DataFrame([pesos_prueba.loc[i if isinstance(i, str) else i[0]].values for i in r.index], index=r.index, columns=r.columns)
    propio = propio.fillna(linea)
    f = lambda w: 100 * (w.mul(total, axis=0) - r).abs().sum().sum() / r.sum().sum()
    return {"nivel": etiqueta, "filas": len(r), "repartir parejo (1/12)": round(f(linea * 0 + 1 / 12), 1),
            "patrón de la línea": round(f(linea), 1), "patrón propio": round(f(propio), 1)}


res = pd.DataFrame([error(["linea"], "Línea"), error(["linea", "clase_et"], "Clase"),
                    error(["linea", "clase_et", "key_id"], "Producto (key_id)")])
c.mostrar(res)
print("Cómo leerlo: error mensual en % de la venta. Mientras más bajo, mejor reparte ese patrón.")
print("\nCONCLUSIÓN 2: el patrón propio de una clase o de un producto falla más que el de su línea. La forma mensual")
print("se toma de la línea; el mes exacto de una clase depende de cuándo cae cada pedido grande.")
c.cierre("ANÁLISIS 2")
