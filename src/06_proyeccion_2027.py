"""Paso 6. Proyección base 2027 por clase y mes, con rango bajo y alto.

Entrada : consulta/cache/base.parquet, cierre_2026.parquet y ordenes_2027.parquet
Salida  : consulta/cache/proyeccion_base.parquet        (anual por clase)
          consulta/cache/proyeccion_base_mensual.parquet (por clase y mes)
Correr  : py src/06_proyeccion_2027.py
"""
import numpy as np
import pandas as pd

import comun as c

PARTE_PRINCIPAL = 0.80      # las clases que acumulan este % de la venta de la línea son "PRINCIPAL"
ANIO = 2027

cfg = c.cargar_config()
c.titulo("PASO 6. PROYECCIÓN BASE 2027")
base = c.leer_cache(cfg, "base", "04_base.py")
cierre = c.leer_cache(cfg, "cierre_2026", "05_cierre_2026.py")
ord27 = c.leer_cache(cfg, "ordenes_2027", "05_cierre_2026.py")

real = base[(base["version"] == "REAL") & (base["clase_et"] != "AJUSTE SIN PRODUCTO")].copy()
real["periodo"] = pd.to_datetime(dict(year=real["anio"], month=real["mes"], day=1)).dt.to_period("M")
FIN = real["periodo"].max()                               # último mes con ventas reales
meses = pd.period_range(real["periodo"].min(), FIN, freq="M")
S = real.groupby(["linea", "clase_et", "periodo"])["venta"].sum().unstack(fill_value=0) \
    .reindex(columns=meses, fill_value=0)
pesos = c.patron_mensual(real)
print(f"Historia: {meses[0]} a {FIN} ({len(meses)} meses) | series (línea + clase): {len(S):,}")


def ventana(tabla, fin, n):
    """Suma de los n meses que terminan en 'fin'."""
    return tabla[[p for p in tabla.columns if fin - n < p <= fin]].sum(axis=1)


def proyectar(tabla, fin):
    """Venta de los 12 meses siguientes a 'fin'. Promedio de tres lecturas del nivel reciente:
    a) los últimos 12 meses; b) el promedio anual de los últimos 24; c) mitad los últimos 12 y
    mitad los últimos 6 anualizados. En las pruebas con el pasado ninguna alternativa más
    compleja lo mejoró."""
    u12, a12, u6 = ventana(tabla, fin, 12), ventana(tabla, fin - 12, 12), ventana(tabla, fin, 6)
    a = u12
    b = (u12 + a12) / 2
    d = 0.5 * u12 + 0.5 * (2 * u6)
    return ((a + b + d) / 3).clip(lower=0)


def grupos(u12):
    """PRINCIPAL = clases que acumulan el 80% de la venta de su línea; RESTO = las demás."""
    orden = u12.clip(lower=0).sort_values(ascending=False)
    antes = orden.groupby(level=0).cumsum() - orden
    total = orden.groupby(level=0).transform("sum")
    return (antes < PARTE_PRINCIPAL * total).map({True: "PRINCIPAL", False: "RESTO"}).reindex(u12.index)


# ------------------------------------------------------------------ 1. Prueba con el pasado
c.subtitulo("Prueba con el pasado: si hubiéramos proyectado así, ¿cuánto habríamos fallado?")
origenes = [FIN - k for k in (12, 18, 24, 30) if FIN - k - 23 >= meses[0]]
pruebas, cocientes, resto_junto, parte_nuevas = [], [], [], []
for fin in origenes:
    f = proyectar(S, fin)
    r = S[[m for m in meses if fin < m <= fin + 12]].sum(axis=1)
    u = ventana(S, fin, 12)
    g = grupos(u)
    for l in c.LINEAS:
        fl, rl, gl, ul = f.xs(l), r.xs(l), g.xs(l), u.xs(l)
        pri, sin_venta = (gl == "PRINCIPAL"), (ul <= 0)
        res = ~pri & ~sin_venta
        pruebas.append({"desde": str(fin), "linea": l.replace("BU-", ""),
                        "total_linea": 100 * (fl.sum() - rl.sum()) / rl.sum(),
                        "por_clase": 100 * (fl - rl).abs().sum() / rl.sum(),
                        "principales": 100 * (fl[pri] - rl[pri]).abs().sum() / rl[pri].sum()})
        resto_junto.append(rl[res].sum() / fl[res].sum())
        parte_nuevas.append({"linea": l, "parte": rl[sin_venta].sum() / rl.sum()})
    q = pd.DataFrame({"grupo": g, "cociente": r / f.replace(0, np.nan)})
    cocientes.append(q[(u > 0) & np.isfinite(q["cociente"])])
pr = pd.DataFrame(pruebas)
print("Error del TOTAL de cada línea, en % (positivo = la proyección quedó alta):")
tl = pr.pivot(index="desde", columns="linea", values="total_linea").round(1)
print(tl.to_string())
print("\nError POR CLASE, en % de la venta (suma de fallas sin importar el signo):")
print(pr.groupby("linea").agg(todas_las_clases=("por_clase", "mean"), solo_principales=("principales", "mean"))
      .round(0).T.to_string())
print("\nCómo leerlo: por clase el error es alto porque un pedido grande mueve mucho una clase; el total de")
print("la línea falla menos porque unas clases quedan arriba y otras abajo.")
for l in tl.columns:
    if (tl[l] > 0).all() or (tl[l] < 0).all():
        sentido = "ALTA" if tl[l].iloc[0] > 0 else "BAJA"
        c.aviso(f"{l}: la proyección quedó {sentido} en todas las pruebas (promedio {tl[l].mean():+.1f}%). "
                "El método no sigue tendencias; el gerente debe tenerlo en cuenta.")

q = pd.concat(cocientes)
rango = q.groupby("grupo")["cociente"].quantile([0.2, 0.8]).unstack()
rango.columns = ["bajo", "alto"]
rango.loc["RESTO_JUNTO"] = [min(float(np.quantile(resto_junto, 0.2)), 1.0), float(np.quantile(resto_junto, 0.8))]
rango.loc["NUEVA"] = [0.0, rango.loc["RESTO", "alto"]]
print("\nRango observado (real entre proyectado, 6 de cada 10 casos cayeron entre 'bajo' y 'alto'):")
print(rango.round(2).to_string())
reserva = pd.DataFrame(parte_nuevas).groupby("linea")["parte"].mean()
print("\nParte de la venta de cada año que vino de clases SIN venta en los 12 meses previos (%):")
print((100 * reserva).round(1).reindex(c.LINEAS).to_string())

# ------------------------------------------------------------------ 2. Proyección 2027
c.subtitulo("Proyección 2027")
u12 = ventana(S, FIN, 12)
primera = real.groupby(["linea", "clase_et"])["periodo"].min().reindex(S.index)
meses_historia = primera.map(lambda m: (FIN.year - m.year) * 12 + FIN.month - m.month + 1)
grupo = grupos(u12)
grupo[u12 <= 0] = "INACTIVA"
grupo[(meses_historia < 12) & (u12 > 0)] = "NUEVA"
p = pd.DataFrame({
    "grupo": grupo,
    "venta_2024": S[[m for m in meses if m.year == 2024]].sum(axis=1),
    "venta_2025": S[[m for m in meses if m.year == 2025]].sum(axis=1),
    "ultimos_12m": u12,
    "meses_con_venta_12m": (S[[m for m in meses if FIN - 12 < m <= FIN]] != 0).sum(axis=1),
    "meses_historia": meses_historia,
    "base_2027": proyectar(S, FIN),
})
# Clases nuevas (menos de 12 meses de historia): se proyecta lo vendido hasta hoy, sin anualizar.
# En las pruebas con el pasado, anualizar duplicaba lo que realmente vendieron al año siguiente.
nuevas = p["grupo"] == "NUEVA"
p.loc[nuevas, "base_2027"] = p.loc[nuevas, "ultimos_12m"].clip(lower=0)
p.loc[p["grupo"] == "INACTIVA", "base_2027"] = 0.0
p = p.reset_index()

# Referencias: cierre 2026 estimado y órdenes que pasan a 2027 (piso)
cz = cierre.groupby(["linea", "clase_et"])["venta"].sum().rename("cierre_2026").reset_index()
p = p.merge(cz, on=["linea", "clase_et"], how="left").merge(ord27, on=["linea", "clase_et"], how="left")
p[["cierre_2026", "ordenes_2027"]] = p[["cierre_2026", "ordenes_2027"]].fillna(0)
sube = p["ordenes_2027"] > p["base_2027"] + 1000
if sube.any():
    print(f"En {int(sube.sum())} clases las órdenes que pasan a 2027 superan la proyección: se usa la orden como piso.")
    c.mostrar(p.loc[sube, ["linea", "clase_et", "base_2027", "ordenes_2027"]])
    p.loc[sube, "base_2027"] = p.loc[sube, "ordenes_2027"]

# Reserva: las clases que hoy no existen (o están inactivas) y aparecerán en 2027. El modelo no
# puede verlas, así que se aparta el porcentaje que históricamente han representado en cada línea.
suma_linea = p.groupby("linea")["base_2027"].sum()
filas_reserva = pd.DataFrame({"linea": c.LINEAS, "clase_et": "RESERVA: CLASES NUEVAS", "grupo": "RESERVA",
                              "base_2027": [suma_linea[l] * reserva[l] for l in c.LINEAS]})
p = pd.concat([p, filas_reserva], ignore_index=True)
num = ["venta_2024", "venta_2025", "ultimos_12m", "cierre_2026", "ordenes_2027", "meses_con_venta_12m", "meses_historia"]
p[num] = p[num].fillna(0)

# Rango bajo y alto con los factores observados en el pasado
fb = p["grupo"].map(rango["bajo"]).fillna(0.0)
fa = p["grupo"].map(rango["alto"]).fillna(1.0)
p.loc[p["grupo"] == "RESERVA", ["bajo_2027", "alto_2027"]] = 0.0
p["bajo_2027"] = np.maximum(p["base_2027"] * fb, p["ordenes_2027"])
p["alto_2027"] = p["base_2027"] * fa
p.loc[p["grupo"] == "RESERVA", "bajo_2027"] = 0.0
p.loc[p["grupo"] == "RESERVA", "alto_2027"] = 2 * p.loc[p["grupo"] == "RESERVA", "base_2027"]
p["cambio_vs_12m_%"] = (100 * (p["base_2027"] / p["ultimos_12m"].where(p["ultimos_12m"] > 0) - 1)).round(1)

# Datos para la revisión: cuántos clientes compran la clase y cuánto pesa el mayor
ult = real[real["periodo"] > FIN - 12]
cli = ult.groupby(["linea", "clase_et", "cliente"])["venta"].sum().reset_index()
cli = cli[cli["venta"] > 0].sort_values("venta", ascending=False)
info = cli.groupby(["linea", "clase_et"]).agg(clientes_12m=("cliente", "nunique"), cliente_principal=("cliente", "first"),
                                             venta_top=("venta", "first"), venta_tot=("venta", "sum")).reset_index()
info["parte_cliente_principal_%"] = (100 * info["venta_top"] / info["venta_tot"]).round(0)
p = p.merge(info.drop(columns=["venta_top", "venta_tot"]), on=["linea", "clase_et"], how="left")
p["clientes_12m"] = p["clientes_12m"].fillna(0).astype(int)

# Por mes: el total anual de la clase repartido con el patrón de su línea
mensual = p[["linea", "clase_et", "grupo", "base_2027"]].merge(
    pesos.stack().rename("peso").reset_index(), on="linea")
mensual["venta_base"] = mensual["base_2027"] * mensual["peso"]
mensual["anio"] = ANIO
mensual = mensual[["anio", "mes", "linea", "clase_et", "grupo", "venta_base"]]
c.guardar_cache(cfg, "rangos", rango.reset_index())
c.guardar_cache(cfg, "proyeccion_base", p)
c.guardar_cache(cfg, "proyeccion_base_mensual", mensual)

# ------------------------------------------------------------------ 3. Lo que se imprime
res = p.groupby("linea").agg(venta_2025=("venta_2025", "sum"), ultimos_12m=("ultimos_12m", "sum"),
                             cierre_2026=("cierre_2026", "sum"), base_2027=("base_2027", "sum"),
                             bajo_2027=("bajo_2027", "sum"), alto_2027=("alto_2027", "sum")).reindex(c.LINEAS)
res.loc["TOTAL"] = res.sum()
res["2027 vs cierre 2026 %"] = (100 * (res["base_2027"] / res["cierre_2026"] - 1)).round(1)
vista = (res.drop(columns="2027 vs cierre 2026 %") / 1e6).round(2)
vista["2027 vs cierre 2026 %"] = res["2027 vs cierre 2026 %"]
print("Por línea, en millones USD (las ventas no incluyen los ajustes contables sin producto):")
print(vista.to_string())
print("\nOJO: el bajo y el alto por línea son la suma de los rangos de cada clase; el total real de la línea")
print("varía mucho menos (mira la primera tabla de la prueba con el pasado).")
c.subtitulo("Clases por grupo")
c.mostrar(p.groupby(["linea", "grupo"]).agg(clases=("clase_et", "size"), base_2027=("base_2027", "sum"))
          .reset_index().pivot(index="linea", columns="grupo", values="clases").fillna(0).astype(int)
          .reindex(c.LINEAS).reset_index())
c.subtitulo("Las 15 clases más grandes de la proyección")
c.mostrar(p.sort_values("base_2027", ascending=False)[["linea", "clase_et", "venta_2025", "ultimos_12m", "cierre_2026",
                                                        "base_2027", "bajo_2027", "alto_2027", "clientes_12m"]], 15)
c.subtitulo("Proyección 2027 por línea y mes (millones USD)")
print((mensual.pivot_table(index="linea", columns="mes", values="venta_base", aggfunc="sum") / 1e6)
      .reindex(c.LINEAS).round(2).to_string())

c.subtitulo("Controles")
dif = abs(mensual["venta_base"].sum() - p["base_2027"].sum())
(c.ok if dif < 1 else c.aviso)(f"La suma mensual coincide con la anual (diferencia {dif:,.2f})")
neg = int((p["base_2027"] < 0).sum())
(c.ok if neg == 0 else c.aviso)(f"Clases con proyección negativa: {neg}")
cambio = 100 * (res.loc["TOTAL", "base_2027"] / res.loc["TOTAL", "ultimos_12m"] - 1)
(c.ok if abs(cambio) <= 15 else c.aviso)(f"Proyección total contra los últimos 12 meses: {cambio:+.1f}% "
                                         "(un cambio mayor a 15% merece revisión)")
print(f"\nGuardado: {c.ruta_cache(cfg, 'proyeccion_base')}")
c.cierre("PASO 6")
