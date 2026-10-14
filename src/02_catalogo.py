"""Paso 2. Catálogo de productos: una fila por producto con su Clase ET.

Entrada : consulta/cache/ventas.parquet (paso 1) y ordenes.parquet (paso 0)
Salida  : consulta/catalogo.xlsx  (lo editas tú; el script respeta tus cambios)
Correr  : py src/02_catalogo.py
"""
from difflib import SequenceMatcher

import pandas as pd

import comun as c

# Cifras de control del archivo 0__VIP_2027_V1_0.xlsx. Si cambias el Excel, cambian.
ESPERADO = {"productos": 2387}
MAYORIA_CLARA = 0.90      # si una clase tiene 90% o más de las facturas del producto, gana sola
MONTO_MUESTRA = 5000      # muestras por arriba de este monto se listan para revisión

cfg = c.cargar_config()
RUTA = cfg["carpeta_consulta"] / "catalogo.xlsx"
c.titulo("PASO 2. CATÁLOGO: una clase por producto")
v = c.leer_cache(cfg, "ventas", "01_ventas.py")
o = c.leer_cache(cfg, "ordenes", "00_preparar.py")
v = v[~v["es_ajuste"]].copy()
hoy = v["fecha"].max()
hace_12m = hoy - pd.DateOffset(months=12)
v["clase_limpia"] = v["clase_original"].map(c.limpiar_clase)


def es_inicio(a, b):
    """a es el inicio de b y termina en límite de palabra."""
    return bool(a) and b.startswith(a) and (len(b) == len(a) or not b[len(a)].isalnum())


# ------------------------------------------------------------------ 1. Una fila por producto
def resumen(key_id, g):
    g = g.sort_values("fecha")
    clases = g.loc[g["clase_limpia"] != "MUESTRA", "clase_limpia"].value_counts()
    return {
        "key_id": key_id, "empresa": g["empresa"].iat[0], "codigo": g["codigo"].iat[0],
        "linea": g["linea"].value_counts().index[0],
        "descripcion": g["descripcion"].iat[-1],
        "fabricante": g["fabricante"].value_counts().index[0],
        "unidad": g["unidad"].iat[-1],
        "clases_vistas": " | ".join(f"{k} ({n})" for k, n in clases.items()) or "MUESTRA",
        "n_clases": len(clases),
        "clase_mayoria": clases.index[0] if len(clases) else "MUESTRA",
        "parte_mayoria": clases.iat[0] / clases.sum() if len(clases) else 1.0,
        "lista_clases": list(clases.index),
        "venta_12m": g.loc[g["fecha"] > hace_12m, "venta"].sum(),
        "venta_total": g["venta"].sum(),
        "ultima_venta": g["fecha"].iat[-1].strftime("%Y-%m-%d"),
    }


cat = pd.DataFrame([resumen(k, g) for k, g in v.groupby("key_id")])


def decidir(f):
    cl = f["lista_clases"]
    if f["n_clases"] == 0:                                   # solo aparece como Muestra
        if f["venta_total"] >= MONTO_MUESTRA:
            return "revisar", "MUESTRA CON VENTA ALTA: parece producto real, confirma su clase", \
                c.nombre_desde_descripcion(f["descripcion"])
        return "ok", "", "MUESTRA"
    if f["n_clases"] == 1:
        return "ok", "", f["clase_mayoria"]
    if f["parte_mayoria"] >= MAYORIA_CLARA:
        return "ok", "CORREGIDO: tenía otra clase en pocas facturas, ganó la mayoría", f["clase_mayoria"]
    misma_raiz = all(es_inicio(a, b) or es_inicio(b, a) for a in cl for b in cl if a != b)
    if misma_raiz:
        return "revisar", "NIVEL: mismo nombre con distinto detalle, decide cuál queda", f["clase_mayoria"]
    return "revisar", "CLASES DISTINTAS: ninguna tiene mayoría clara", f["clase_mayoria"]


dec = cat.apply(decidir, axis=1, result_type="expand")
cat["estado"], cat["motivo"], cat["clase_sugerida"] = dec[0], dec[1], dec[2]

# Dos revisiones más para los que quedaron en "ok":
# a) El mismo producto (descripción idéntica) con otra clase en otra empresa o código.
cat["desc_norm"] = cat["descripcion"].map(c.norm)
reales = cat[cat["clase_sugerida"] != "MUESTRA"]
varias = reales.groupby("desc_norm")["clase_sugerida"].agg(lambda s: sorted(set(s)))
varias = varias[varias.map(len) > 1]
choca = cat["desc_norm"].isin(varias.index) & (cat["estado"] == "ok") & (cat["clase_sugerida"] != "MUESTRA")
cat.loc[choca, "estado"] = "revisar"
cat.loc[choca, "motivo"] = "MISMO PRODUCTO CON OTRA CLASE EN OTRO CÓDIGO: " + \
    cat.loc[choca, "desc_norm"].map(lambda d: " | ".join(varias[d]))
# b) La clase no comparte ninguna palabra con la descripción: puede ser sinónimo o error.
def palabras(t):
    return set(w for w in c.norm(t).replace("-", " ").replace("/", " ").split() if len(w) > 2)


def clase_ajena(f):
    clase, desc = f["clase_sugerida"], f["descripcion"]
    if palabras(clase) & palabras(desc):
        return False
    if c.solo_letras_numeros(clase) in c.solo_letras_numeros(desc):        # "UC-II" dentro de "UC-II® 1H2"
        return False
    parecido = SequenceMatcher(None, clase, c.nombre_desde_descripcion(desc)).ratio()
    return parecido < 0.8                                                  # tolera una letra distinta


ajena = cat.apply(clase_ajena, axis=1) & (cat["estado"] == "ok") & (cat["clase_sugerida"] != "MUESTRA")
cat.loc[ajena, "estado"] = "revisar"
cat.loc[ajena, "motivo"] = "CLASE SIN PALABRAS DE LA DESCRIPCIÓN: confirma que es sinónimo y no error"

# ------------------------------------------------------------------ 2. Misma clase escrita distinto
# "STEPAN MILD" y "STEPAN-MILD" son la misma clase: se queda la forma que más vende.
cat["clave_escritura"] = cat["clase_sugerida"].map(c.solo_letras_numeros)
peso = cat.assign(v=cat["venta_total"].abs() + 1).groupby(["clave_escritura", "clase_sugerida"])["v"].sum()
ganadora = peso.reset_index().sort_values("v", ascending=False).drop_duplicates("clave_escritura") \
    .set_index("clave_escritura")["clase_sugerida"]
nueva = cat["clave_escritura"].map(ganadora)
unificadas = cat.loc[nueva != cat["clase_sugerida"], ["clase_sugerida"]].assign(queda_como=nueva)
cat["clase_sugerida"] = nueva

# ------------------------------------------------------------------ 3. Productos nuevos (solo en órdenes)
o["key_id"] = c.EMPRESA_ORDENES + "-" + o["codigo"]
nuevos = o[~o["key_id"].isin(cat["key_id"])].sort_values("fecha_entrega").groupby("key_id").agg(
    codigo=("codigo", "first"), linea=("linea", "first"), descripcion=("descripcion", "last"),
    fabricante=("fabricante", "first"), unidad=("unidad", "last"),
    clase_sugerida=("clase_original", lambda s: c.limpiar_clase(s.iloc[-1])),
    usd_ordenes=("usd_abierto", "sum")).reset_index()
clases_conocidas = set(cat["clase_sugerida"])
nuevos["empresa"] = c.EMPRESA_ORDENES
nuevos["clases_vistas"] = nuevos["clase_sugerida"] + " (solo órdenes)"
existe = nuevos["clase_sugerida"].isin(clases_conocidas)
nuevos["estado"] = existe.map({True: "ok", False: "revisar"})
nuevos["motivo"] = existe.map({True: "NUEVO: sin ventas, su clase ya existe",
                               False: "NUEVO: sin ventas y su clase no existe en el catálogo"})
nuevos["venta_12m"] = 0.0
nuevos["venta_total"] = 0.0
nuevos["ultima_venta"] = ""
cat = pd.concat([cat, nuevos], ignore_index=True)

# ------------------------------------------------------------------ 4. Respetar lo que ya decidiste
cat["clase_et"] = cat["clase_sugerida"]
cat["comentario"] = ""
conservadas = 0
if RUTA.exists():
    previo = pd.read_excel(RUTA, dtype=str).fillna("")
    previo = previo.set_index("key_id")
    for col in ("clase_et", "estado", "comentario"):
        anterior = cat["key_id"].map(previo[col]) if col in previo.columns else None
        if anterior is not None:
            cat[col] = anterior.where(anterior.notna() & (anterior != ""), cat[col])
    conservadas = int(cat["key_id"].isin(previo.index).sum())
    cat["clase_et"] = cat["clase_et"].map(c.norm)
    cat["estado"] = cat["estado"].str.lower().str.strip()

columnas = ["key_id", "empresa", "codigo", "linea", "descripcion", "fabricante", "unidad",
            "clases_vistas", "clase_sugerida", "clase_et", "estado", "motivo", "comentario",
            "venta_12m", "venta_total", "ultima_venta"]
cat = cat[columnas].sort_values(["estado", "venta_12m"], ascending=[False, False])
c.escribir_excel(cat, RUTA, hoja="catalogo", anchos={"descripcion": 55, "clases_vistas": 60, "motivo": 45})

# ------------------------------------------------------------------ 5. Lo que se imprime
c.subtitulo("Resumen del catálogo")
print(f"Productos: {len(cat):,} ({len(nuevos)} nuevos que solo aparecen en órdenes abiertas)")
print(f"Clases distintas: {cat['clase_et'].nunique():,}")
if conservadas:
    print(f"Ya existía catalogo.xlsx: se respetaron tus decisiones en {conservadas:,} productos.")
resumen_motivos = cat.assign(tipo=cat["motivo"].str.split(":").str[0]).groupby(["estado", "tipo"]).agg(
    productos=("key_id", "size"), venta_12m=("venta_12m", "sum")).reset_index()
c.mostrar(resumen_motivos.sort_values(["estado", "productos"], ascending=[True, False]))

c.subtitulo("Clases a las que la regla les quitó el empaque")
cambio = v[v["clase_limpia"] != v["clase_original"].map(c.norm)]
c.mostrar(cambio.assign(antes=cambio["clase_original"].map(c.norm)).groupby(["antes", "clase_limpia"])
          .agg(filas=("venta", "size"), venta=("venta", "sum")).reset_index().sort_values("venta", ascending=False))

c.subtitulo("Clases con dos escrituras que se unificaron")
c.mostrar(unificadas.drop_duplicates().sort_values("queda_como"))

c.subtitulo(f"Muestras de más de {MONTO_MUESTRA:,} USD. Revisa si en realidad son ventas")
m = v[v["es_muestra"] & (v["venta"] >= MONTO_MUESTRA)].merge(cat[["key_id", "clase_et"]], on="key_id")
print("Estas filas se suman a la clase de su producto (columna clase_et):")
c.mostrar(m[["fila_excel", "fecha", "linea", "cliente", "descripcion", "cantidad", "venta", "clase_et"]]
          .sort_values("venta", ascending=False))

c.subtitulo("PENDIENTES: productos con estado 'revisar' (los de mayor venta primero)")
pend = cat[cat["estado"] != "ok"]
c.mostrar(pend[["key_id", "linea", "descripcion", "clases_vistas", "clase_et", "motivo", "venta_12m"]], 40)

c.subtitulo("Controles")
c.control("Productos en el catálogo", len(cat), ESPERADO["productos"])
dup = int(cat["key_id"].duplicated().sum())
(c.ok if dup == 0 else c.aviso)(f"Productos repetidos en el catálogo: {dup}")
vacias = int((cat["clase_et"] == "").sum())
(c.ok if vacias == 0 else c.aviso)(f"Productos sin clase: {vacias}")
faltan = int((~v["key_id"].isin(cat["key_id"])).sum())
(c.ok if faltan == 0 else c.aviso)(f"Facturas cuyo producto no está en el catálogo: {faltan}")
n = len(pend)
(c.ok if n == 0 else c.aviso)(f"Productos por revisar: {n} (venta 12 meses {pend['venta_12m'].sum():,.0f}). "
                              "Ábrelos en catalogo.xlsx, corrige clase_et y cambia estado a ok")
print(f"\nGuardado: {RUTA}")
c.cierre("PASO 2")
