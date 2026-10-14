"""Paso 8. Dispersión por agente: reparte lo revisado por los gerentes y genera la hoja de cada agente.

Entrada : consulta/cache/filas_gerentes.parquet, ventas.parquet y consulta/catalogo.xlsx
Salida  : consulta/agentes_nombres.xlsx                  (para unificar nombres de agentes; editable)
          consulta/agentes_clientes.xlsx                 (agente vigente de cada cliente; editable)
          output/precios_agentes/Precios_<AGENTE>.xlsx   (una por agente; se respeta el precio que verifiquen)
          output/presupuesto_por_agente.xlsx             (cuánto del presupuesto le toca a cada agente)
          consulta/cache/presupuesto_2027.parquet        (por mes) y presupuesto_2027_anual.parquet
Correr  : py src/08_agentes.py   (una vez para generar las hojas y otra vez cuando regresen)
"""
import re

import numpy as np
import pandas as pd

import comun as c

CAMBIO_PRECIO = 20          # % de cambio de precio que se lista para confirmar
ANIO = 2027

cfg = c.cargar_config()
CARPETA = cfg["carpeta_output"] / "precios_agentes"
CARPETA.mkdir(exist_ok=True)
RUTA_NOM = cfg["carpeta_consulta"] / "agentes_nombres.xlsx"
RUTA_CLI = cfg["carpeta_consulta"] / "agentes_clientes.xlsx"
c.titulo("PASO 8. DISPERSIÓN POR AGENTE")
ventas = c.leer_cache(cfg, "ventas", "01_ventas.py")
filas = c.leer_cache(cfg, "filas_gerentes", "07_gerentes.py")
base = c.leer_cache(cfg, "base", "04_base.py")
patron = c.patron_mensual(base[base["version"] == "REAL"])
cat = pd.read_excel(cfg["carpeta_consulta"] / "catalogo.xlsx", dtype=str).fillna("")
v, ult, FIN = c.mezcla_reciente(ventas, cat)


def limpio(s):
    return re.sub(r"[\u200e\u200f]", "", str(s)).strip()


# ------------------------------------------------------------------ 1. Nombres de agentes (para unir duplicados)
ult = ult.assign(agente=ult["agente"].map(limpio))
nom = ult.groupby("agente", as_index=False).agg(venta_12m=("venta", "sum"), clientes=("cliente_id", "nunique"))
nom = nom.rename(columns={"agente": "nombre_en_facturas"}).sort_values("venta_12m", ascending=False)
nom["nombre_final"] = nom["nombre_en_facturas"]
if RUTA_NOM.exists():
    prev = pd.read_excel(RUTA_NOM, dtype=str).fillna("").drop_duplicates("nombre_en_facturas").set_index("nombre_en_facturas")
    anterior = nom["nombre_en_facturas"].map(prev["nombre_final"])
    nom["nombre_final"] = anterior.where(anterior.notna() & (anterior != ""), nom["nombre_final"]).map(limpio)
c.escribir_excel(nom[["nombre_en_facturas", "nombre_final", "clientes", "venta_12m"]], RUTA_NOM, hoja="agentes")
ult = ult.assign(agente=ult["agente"].map(nom.set_index("nombre_en_facturas")["nombre_final"]))
c.subtitulo("Agentes en las facturas de los últimos 12 meses")
c.mostrar(ult.groupby("agente").agg(clientes=("cliente_id", "nunique"), venta_12m=("venta", "sum")).reset_index()
          .sort_values("venta_12m", ascending=False))
print("Si dos nombres son la misma persona, escribe el mismo 'nombre_final' en agentes_nombres.xlsx y vuelve a correr.")

# ------------------------------------------------------------------ 2. Agente de cada cliente
por_cli = ult.groupby(["linea", "cliente_id", "agente"], as_index=False)["venta"].sum()
por_cli = por_cli[por_cli["venta"] > 0]
por_cli["parte"] = por_cli["venta"] / por_cli.groupby(["linea", "cliente_id"])["venta"].transform("sum")
texto = por_cli.sort_values("parte", ascending=False).groupby(["linea", "cliente_id"]).apply(
    lambda g: " | ".join(f"{a} {100 * q:.0f}%" for a, q in zip(g["agente"], g["parte"]))).rename("agentes_12m")
cli = ult.groupby(["linea", "cliente_id"], as_index=False).agg(cliente=("cliente", "last"), venta_12m=("venta", "sum"))
cli = cli.merge(texto.reset_index(), on=["linea", "cliente_id"], how="left")
cli["n_agentes"] = cli["agentes_12m"].fillna("").str.count(r"\|") + 1
cli["agente_vigente"] = ""
if RUTA_CLI.exists():
    prev = pd.read_excel(RUTA_CLI, dtype=str).fillna("").drop_duplicates(["linea", "cliente_id"]).set_index(["linea", "cliente_id"])
    cli["agente_vigente"] = [limpio(prev["agente_vigente"].get(k, "")) for k in zip(cli["linea"], cli["cliente_id"])]
c.escribir_excel(cli.sort_values(["n_agentes", "venta_12m"], ascending=[False, False])
                 [["linea", "cliente_id", "cliente", "venta_12m", "n_agentes", "agentes_12m", "agente_vigente"]],
                 RUTA_CLI, hoja="clientes", anchos={"cliente": 40, "agentes_12m": 70})
varios = cli[cli["n_agentes"] > 1]
c.subtitulo("Clientes con más de un agente en los últimos 12 meses")
print(f"{len(varios)} de {len(cli)} combinaciones de cliente y línea, con {100 * varios['venta_12m'].sum() / cli['venta_12m'].sum():.0f}% "
      f"de la venta. Con agente vigente escrito: {int((cli['agente_vigente'] != '').sum())}")
print("Regla: si escribes 'agente_vigente' en agentes_clientes.xlsx, ese agente recibe todo el cliente. Si lo dejas")
print("vacío, cada fila se reparte según qué agente la facturó en los últimos 12 meses.")
c.mostrar(varios.sort_values("venta_12m", ascending=False)[["linea", "cliente", "venta_12m", "agentes_12m"]], 12)

# ------------------------------------------------------------------ 3. Repartir cada fila entre agentes
vigente = {k: a for k, a in zip(zip(cli["linea"], cli["cliente_id"]), cli["agente_vigente"]) if a}
por_fila = ult.groupby(["linea", "cliente_id", "producto", "agente"], as_index=False)["venta"].sum()
por_fila = por_fila[por_fila["venta"] > 0]
por_fila["parte"] = por_fila["venta"] / por_fila.groupby(["linea", "cliente_id", "producto"])["venta"].transform("sum")
idx_fila = {k: g[["agente", "parte"]].values.tolist() for k, g in por_fila.groupby(["linea", "cliente_id", "producto"])}
idx_cli = {k: g[["agente", "parte"]].values.tolist() for k, g in por_cli.groupby(["linea", "cliente_id"])}
partes = []
for i, f in filas.iterrows():
    k_cli = (f["linea"], f["cliente_id"])
    if k_cli in vigente:
        reparto, regla = [[vigente[k_cli], 1.0]], "agente vigente"
    elif (f["linea"], f["cliente_id"], f["producto"]) in idx_fila:
        reparto, regla = idx_fila[(f["linea"], f["cliente_id"], f["producto"])], "facturas de la fila"
    elif k_cli in idx_cli:
        reparto, regla = idx_cli[k_cli], "facturas del cliente"
    else:
        reparto, regla = [["POR DEFINIR", 1.0]], "sin agente"
    for agente, parte in reparto:
        partes.append((i, agente, parte, regla))
partes = pd.DataFrame(partes, columns=["i", "agente", "parte", "regla"])
d = partes.merge(filas, left_on="i", right_index=True)
d["cantidad"] = d["cantidad_2027"] * d["parte"]
d["venta_gerente"] = d["venta_final"] * d["parte"]
d["precio_gerente"] = d["precio_2027"]
d["id_fila"] = d["linea"] + "|" + d["cliente_id"] + "|" + d["clase_et"] + "|" + d["producto"] + "|" + d["agente"]
fac = v[(v["tipo_doc"] == "Factura") & (v["cantidad"] > 0) & (v["venta"] > 0)].sort_values("fecha")
ultima = fac.groupby(["linea", "cliente_id", "producto"]).agg(precio_ultima_factura=("precio_usd", "last"), fecha_ultima_factura=("fecha", "last"))
d = d.merge(ultima, on=["linea", "cliente_id", "producto"], how="left")
d["fecha_ultima_factura"] = d["fecha_ultima_factura"].dt.strftime("%Y-%m-%d").fillna("")
d["parte_del_agente_%"] = (100 * d["parte"]).round(0)
d["precio_verificado"], d["comentario"] = np.nan, ""

# ------------------------------------------------------------------ 4. Hojas por agente (respetando lo ya escrito)
previos = [pd.read_excel(a) for a in CARPETA.glob("Precios_*.xlsx")]
if previos:
    escrito = pd.concat(previos, ignore_index=True)
    escrito = escrito[escrito["id_fila"].notna()].drop_duplicates("id_fila").set_index("id_fila")
    d["precio_verificado"] = pd.to_numeric(d["id_fila"].map(escrito["precio_verificado"]), errors="coerce")
    d["comentario"] = d["id_fila"].map(escrito["comentario"]).fillna("").astype(str).replace("nan", "")
    for a in CARPETA.glob("Precios_*.xlsx"):          # se regeneran todas: un agente puede haber cambiado de clientes
        a.unlink()
COLS = ["linea", "cliente", "clase_et", "producto", "unidad", "parte_del_agente_%", "cantidad", "precio_gerente",
        "precio_ultima_factura", "fecha_ultima_factura", "precio_verificado", "comentario", "id_fila"]
for agente, g in d.groupby("agente"):
    nombre = re.sub(r"[^A-Za-z0-9ÁÉÍÓÚÑáéíóúñ]+", "_", agente).strip("_")
    g = g.sort_values(["linea", "cliente", "venta_gerente"], ascending=[True, True, False])
    c.escribir_excel(g[COLS], CARPETA / f"Precios_{nombre}.xlsx", hoja="precios",
                     anchos={"cliente": 34, "producto": 52, "clase_et": 28, "id_fila": 10, "comentario": 35})

# ------------------------------------------------------------------ 5. Presupuesto final
d["precio_final"] = d["precio_verificado"].where(d["precio_verificado"].notna(), d["precio_gerente"])
d["venta_final_agente"] = d["cantidad"] * d["precio_final"]
meses = []
for mes in range(1, 13):
    w = d["linea"].map(lambda l: patron.loc[l, mes])
    meses.append(pd.DataFrame({"anio": ANIO, "mes": mes, "linea": d["linea"], "agente": d["agente"], "cliente_id": d["cliente_id"],
                               "cliente": d["cliente"], "clase_et": d["clase_et"], "producto": d["producto"], "key_ref": d["key_ref"],
                               "unidad": d["unidad"], "cantidad": d["cantidad"] * w, "precio": d["precio_final"],
                               "venta_gerentes": d["venta_gerente"] * w, "venta": d["venta_final_agente"] * w}))
ppto = pd.concat(meses, ignore_index=True)
c.guardar_cache(cfg, "presupuesto_2027", ppto)
c.guardar_cache(cfg, "presupuesto_2027_anual", d.drop(columns=["i"]))
cuota = d.pivot_table(index="agente", columns="linea", values="venta_final_agente", aggfunc="sum").reindex(columns=c.LINEAS).fillna(0)
cuota["TOTAL"] = cuota.sum(axis=1)
cuota = cuota.sort_values("TOTAL", ascending=False)
por_mes = ppto.pivot_table(index="agente", columns="mes", values="venta", aggfunc="sum").reindex(cuota.index).fillna(0)
detalle = d.groupby(["agente", "linea", "cliente"], as_index=False).agg(venta_2027=("venta_final_agente", "sum")) \
    .sort_values(["agente", "venta_2027"], ascending=[True, False])
c.escribir_excel({"por_agente": cuota.reset_index(), "por_mes": por_mes.reset_index(), "por_cliente": detalle},
                 cfg["carpeta_output"] / "presupuesto_por_agente.xlsx", anchos={"cliente": 40})

c.subtitulo("Presupuesto 2027 por agente (millones USD)")
vista = (cuota / 1e6).round(2)
vista.insert(0, "filas", d.groupby("agente").size().reindex(cuota.index))
vista.insert(1, "clientes", d.groupby("agente")["cliente_id"].nunique().reindex(cuota.index))
print(vista.to_string())
c.subtitulo("Cómo se asignó el agente")
c.mostrar(d.groupby("regla").agg(filas=("venta_gerente", "size"), venta=("venta_gerente", "sum")).reset_index())

c.subtitulo("Precios verificados por los agentes")
ver = d[d["precio_verificado"].notna()].copy()
if len(ver) == 0:
    print("Todavía no hay precios verificados. Comparte las hojas de output/precios_agentes. Cada agente escribe en")
    print("'precio_verificado' el precio de venta en USD por unidad solo si es distinto de 'precio_gerente'.")
else:
    ver["cambio_%"] = (100 * (ver["precio_verificado"] / ver["precio_gerente"] - 1)).round(1)
    efecto = 100 * ((ver["cantidad"] * ver["precio_verificado"]).sum() / (ver["cantidad"] * ver["precio_gerente"]).sum() - 1)
    print(f"Precios verificados: {len(ver):,} | efecto en la venta de esas filas: {efecto:+.1f}%")
    fuertes = ver[ver["cambio_%"].abs() >= CAMBIO_PRECIO]
    (c.ok if len(fuertes) == 0 else c.aviso)(f"Cambios de precio de {CAMBIO_PRECIO}% o más: {len(fuertes)}. Confirma con el agente")
    c.mostrar(fuertes[["agente", "cliente", "producto", "precio_gerente", "precio_verificado", "cambio_%", "comentario"]], 30)

c.subtitulo("Controles")
c.control("Lo repartido entre agentes = lo revisado por gerentes", d["venta_gerente"].sum(), filas["venta_final"].sum(), 1)
dif = abs(ppto["venta"].sum() - d["venta_final_agente"].sum())
(c.ok if dif < 1 else c.aviso)(f"La suma mensual coincide con la anual (diferencia {dif:,.2f})")
sin = d[d["agente"] == "POR DEFINIR"]
print(f"Sin agente (reserva y altas sin historia): {len(sin)} filas, {sin['venta_gerente'].sum():,.0f} USD. Quedan en Precios_POR_DEFINIR.xlsx")
print(f"\nHojas en: {CARPETA}")
c.cierre("PASO 8")
