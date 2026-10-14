"""Paso 3. Análisis de clases: qué tan parejo es el precio dentro de cada Clase ET.

Sirve para decidir hasta dónde cortar una clase. No cambia nada: mide y deja una lista.
Entrada : consulta/cache/ventas.parquet y consulta/catalogo.xlsx
Salida  : consulta/clases_revision.xlsx (hojas: clases y variantes)
Correr  : py src/03_clases.py
"""
import numpy as np
import pandas as pd

import comun as c

RATIO_PAREJO = 1.3      # hasta 1.3 veces entre la variante más cara y la más barata: precio parejo
RATIO_MIXTO = 2.0       # más de 2 veces: clase mixta
PARTE_MINIMA = 0.05     # solo se comparan variantes que pesan 5% o más de la clase
MESES_MINIMOS = 12      # una variante "tiene historia" si vendió en 12 o más de los últimos 24 meses

cfg = c.cargar_config()
RUTA = cfg["carpeta_consulta"] / "clases_revision.xlsx"
c.titulo("PASO 3. ANÁLISIS DE CLASES: precio y unidad dentro de cada Clase ET")
ventas = c.leer_cache(cfg, "ventas", "01_ventas.py")
cat = pd.read_excel(cfg["carpeta_consulta"] / "catalogo.xlsx", dtype=str).fillna("")
v, _, FIN = c.mezcla_reciente(ventas, cat)
nombres = {p: c.nombre_desde_descripcion(p) for p in v["producto"].unique()}
v["variante"] = v["producto"].map(nombres)             # el nombre sin empaque ni fabricante
v["periodo"] = v["fecha"].dt.to_period("M")
f = v[(v["tipo_doc"] == "Factura") & (v["cantidad"] > 0) & (v["venta"] > 0) &
      (v["fecha"] > FIN - pd.DateOffset(months=12)) & (v["clase_et"] != "MUESTRA")].copy()
f["log_precio"] = np.log(f["venta"] / f["cantidad"])
print(f"Facturas de los últimos 12 meses: {len(f):,} | venta {f['venta'].sum() / 1e6:,.1f} millones")

# ------------------------------------------------------------------ 1. ¿Qué explica el precio dentro de una clase?
c.subtitulo("Qué explica las diferencias de precio dentro de una misma clase")


def media(cols):
    llave = [f[x] for x in ["linea", "clase_et"] + cols]
    return ((f["log_precio"] * f["venta"]).groupby(llave).transform("sum") /
            f["venta"].groupby(llave).transform("sum"))


total = np.average((f["log_precio"] - media([])) ** 2, weights=f["venta"])
factores = [("La variante (nombre sin empaque)", ["variante"]),
            ("El producto (variante + empaque + fabricante)", ["producto"]),
            ("El fabricante", ["fabricante"]), ("La unidad de medida", ["unidad"]),
            ("El cliente", ["cliente_id"]), ("Producto + cliente", ["producto", "cliente_id"])]
exp = pd.DataFrame([{"factor": n, "explica_%": round(100 * (1 - np.average((f["log_precio"] - media(k)) ** 2,
                                                                         weights=f["venta"]) / total), 1)}
                    for n, k in factores])
c.mostrar(exp)
print("Cómo leerlo: 100% sería que ese factor explica todo el precio. La variante es lo que más pesa;")
print("por eso el corte de una clase se decide viendo sus variantes.")

# ------------------------------------------------------------------ 2. Precio por variante y tipo de clase
u24 = v[v["fecha"] > FIN - pd.DateOffset(months=24)]
meses_venta = u24[u24["venta"] > 0].groupby(["linea", "clase_et", "variante"])["periodo"].nunique()
clases, variantes = [], []
for (linea, clase), g in f.groupby(["linea", "clase_et"]):
    t = g.groupby("variante").agg(venta_12m=("venta", "sum"), cantidad_12m=("cantidad", "sum"),
                                  clientes=("cliente_id", "nunique"), productos=("producto", "nunique"),
                                  unidades=("unidad", lambda s: ", ".join(sorted(set(s))))).reset_index()
    t["precio"] = t["venta_12m"] / t["cantidad_12m"]
    t["parte_%"] = 100 * t["venta_12m"] / t["venta_12m"].sum()
    t["meses_con_venta_24m"] = [int(meses_venta.get((linea, clase, x), 0)) for x in t["variante"]]
    t.insert(0, "clase_et", clase)
    t.insert(0, "linea", linea)
    grandes = t[t["parte_%"] >= 100 * PARTE_MINIMA]
    ratio = grandes["precio"].max() / grandes["precio"].min() if len(grandes) else 1.0
    por_unidad = g.groupby("unidad").agg(v=("venta", "sum"), q=("cantidad", "sum"))
    pu = por_unidad["v"] / por_unidad["q"]
    ratio_unidad = pu.max() / pu.min() if len(pu) > 1 else 1.0
    con_historia = int(((grandes["meses_con_venta_24m"] >= MESES_MINIMOS)).sum())
    tipo = "PAREJA" if ratio <= RATIO_PAREJO else ("MODERADA" if ratio <= RATIO_MIXTO else "MIXTA")
    if tipo == "PAREJA":
        sugerencia = "Dejar como está"
    elif con_historia >= 2:
        sugerencia = "Se puede separar por variante: revisar con el gerente"
    else:
        sugerencia = "Dejar junta (variantes con poca historia): leer la clase solo en dólares"
    if ratio_unidad > RATIO_PAREJO:
        sugerencia += " | Revisar unidades: el precio cambia según la unidad"
    clases.append({"linea": linea, "clase_et": clase, "venta_12m": g["venta"].sum(), "variantes": len(t),
                   "productos": g["producto"].nunique(), "clientes": g["cliente_id"].nunique(),
                   "unidades": ", ".join(sorted(set(g["unidad"]))), "precio_min": grandes["precio"].min(),
                   "precio_max": grandes["precio"].max(), "veces_precio": round(ratio, 2),
                   "veces_precio_por_unidad": round(ratio_unidad, 2), "variantes_con_historia": con_historia,
                   "tipo": tipo, "sugerencia": sugerencia})
    variantes.append(t)
clases = pd.DataFrame(clases).sort_values(["tipo", "venta_12m"], ascending=[True, False])
variantes = pd.concat(variantes, ignore_index=True)
no_parejas = clases[clases["tipo"] != "PAREJA"][["linea", "clase_et"]]
detalle = variantes.merge(no_parejas, on=["linea", "clase_et"]).sort_values(
    ["linea", "clase_et", "venta_12m"], ascending=[True, True, False])
orden = clases.assign(o=clases["tipo"].map({"MIXTA": 0, "MODERADA": 1, "PAREJA": 2})).sort_values(
    ["o", "venta_12m"], ascending=[True, False]).drop(columns="o")
c.escribir_excel({"clases": orden, "variantes": detalle}, RUTA, anchos={"clase_et": 35, "variante": 40, "sugerencia": 60})

c.subtitulo("Tipos de clase según qué tan distinto es el precio entre sus variantes")
res = clases.groupby("tipo").agg(clases=("clase_et", "size"), venta_12m=("venta_12m", "sum")).reindex(
    ["PAREJA", "MODERADA", "MIXTA"]).fillna(0)
res["% de la venta"] = (100 * res["venta_12m"] / res["venta_12m"].sum()).round(1)
print(res.to_string())
print(f"\nPAREJA: hasta {RATIO_PAREJO} veces | MODERADA: hasta {RATIO_MIXTO} veces | MIXTA: más de {RATIO_MIXTO} veces")
c.subtitulo("Por línea (número de clases)")
print(pd.crosstab(clases["linea"], clases["tipo"]).reindex(c.LINEAS).to_string())
unid = clases[clases["veces_precio_por_unidad"] > RATIO_PAREJO]
print(f"\nClases donde el precio cambia según la unidad de medida: {len(unid)} "
      f"({unid['venta_12m'].sum() / 1e6:,.1f} millones). En esas no se pueden sumar cantidades.")
print(f"Clases con más de un código de unidad pero el mismo precio (solo cambió el código): "
      f"{int(((clases['unidades'].str.contains(',')) & (clases['veces_precio_por_unidad'] <= RATIO_PAREJO)).sum())}")

c.subtitulo("PENDIENTES: clases MIXTAS y MODERADAS (las de mayor venta primero)")
c.mostrar(orden.loc[orden["tipo"] != "PAREJA", ["linea", "clase_et", "venta_12m", "variantes", "veces_precio",
                                                 "variantes_con_historia", "tipo", "sugerencia"]], 30)
c.subtitulo("Ejemplo: variantes de la clase mixta de mayor venta")
if len(no_parejas):
    top = orden[orden["tipo"] == "MIXTA"].head(1) if (orden["tipo"] == "MIXTA").any() else orden[orden["tipo"] != "PAREJA"].head(1)
    ej = detalle[(detalle["linea"] == top["linea"].iat[0]) & (detalle["clase_et"] == top["clase_et"].iat[0])]
    c.mostrar(ej[["clase_et", "variante", "venta_12m", "cantidad_12m", "precio", "parte_%", "clientes", "meses_con_venta_24m"]], 15)

c.subtitulo("Controles")
dif = abs(clases["venta_12m"].sum() - f["venta"].sum())
(c.ok if dif < 1 else c.aviso)(f"La suma por clase coincide con las facturas analizadas (diferencia {dif:,.2f})")
n = int((clases["tipo"] != "PAREJA").sum())
print(f"Clases por revisar con los gerentes: {n}. Si deciden separar una, cambia 'clase_et' de sus productos en")
print("catalogo.xlsx (por ejemplo de CETIOL a CETIOL HE) y vuelve a correr los pasos 2, 3 y 4.")
print(f"\nGuardado: {RUTA}")
c.cierre("PASO 3")
