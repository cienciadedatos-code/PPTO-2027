"""Análisis 3. ¿Qué método de proyección usar? Pruebas contra el pasado.

Respalda las decisiones del paso 6 (método) y del paso 7 (cantidad por precio, confianza por fila).
Correr: py analisis/a3_metodos.py   (necesita haber corrido hasta el paso 2). Tarda cerca de un minuto.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import comun as c  # noqa: E402

cfg = c.cargar_config()
c.titulo("ANÁLISIS 3. MÉTODOS DE PROYECCIÓN")
ventas = c.leer_cache(cfg, "ventas", "01_ventas.py")
cat = pd.read_excel(cfg["carpeta_consulta"] / "catalogo.xlsx", dtype=str).fillna("")
v, _, _ = c.mezcla_reciente(ventas, cat)
v["per"] = v["fecha"].dt.to_period("M")
FIN = v["per"].max()
meses = pd.period_range(v["per"].min(), FIN, freq="M")
K = ["linea", "clase_et", "cliente_id", "producto"]
SV = v.groupby(K + ["per"])["venta"].sum().unstack(fill_value=0).reindex(columns=meses, fill_value=0)
SQ = v.groupby(K + ["per"])["cantidad"].sum().unstack(fill_value=0).reindex(columns=meses, fill_value=0)
CL = SV.groupby(level=[0, 1]).sum()                       # venta por clase
ORIGENES = [FIN - k for k in (12, 18, 24, 30) if FIN - k - 23 >= meses[0]]
print(f"Se proyectan 12 meses desde cada origen y se compara con lo real. Orígenes: {[str(o) for o in ORIGENES]}")


def win(t, fin, n):
    return t[[m for m in t.columns if fin - n < m <= fin]].sum(axis=1)


def real12(t, fin):
    return t[[m for m in t.columns if fin < m <= fin + 12]].sum(axis=1)


def metodos(t, fin):
    u12, a12, u6 = win(t, fin, 12), win(t, fin - 12, 12), win(t, fin, 6)
    g = ((u12 / a12.replace(0, np.nan)) - 1).clip(-0.5, 0.5).fillna(0)
    m = {"A. Últimos 12 meses": u12, "B. Promedio de 24 meses": (u12 + a12) / 2,
         "C. Tendencia amortiguada": u12 * (1 + 0.5 * g), "D. Últimos 6 meses por 2": 2 * u6}
    m["E. Promedio de tres lecturas (el elegido)"] = (u12 + (u12 + a12) / 2 + 0.5 * u12 + u6) / 3
    return {k: x.clip(lower=0) for k, x in m.items()}


def wape(f, r):
    return 100 * (f - r).abs().sum() / r.sum()


# ------------------------------------------------------------------ 1. Métodos por clase
c.subtitulo("1. Error de cada método (promedio de los orígenes)")
filas, elegidos = [], {}
for fin in ORIGENES:
    r = real12(CL, fin)
    for nombre, f in metodos(CL, fin).items():
        elegidos[(fin, nombre)] = (f, r)
        filas.append({"metodo": nombre, "error por clase %": wape(f, r),
                      "error del total por línea %": np.mean([abs(f.xs(l).sum() - r.xs(l).sum()) / r.xs(l).sum() * 100 for l in c.LINEAS]),
                      "error del total empresa %": abs(f.sum() - r.sum()) / r.sum() * 100})
c.mostrar(pd.DataFrame(filas).groupby("metodo", as_index=False).mean().round(1))
nombres = [k for k in metodos(CL, ORIGENES[0])]
if len(ORIGENES) >= 3:
    antes, despues = ORIGENES[2], ORIGENES[0]                # 12 meses de separación
    err = pd.DataFrame({n: (elegidos[(antes, n)][0] - elegidos[(antes, n)][1]).abs() for n in nombres})
    mejor = err.idxmin(axis=1)
    fut = pd.DataFrame({n: elegidos[(despues, n)][0] for n in nombres})
    r = elegidos[(despues, nombres[0])][1]
    sel = pd.Series([fut.loc[i, mejor[i]] for i in fut.index], index=fut.index)
    print(f"\nElegir para cada clase el método que mejor le fue en {antes} y usarlo en {despues}: error {wape(sel, r):.1f}% "
          f"(contra {wape(fut[nombres[-1]], r):.1f}% del método único)")
print("\nCONCLUSIÓN 1: ningún método complejo mejora al promedio de tres lecturas, y elegir método por clase empeora")
print("(se ajusta al ruido). La tendencia tampoco ayuda a nivel clase.")

# ------------------------------------------------------------------ 2. Dólares contra cantidad por precio, y error por nivel
c.subtitulo("2. ¿Proyectar dólares o cantidad por precio? ¿Cuánto falla en cada nivel?")
E = "E. Promedio de tres lecturas (el elegido)"
niveles = {"Cliente + descripción": [0, 1, 2, 3], "Cliente + clase": [0, 1, 2], "Clase": [0, 1], "Línea": [0]}
filas, recurrencia, cubetas = [], [], []
for fin in ORIGENES:
    r = real12(SV, fin)
    usd = metodos(SV, fin)[E]
    q = metodos(SQ, fin)[E]

    def precio(n):
        vv, qq = win(SV, fin, n), win(SQ, fin, n)
        return (vv / qq).where((qq > 0) & (vv > 0))

    qp = (q * precio(6).fillna(precio(12)).fillna(precio(24))).fillna(usd)
    for nombre, lv in niveles.items():
        filas.append({"nivel": nombre, "en dólares %": wape(usd.groupby(level=lv).sum(), r.groupby(level=lv).sum()),
                      "cantidad por precio %": wape(qp.groupby(level=lv).sum(), r.groupby(level=lv).sum())})
    filas.append({"nivel": "Total empresa", "en dólares %": abs(usd.sum() - r.sum()) / r.sum() * 100,
                  "cantidad por precio %": abs(qp.sum() - r.sum()) / r.sum() * 100})
    u12 = win(SV, fin, 12)
    act = u12 > 0
    compras = (SV[[m for m in meses if fin - 12 < m <= fin]] > 0).sum(axis=1)
    recurrencia.append({"origen": str(fin), "filas activas": int(act.sum()), "vuelven a comprar %": 100 * (r[act] > 0).mean(),
                        "venta del año siguiente que vino de filas nuevas %": 100 * r[~act].sum() / r.sum()})
    b = pd.cut(compras[act], [0, 2, 5, 12], labels=["BAJA (1-2 meses)", "MEDIA (3-5 meses)", "ALTA (6+ meses)"])
    t = pd.DataFrame({"confianza": b, "f": qp[act], "r": r[act], "u": u12[act]})
    for nombre, g in t.groupby("confianza", observed=True):
        cubetas.append({"confianza": nombre, "% de las filas": 100 * len(g) / len(t), "% de la venta": 100 * g["u"].sum() / t["u"].sum(),
                        "vuelven a comprar %": 100 * (g["r"] > 0).mean(), "error %": wape(g["f"], g["r"])})
orden = list(niveles) + ["Total empresa"]
c.mostrar(pd.DataFrame(filas).groupby("nivel").mean().reindex(orden).round(1).reset_index())
print("\nCONCLUSIÓN 2: cantidad por precio falla lo mismo que dólares, así que se puede usar el formato de los gerentes.")
print("El error baja al sumar: por fila es muy alto, por línea es bajo.")

c.subtitulo("3. ¿Por qué una fila sola es tan impredecible?")
c.mostrar(pd.DataFrame(recurrencia).round(1))
c.mostrar(pd.DataFrame(cubetas).groupby("confianza", as_index=False, observed=True).mean().round(1))
print("\nCONCLUSIÓN 3: solo la mitad de las combinaciones cliente + descripción repite al año siguiente. Las que compran")
print("seguido son pocas filas pero mucha venta, y repiten casi siempre: de ahí sale la etiqueta de confianza.")

# ------------------------------------------------------------------ 4. Clases nuevas
c.subtitulo("4. Clases con menos de 12 meses de historia: ¿anualizar lo vendido?")
filas = []
for fin in ORIGENES:
    hist = CL[[m for m in meses if m <= fin]]
    con_venta = (hist != 0)
    meses_hist = pd.Series(hist.shape[1] - con_venta.values.argmax(axis=1), index=hist.index).where(con_venta.any(axis=1))
    u12, r = win(CL, fin, 12), real12(CL, fin)
    nuevas = (meses_hist < 12) & (u12 > 0)
    filas.append({"origen": str(fin), "clases nuevas": int(nuevas.sum()), "real / (lo vendido tal cual)": r[nuevas].sum() / u12[nuevas].sum(),
                  "real / (anualizado)": r[nuevas].sum() / (u12[nuevas] / meses_hist[nuevas] * 12).sum()})
c.mostrar(pd.DataFrame(filas).round(2))
print("\nCONCLUSIÓN 4: un cociente cercano a 1 es lo correcto. Anualizar proyecta cerca del doble de lo que vendieron;")
print("usar lo vendido tal cual queda cerca de 1. Por eso las clases nuevas no se anualizan.")
c.cierre("ANÁLISIS 3")
