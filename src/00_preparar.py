"""Paso 0. Lee el Excel una sola vez y guarda una copia rápida de cada pestaña.

Entrada : raw/0__VIP_2027_V1_0.xlsx
Salida  : consulta/cache/rentabilidad.parquet, ordenes.parquet, ppto2026.parquet, vip.parquet
Correr  : py src/00_preparar.py   (vuelve a correrlo solo si cambia el Excel)
"""
import time

import pandas as pd

import comun as c

# Cifras de control del archivo 0__VIP_2027_V1_0.xlsx. Si cambias el Excel, cambian.
ESPERADO = {"filas_rentabilidad": 89991, "filas_ordenes": 1761, "filas_ppto": 43980,
            "venta_rentabilidad": 552162277.74, "usd_ordenes": 32787825.62, "usd_ppto": 123095049.13}

inicio = time.time()
cfg = c.cargar_config()
c.titulo("PASO 0. PREPARAR: leer el Excel y guardar la copia rápida")
print("Excel:", cfg["raw_excel"].name, f"({cfg['raw_excel'].stat().st_size / 1e6:,.0f} MB)")

try:
    import python_calamine  # noqa: F401
    motor = "calamine"
except ImportError:
    motor = "openpyxl"
    c.aviso("No está instalado python-calamine; uso el lector lento (puede tardar varios minutos).")
libro = pd.ExcelFile(cfg["raw_excel"], engine=motor)
hojas = {h.strip(): h for h in libro.sheet_names}        # algunos nombres traen espacios al final


def leer(nombre, **kw):
    if nombre not in hojas:
        raise SystemExit(f"ERROR: no encuentro la pestaña '{nombre}'. Pestañas: {list(hojas)}")
    t = time.time()
    df = libro.parse(hojas[nombre], dtype=object, **kw)
    df.columns = [str(col).strip() for col in df.columns]
    print(f"  {nombre}: {len(df):,} filas, {df.shape[1]} columnas ({time.time() - t:.0f} s)")
    return df


# ------------------------------------------------------------------ BD RENTABILIDAD
c.subtitulo("Leyendo pestañas")
r = leer(c.HOJA_RENTABILIDAD)
cols_texto = ["Empresa", "Tipo documento", "Cancelado", "Serie Documento", "No Documento", "Cod Cliente",
              "Cliente", "Moneda", "Cod Articulo", "Descripción", "U de Medida", "Linea", "Agente",
              "RFC Cliente", "Clase ET", "Agente actual", "PROVEEDOR CORRECTO", "FABRICANTE CORRECTO"]
cols_num = ["Cantidad", "Precio U", "Venta", "Utilidad B II"]
faltan = [x for x in cols_texto + cols_num + ["Fecha Doc"] if x not in r.columns]
if faltan:
    raise SystemExit(f"ERROR: faltan columnas en {c.HOJA_RENTABILIDAD}: {faltan}")
rent = pd.DataFrame({col: c.texto(r[col]) for col in cols_texto})
for col in cols_num:
    rent[col] = c.numero(r[col])
rent["Fecha Doc"] = c.fecha(r["Fecha Doc"])
rent["fila_excel"] = range(2, len(rent) + 2)             # para ubicar cada fila en el Excel
del r

# ------------------------------------------------------------------ Órdenes abiertas
o = leer(c.HOJA_ORDENES)
ordenes = pd.DataFrame({
    "documento": c.texto(o["NUMERO DE DOCUMENTO"]),
    "cod_cliente": c.texto(o["CODIGO CLIENTE"]),
    "cliente": c.texto(o["CLIENTE"]),
    "rfc": c.texto(o["RFC"]),
    "linea": c.texto(o["LINEA DE NEGOCIO"]),
    "codigo": c.texto(o["CODIGO PRODUCTO"]),
    "descripcion": c.texto(o["DESCRIPCION"]),
    "fabricante": c.texto(o["FABRICANTE"]),
    "unidad": c.texto(o["UNIDAD DE MEDIDA"]),
    "agente": c.texto(o["AGENTE"]),
    "clase_original": c.texto(o["CLASE ET"]),
    "cantidad_abierta": c.numero(o["CANTIDAD ABIERTA RESTANTE"]),
    "precio": c.numero(o["PRECIO"]),
    "usd_abierto": c.numero(o["TOTAL USD ABIERTO"]),
    "fecha_entrega": c.fecha(o["FECHA DE ENTREGA"]),
    "fecha_orden": c.fecha(o["FECHA DE CONTABILIZACION"]),
})
ordenes["fila_excel"] = range(2, len(ordenes) + 2)

# ------------------------------------------------------------------ Presupuesto 2026
p = leer(c.HOJA_PPTO)
ppto = pd.DataFrame({
    "linea": c.texto(p["Linea"]),
    "rfc": c.texto(p["RFC Cliente"]),
    "cliente": c.texto(p["Cliente"]),
    "clase_ppto": c.texto(p["Clase ET"]),
    "agente": c.texto(p["Agente"]),
    "fabricante": c.texto(p["FABRICANTE"]),
    "mes_txt": c.texto(p["MES"]),
    "anio": c.numero(p["Año"]).astype(int),
    "venta": c.numero(p["$"]),
})
MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
         "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12}
ppto["mes"] = ppto["mes_txt"].str.lower().str[:3].map(MESES)

# ------------------------------------------------------------------ Pestaña VIP (para validar)
v = leer(c.HOJA_VIP, header=None)
# La pestaña tiene varias tablas; la primera (ventas en USD) es la que sirve
fila_lineas = []
for i in v.index:
    nombre = str(v.iat[i, 0]).strip()
    if nombre in c.LINEAS and nombre not in [str(v.iat[k, 0]).strip() for k in fila_lineas]:
        fila_lineas.append(i)
fila_anios = fila_lineas[0] - 1
vip, anios_vistos = [], set()
for j in range(1, v.shape[1]):
    etiqueta = str(v.iat[fila_anios, j]).strip()
    encabezado = str(v.iat[fila_anios - 1, j]).upper()
    if not etiqueta[:4].isdigit() or "VENTAS" not in encabezado:
        continue
    if etiqueta[:4] in anios_vistos:                     # "2026 (4)" y "2026 (8+4)" son estimados: se saltan
        continue
    anios_vistos.add(etiqueta[:4])
    for i in fila_lineas:
        vip.append({"linea": str(v.iat[i, 0]).strip(), "anio": int(float(etiqueta[:4])),
                    "etiqueta": etiqueta, "venta_vip": float(v.iat[i, j])})
vip = pd.DataFrame(vip)

# ------------------------------------------------------------------ Guardar y controlar
c.guardar_cache(cfg, "rentabilidad", rent)
c.guardar_cache(cfg, "ordenes", ordenes)
c.guardar_cache(cfg, "ppto2026", ppto)
c.guardar_cache(cfg, "vip", vip)

c.subtitulo("Controles")
c.control("Filas de BD RENTABILIDAD", len(rent), ESPERADO["filas_rentabilidad"])
c.control("Filas de órdenes abiertas", len(ordenes), ESPERADO["filas_ordenes"])
c.control("Filas de presupuesto 2026", len(ppto), ESPERADO["filas_ppto"])
c.control("Venta total en BD RENTABILIDAD (sin filtrar)", rent["Venta"].sum(), ESPERADO["venta_rentabilidad"], 1)
c.control("Órdenes abiertas en USD", ordenes["usd_abierto"].sum(), ESPERADO["usd_ordenes"], 1)
c.control("Presupuesto 2026 en USD", ppto["venta"].sum(), ESPERADO["usd_ppto"], 1)
sin_fecha = int(rent["Fecha Doc"].isna().sum())
(c.ok if sin_fecha <= 10 else c.aviso)(f"Filas de rentabilidad sin fecha: {sin_fecha} (esperado: 10 o menos)")
print(f"\nPeriodo de facturas: {rent['Fecha Doc'].min():%d-%m-%Y} a {rent['Fecha Doc'].max():%d-%m-%Y}")
print(f"Entrega de órdenes : {ordenes['fecha_entrega'].min():%d-%m-%Y} a {ordenes['fecha_entrega'].max():%d-%m-%Y}")
print("Años en VIP        :", sorted(vip["etiqueta"].unique()))
print(f"Tiempo total: {time.time() - inicio:.0f} s. Copia guardada en {cfg['carpeta_consulta'] / 'cache'}")
c.cierre("PASO 0")
