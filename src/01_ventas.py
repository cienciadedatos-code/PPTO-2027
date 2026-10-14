"""Paso 1. Tabla de ventas validada.

Entrada : consulta/cache/rentabilidad.parquet y vip.parquet (paso 0)
Salida  : consulta/cache/ventas.parquet (una fila por línea de factura)
Correr  : py src/01_ventas.py
"""
import pandas as pd

import comun as c

# Cifras de control del archivo 0__VIP_2027_V1_0.xlsx. Si cambias el Excel, cambian.
ESPERADO = {"filas_ventas": 86238, "venta_total": 544977338.50, "productos": 2328,
            "clientes": 957, "filas_ajuste": 10}

cfg = c.cargar_config()
c.titulo("PASO 1. VENTAS: aplicar las reglas y validar contra la pestaña VIP")
r = c.leer_cache(cfg, "rentabilidad", "00_preparar.py")
vip = c.leer_cache(cfg, "vip", "00_preparar.py")
print(f"Filas leídas de BD RENTABILIDAD: {len(r):,} | venta {r['Venta'].sum():,.2f}")

# ------------------------------------------------------------------ 1. Reglas de qué es venta
c.subtitulo("Regla 1: solo las cinco líneas de negocio")
fuera = r[~r["Linea"].isin(c.LINEAS)]
c.mostrar(fuera.groupby("Linea").agg(filas=("Venta", "size"), venta=("Venta", "sum")).reset_index())
r = r[r["Linea"].isin(c.LINEAS)]

c.subtitulo("Regla 2: sin los agentes excluidos")
fuera = r[r["Agente"].isin(c.AGENTES_EXCLUIDOS)]
c.mostrar(fuera.groupby("Agente").agg(filas=("Venta", "size"), venta=("Venta", "sum")).reset_index())
r = r[~r["Agente"].isin(c.AGENTES_EXCLUIDOS)].copy()

c.subtitulo("Se conservan (venta neta): notas de crédito y cancelaciones")
c.mostrar(r.groupby(["Tipo documento", "Cancelado"]).agg(filas=("Venta", "size"), venta=("Venta", "sum")).reset_index())

# ------------------------------------------------------------------ 2. Columnas nuevas
v = pd.DataFrame({
    "empresa": r["Empresa"], "codigo": r["Cod Articulo"],
    "key_id": r["Empresa"] + "-" + r["Cod Articulo"],
    "fecha": r["Fecha Doc"], "anio": r["Fecha Doc"].dt.year, "mes": r["Fecha Doc"].dt.month,
    "linea": r["Linea"], "agente": r["Agente"], "agente_actual": r["Agente actual"],
    "rfc": r["RFC Cliente"], "cod_cliente": r["Cod Cliente"], "cliente": r["Cliente"],
    "descripcion": r["Descripción"], "clase_original": r["Clase ET"],
    "unidad": r["U de Medida"].str.upper(), "fabricante": r["FABRICANTE CORRECTO"],
    "tipo_doc": r["Tipo documento"], "cancelado": r["Cancelado"], "no_doc": r["No Documento"],
    "cantidad": r["Cantidad"], "venta": r["Venta"], "utilidad": r["Utilidad B II"],
    "fila_excel": r["fila_excel"],
})
v["es_muestra"] = v["clase_original"].map(c.norm) == "MUESTRA"

# Ajustes contables: filas sin empresa, sin producto y sin cliente. Cuentan en el total
# de la línea (así lo reporta la pestaña VIP) pero no pertenecen a ningún producto.
v["es_ajuste"] = (v["empresa"] == "") | (v["codigo"].isin(["", "0"]))
v.loc[v["es_ajuste"], "key_id"] = "AJUSTE-SIN-PRODUCTO"

# Llave del cliente: el RFC. Los RFC genéricos (extranjeros o público en general) no identifican
# a nadie, así que ahí se usa el nombre.
generico = v["rfc"].str.upper().str.startswith(("XAXX", "XEXX")) | v["rfc"].isin(["", "0"])
v["cliente_id"] = v["rfc"].str.upper()
v.loc[generico, "cliente_id"] = "SIN_RFC-" + v.loc[generico, "cliente"].map(c.norm)
v.loc[v["es_ajuste"], ["cliente_id", "cliente"]] = ["AJUSTE", "AJUSTE SIN CLIENTE"]
# Un solo nombre por cliente: el más reciente
nombre = v.sort_values("fecha").groupby("cliente_id")["cliente"].last()
v["cliente"] = v["cliente_id"].map(nombre)

# Precio en dólares: venta entre cantidad (Precio U viene en la moneda de la factura)
v["precio_usd"] = (v["venta"] / v["cantidad"]).where(v["cantidad"] != 0)

# ------------------------------------------------------------------ 3. Validación contra VIP
c.subtitulo("Validación: venta por línea y año contra la pestaña VIP")
mio = v.groupby(["linea", "anio"])["venta"].sum().rename("venta_codigo").reset_index()
comp = vip.merge(mio, on=["linea", "anio"], how="left")
comp["diferencia"] = comp["venta_codigo"] - comp["venta_vip"]
tabla = comp.pivot(index="linea", columns="etiqueta", values="diferencia").reindex(c.LINEAS)
print("Diferencia en USD (código menos VIP). Debe ser prácticamente cero en todas las celdas:")
print(tabla.to_string())
peor = comp["diferencia"].abs().max()
(c.ok if peor <= 1 else c.aviso)(f"Mayor diferencia contra VIP: {peor:,.2f} USD (tolerancia: 1.00)")

# ------------------------------------------------------------------ 4. Otros controles
c.subtitulo("Controles")
c.control("Filas de ventas", len(v), ESPERADO["filas_ventas"])
c.control("Venta total", v["venta"].sum(), ESPERADO["venta_total"], 1)
c.control("Productos distintos (key_id)", v["key_id"].nunique(), ESPERADO["productos"])
c.control("Clientes distintos (cliente_id)", v["cliente_id"].nunique(), ESPERADO["clientes"])
c.control("Filas de ajuste (sin empresa ni producto)", int(v["es_ajuste"].sum()), ESPERADO["filas_ajuste"])
if v["es_ajuste"].any():
    print("Filas de ajuste. Cuentan en el total de su línea, pero no en ninguna clase:")
    c.mostrar(v.loc[v["es_ajuste"], ["fila_excel", "fecha", "linea", "tipo_doc", "venta"]])
print(f"Filas con RFC genérico o vacío (usan el nombre como llave): {int(generico.sum()):,} "
      f"| venta {v.loc[generico, 'venta'].sum():,.2f}")
print(f"Filas marcadas como Muestra en el origen: {int(v['es_muestra'].sum()):,} "
      f"| venta {v.loc[v['es_muestra'], 'venta'].sum():,.2f}")

c.subtitulo("Venta por línea y año (millones USD)")
print((v.pivot_table(index="linea", columns="anio", values="venta", aggfunc="sum") / 1e6)
      .reindex(c.LINEAS).round(2).to_string())
c.subtitulo("Venta 2025 y 2026 por empresa y mes (millones USD). Revisa que no falten meses")
rec = v[v["anio"] >= 2025]
print((rec.pivot_table(index=["anio", "empresa"], columns="mes", values="venta", aggfunc="sum") / 1e6)
      .round(2).fillna(0).to_string())
ultimo = v["fecha"].max()
print(f"\nÚltima factura: {ultimo:%d-%m-%Y}. Último mes con datos: {ultimo:%m-%Y}")

c.guardar_cache(cfg, "ventas", v)
print(f"Guardado: {c.ruta_cache(cfg, 'ventas')}")
c.cierre("PASO 1")
