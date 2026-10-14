"""Paso 4. BD GENERAL limpia: ventas, órdenes abiertas y presupuesto 2026 en una sola tabla.

Entrada : ventas.parquet, ordenes.parquet, ppto2026.parquet y consulta/catalogo.xlsx
Salida  : output/bd_general_limpia.xlsx            (entregable)
          consulta/equivalencias_ppto.xlsx          (lo editas tú; el script respeta tus cambios)
          consulta/cache/base.parquet               (para los pasos siguientes)
Correr  : py src/04_base.py
"""
import pandas as pd

import comun as c

# Cifras de control del archivo 0__VIP_2027_V1_0.xlsx. Si cambias el Excel, cambian.
ESPERADO = {"venta_real": 544977338.50, "usd_ordenes": 32757878.46, "usd_ppto": 123095049.13}

cfg = c.cargar_config()
RUTA_CAT = cfg["carpeta_consulta"] / "catalogo.xlsx"
RUTA_EQ = cfg["carpeta_consulta"] / "equivalencias_ppto.xlsx"
RUTA_OUT = cfg["carpeta_output"] / "bd_general_limpia.xlsx"
c.titulo("PASO 4. BASE LIMPIA: ventas + órdenes abiertas + presupuesto 2026")

v = c.leer_cache(cfg, "ventas", "01_ventas.py")
o = c.leer_cache(cfg, "ordenes", "00_preparar.py")
p = c.leer_cache(cfg, "ppto2026", "00_preparar.py")
if not RUTA_CAT.exists():
    raise SystemExit("ERROR: falta consulta/catalogo.xlsx. Corre primero 02_catalogo.py.")
cat = pd.read_excel(RUTA_CAT, dtype=str).fillna("")
cat["clase_et"] = cat["clase_et"].map(c.norm)
clase_de = cat.set_index("key_id")["clase_et"]
pendientes = cat[cat["estado"].str.lower().str.strip() != "ok"]
if len(pendientes):
    c.aviso(f"El catálogo tiene {len(pendientes)} productos en 'revisar'. La base se arma con su clase "
            "actual; vuelve a correr este paso cuando los resuelvas.")

# ------------------------------------------------------------------ 1. Ventas reales (por mes)
filas_antes, venta_antes = len(v), v["venta"].sum()
v["clase_et"] = v["key_id"].map(clase_de)
v.loc[v["es_ajuste"], "clase_et"] = "AJUSTE SIN PRODUCTO"
v["clase_et"] = v["clase_et"].fillna("SIN CATALOGO")
# Control: traer la clase no debe borrar ni duplicar nada
assert len(v) == filas_antes and abs(v["venta"].sum() - venta_antes) < 0.01, "Se alteraron las ventas al traer la clase"
desc_ref = cat.set_index("key_id")["descripcion"]
fab_ref = cat.set_index("key_id")["fabricante"]
v["descripcion_ref"] = v["key_id"].map(desc_ref).fillna("")
v["fabricante_ref"] = v["key_id"].map(fab_ref).fillna("")
real = v.groupby(["anio", "mes", "linea", "cliente_id", "cliente", "key_id", "clase_et"], as_index=False).agg(
    agente=("agente", "last"), descripcion=("descripcion_ref", "first"), fabricante=("fabricante_ref", "first"),
    unidad=("unidad", "last"), cantidad=("cantidad", "sum"), venta=("venta", "sum"), utilidad=("utilidad", "sum"))
real.insert(0, "version", "REAL")

# ------------------------------------------------------------------ 2. Órdenes abiertas (por mes de entrega)
c.subtitulo("Órdenes abiertas")
fuera = o[~o["linea"].isin(c.LINEAS)]
print(f"Órdenes fuera de las cinco líneas (no entran): {len(fuera)} filas, {fuera['usd_abierto'].sum():,.2f} USD")
o = o[o["linea"].isin(c.LINEAS)].copy()
o["key_id"] = c.EMPRESA_ORDENES + "-" + o["codigo"]
o["clase_et"] = o["key_id"].map(clase_de).fillna("SIN CATALOGO")
generico = o["rfc"].str.upper().str.startswith(("XAXX", "XEXX")) | o["rfc"].isin(["", "0"])
o["cliente_id"] = o["rfc"].str.upper()
o.loc[generico, "cliente_id"] = "SIN_RFC-" + o.loc[generico, "cliente"].map(c.norm)
nombre = v.sort_values("fecha").groupby("cliente_id")["cliente"].last()
o["cliente"] = o["cliente_id"].map(nombre).fillna(o["cliente"])
o["anio"], o["mes"] = o["fecha_entrega"].dt.year, o["fecha_entrega"].dt.month
ordenes = o.groupby(["anio", "mes", "linea", "cliente_id", "cliente", "key_id", "clase_et"], as_index=False).agg(
    agente=("agente", "last"), descripcion=("descripcion", "first"), fabricante=("fabricante", "first"),
    unidad=("unidad", "last"), cantidad=("cantidad_abierta", "sum"), venta=("usd_abierto", "sum"))
ordenes["utilidad"] = 0.0
ordenes.insert(0, "version", "ORDENES")
print(f"AVISO PERMANENTE: la pestaña de órdenes no trae empresa; se asume {c.EMPRESA_ORDENES} en todas.")

# ------------------------------------------------------------------ 3. Presupuesto 2026 (traducir sus clases)
c.subtitulo("Presupuesto 2026: equivalencia de clases")
p = p[p["venta"] != 0].copy()
p["clase_n"] = p["clase_ppto"].map(c.limpiar_clase)
clases_cat = cat.groupby(["linea", "clase_et"])["venta_12m"].apply(lambda s: pd.to_numeric(s).sum()).reset_index()
por_linea = {l: g.set_index("clase_et")["venta_12m"].to_dict() for l, g in clases_cat.groupby("linea")}


def sugerir(linea, clase):
    """Busca la clase del catálogo que corresponde a una clase del presupuesto."""
    opciones = por_linea.get(linea, {})
    if clase in opciones:
        return clase, "ok", "IGUAL"
    compacto = {c.solo_letras_numeros(k): k for k in opciones}
    if c.solo_letras_numeros(clase) in compacto:
        return compacto[c.solo_letras_numeros(clase)], "ok", "IGUAL SALVO ESPACIOS O SIGNOS"
    # el presupuesto es más detallado: "CAPSULA 0 HGC 0000 NATURAL" -> "CAPSULA 0"
    inicios = [k for k in opciones if clase.startswith(k) and (len(clase) == len(k) or not clase[len(k)].isalnum())]
    if inicios:
        return max(inicios, key=len), "revisar", "EL PRESUPUESTO ES MÁS DETALLADO"
    # el catálogo es más detallado: "OMEPRAZOL PELLETS" -> "OMEPRAZOL PELLETS 8.5%"
    largas = [k for k in opciones if k.startswith(clase) and not k[len(clase)].isalnum()]
    if len(largas) == 1:
        return largas[0], "revisar", "EL CATÁLOGO ES MÁS DETALLADO"
    if len(largas) > 1:
        return max(largas, key=lambda k: opciones[k]), "revisar", "VARIAS CLASES DEL CATÁLOGO EMPIEZAN IGUAL"
    return "", "revisar", "SIN EQUIVALENTE: escribe la clase del catálogo o deja la del presupuesto"


eq = p.groupby(["linea", "clase_n"], as_index=False).agg(clase_ppto=("clase_ppto", "first"), ppto_2026=("venta", "sum"))
sug = eq.apply(lambda f: sugerir(f["linea"], f["clase_n"]), axis=1, result_type="expand")
eq["clase_sugerida"], eq["estado"], eq["motivo"] = sug[0], sug[1], sug[2]
eq["clase_catalogo"] = eq["clase_sugerida"]
eq["comentario"] = ""
conservadas = 0
if RUTA_EQ.exists():
    previo = pd.read_excel(RUTA_EQ, dtype=str).fillna("")
    previo["llave"] = previo["linea"] + "|" + previo["clase_n"]
    previo = previo.drop_duplicates("llave").set_index("llave")
    llave = eq["linea"] + "|" + eq["clase_n"]
    for col in ("clase_catalogo", "estado", "comentario"):
        anterior = llave.map(previo[col])
        eq[col] = anterior.where(anterior.notna(), eq[col])
    conservadas = int(llave.isin(previo.index).sum())
    eq["clase_catalogo"] = eq["clase_catalogo"].map(c.norm)
    eq["estado"] = eq["estado"].str.lower().str.strip()
eq = eq[["linea", "clase_ppto", "clase_n", "clase_sugerida", "clase_catalogo", "estado", "motivo",
         "comentario", "ppto_2026"]].sort_values(["estado", "ppto_2026"], ascending=[False, False])
c.escribir_excel(eq, RUTA_EQ, hoja="equivalencias", anchos={"clase_ppto": 45, "clase_sugerida": 40, "motivo": 50})
if conservadas:
    print(f"Ya existía equivalencias_ppto.xlsx: se respetaron tus decisiones en {conservadas:,} clases.")

mapa = eq.set_index(eq["linea"] + "|" + eq["clase_n"])["clase_catalogo"]
p["clase_et"] = (p["linea"] + "|" + p["clase_n"]).map(mapa)
sin_nombre = p["clase_n"].where(~p["clase_n"].isin(["", "0"]), "SIN CLASE")
p["clase_et"] = p["clase_et"].where(p["clase_et"].fillna("") != "", "PPTO: " + sin_nombre)
gen = p["rfc"].str.upper().str.startswith(("XAXX", "XEXX")) | p["rfc"].isin(["", "0"])
p["cliente_id"] = p["rfc"].str.upper()
p.loc[gen, "cliente_id"] = "SIN_RFC-" + p.loc[gen, "cliente"].map(c.norm)
p["cliente"] = p["cliente_id"].map(nombre).fillna(p["cliente"])
ppto = p.groupby(["anio", "mes", "linea", "cliente_id", "cliente", "clase_et"], as_index=False).agg(
    agente=("agente", "last"), fabricante=("fabricante", "first"), venta=("venta", "sum"))
ppto["key_id"], ppto["descripcion"], ppto["unidad"] = "", "", ""
ppto["cantidad"], ppto["utilidad"] = 0.0, 0.0
ppto.insert(0, "version", "PPTO_2026")

res = eq.groupby(["estado", "motivo"]).agg(clases=("clase_n", "size"), ppto_2026=("ppto_2026", "sum")).reset_index()
res["% del ppto"] = (100 * res["ppto_2026"] / res["ppto_2026"].sum()).round(1)
c.mostrar(res.sort_values(["estado", "ppto_2026"], ascending=[True, False]))
c.subtitulo("PENDIENTES: clases del presupuesto por revisar (las de mayor monto primero)")
c.mostrar(eq.loc[eq["estado"] != "ok", ["linea", "clase_ppto", "clase_catalogo", "motivo", "ppto_2026"]], 40)

# ------------------------------------------------------------------ 4. Apilar y guardar
columnas = ["version", "anio", "mes", "linea", "cliente_id", "cliente", "agente", "key_id", "clase_et",
            "descripcion", "fabricante", "unidad", "cantidad", "venta", "utilidad"]
base = pd.concat([real[columnas], ordenes[columnas], ppto[columnas]], ignore_index=True)
base["precio_usd"] = (base["venta"] / base["cantidad"]).where(base["cantidad"] != 0)
c.guardar_cache(cfg, "base", base)
print("\nEscribiendo el Excel entregable (tarda cerca de un minuto)...")
c.escribir_excel(base, RUTA_OUT, hoja="bd_general", anchos={"cliente": 40, "descripcion": 55, "clase_et": 35})

# ------------------------------------------------------------------ 5. Controles
c.subtitulo("Controles")
tot = base.groupby("version")["venta"].sum()
c.control("Venta REAL en la base = venta del paso 1", tot["REAL"], ESPERADO["venta_real"], 1)
c.control("ÓRDENES en la base (cinco líneas)", tot["ORDENES"], ESPERADO["usd_ordenes"], 1)
c.control("PRESUPUESTO 2026 en la base", tot["PPTO_2026"], ESPERADO["usd_ppto"], 1)
sin_cat = base[base["clase_et"] == "SIN CATALOGO"]
(c.ok if len(sin_cat) == 0 else c.aviso)(f"Filas sin clase en el catálogo: {len(sin_cat)} "
                                         f"(venta {sin_cat['venta'].sum():,.2f}). Corre 02_catalogo.py para agregarlas")
sin_eq = base[base["clase_et"].str.startswith("PPTO: ")]
(c.ok if len(sin_eq) == 0 else c.aviso)(
    f"Presupuesto 2026 sin equivalencia: {sin_eq['venta'].sum():,.0f} USD en {sin_eq['clase_et'].nunique()} clases "
    "(quedan con el prefijo 'PPTO: '). Resuélvelas en equivalencias_ppto.xlsx")
rev = eq[eq["estado"] != "ok"]
(c.ok if len(rev) == 0 else c.aviso)(f"Equivalencias por revisar: {len(rev)} clases, "
                                     f"{rev['ppto_2026'].sum():,.0f} USD de presupuesto")

c.subtitulo("Resumen de la base (millones USD)")
print((base.pivot_table(index="linea", columns=["version", "anio"], values="venta", aggfunc="sum") / 1e6)
      .reindex(c.LINEAS).round(2).fillna(0).to_string())
print(f"\nFilas: {len(base):,} | clases: {base['clase_et'].nunique():,} | clientes: {base['cliente_id'].nunique():,}")
c.mostrar(base.groupby("version").agg(filas=("venta", "size"), venta=("venta", "sum")).reset_index())
print(f"\nGuardado: {RUTA_OUT}\nGuardado: {RUTA_EQ}")
c.cierre("PASO 4")
