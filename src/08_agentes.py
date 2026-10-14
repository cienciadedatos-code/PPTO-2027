"""Paso 8. Dispersión por agente: reparte lo revisado por los gerentes y genera la hoja de cada agente.

Entrada : consulta/cache/filas_gerentes.parquet, ventas.parquet, ppto2026.parquet y consulta/catalogo.xlsx

Regla del agente de cada fila (cliente + producto), en este orden:
  1. El 'agente_vigente' escrito a mano en agentes_clientes.xlsx.
  2. El agente del presupuesto 2026 para esa línea y cliente: la última fila que aparece en la pestaña
     BD PPTO 2026, igual que la columna NUEVA ASIGNACIO AGENTES de la BD GENERAL original.
  3. El agente que más le facturó esa fila (cliente + producto) en los últimos 12 meses; si la fila no
     tiene facturas, el que más le facturó al cliente en esa línea.
  4. Si no hay nada: POR DEFINIR.
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
ppto26 = c.leer_cache(cfg, "ppto2026", "00_preparar.py")
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
solo_ppto = sorted(set(ppto26["agente"].map(limpio)) - set(nom["agente"]) - {""})
nom = pd.concat([nom, pd.DataFrame({"agente": solo_ppto, "venta_12m": 0.0, "clientes": 0})], ignore_index=True)
nom = nom.rename(columns={"agente": "nombre_en_facturas"}).sort_values("venta_12m", ascending=False)
nom["nombre_final"] = nom["nombre_en_facturas"]
if RUTA_NOM.exists():
    prev = pd.read_excel(RUTA_NOM, dtype=str).fillna("").drop_duplicates("nombre_en_facturas").set_index("nombre_en_facturas")
    anterior = nom["nombre_en_facturas"].map(prev["nombre_final"])
    nom["nombre_final"] = anterior.where(anterior.notna() & (anterior != ""), nom["nombre_final"]).map(limpio)
c.escribir_excel(nom[["nombre_en_facturas", "nombre_final", "clientes", "venta_12m"]], RUTA_NOM, hoja="agentes")
nombre_final = nom.set_index("nombre_en_facturas")["nombre_final"]
ult = ult.assign(agente=ult["agente"].map(nombre_final))
c.subtitulo("Agentes en las facturas de los últimos 12 meses")
c.mostrar(ult.groupby("agente").agg(clientes=("cliente_id", "nunique"), venta_12m=("venta", "sum")).reset_index()
          .sort_values("venta_12m", ascending=False))
print("Si dos nombres son la misma persona, escribe el mismo 'nombre_final' en agentes_nombres.xlsx y vuelve a correr.")

# ------------------------------------------------------------------ 2. Agente de cada cliente
# a) Del presupuesto 2026: la última fila de cada línea + cliente (como el XLOOKUP de la BD GENERAL original)
p26 = ppto26.copy()
p26["agente"] = p26["agente"].map(limpio)
p26["agente"] = p26["agente"].map(nombre_final).fillna(p26["agente"])
generico = p26["rfc"].str.upper().str.startswith(("XAXX", "XEXX")) | p26["rfc"].isin(["", "0"])
p26["cliente_id"] = p26["rfc"].str.upper()
p26.loc[generico, "cliente_id"] = "SIN_RFC-" + p26.loc[generico, "cliente"].map(c.norm)
p26 = p26[p26["agente"] != ""]
agente_ppto = p26.groupby(["linea", "cliente_id"])["agente"].last().to_dict()
agente_ppto_nombre = p26.assign(n=p26["cliente"].map(c.norm)).groupby(["linea", "n"])["agente"].last().to_dict()


def del_ppto(linea, cliente_id, cliente):
    if (linea, cliente_id) in agente_ppto:
        return agente_ppto[(linea, cliente_id)]
    return agente_ppto_nombre.get((linea, c.norm(cliente)), "")


# b) De las facturas: quién más le facturó
por_cli = ult.groupby(["linea", "cliente_id", "agente"], as_index=False)["venta"].sum()
por_cli = por_cli[por_cli["venta"] > 0]
por_cli["parte"] = por_cli["venta"] / por_cli.groupby(["linea", "cliente_id"])["venta"].transform("sum")
texto = por_cli.sort_values("parte", ascending=False).groupby(["linea", "cliente_id"]).apply(
    lambda g: " | ".join(f"{a} {100 * q:.0f}%" for a, q in zip(g["agente"], g["parte"]))).rename("agentes_12m")
mayor_cli = por_cli.sort_values("venta").groupby(["linea", "cliente_id"])["agente"].last().to_dict()
por_fila = ult.groupby(["linea", "cliente_id", "producto", "agente"], as_index=False)["venta"].sum()
mayor_fila = por_fila[por_fila["venta"] > 0].sort_values("venta").groupby(["linea", "cliente_id", "producto"])["agente"].last().to_dict()

cli = ult.groupby(["linea", "cliente_id"], as_index=False).agg(cliente=("cliente", "last"), venta_12m=("venta", "sum"))
cli = cli.merge(texto.reset_index(), on=["linea", "cliente_id"], how="left")
cli["agente_ppto_2026"] = [del_ppto(l, k, n) for l, k, n in zip(cli["linea"], cli["cliente_id"], cli["cliente"])]
cli["agente_mas_facturo"] = [mayor_cli.get(k, "") for k in zip(cli["linea"], cli["cliente_id"])]
cli["difieren"] = ((cli["agente_ppto_2026"] != "") & (cli["agente_ppto_2026"] != cli["agente_mas_facturo"])).map({True: "SI", False: ""})
cli["agente_vigente"] = ""
if RUTA_CLI.exists():
    prev = pd.read_excel(RUTA_CLI, dtype=str).fillna("").drop_duplicates(["linea", "cliente_id"]).set_index(["linea", "cliente_id"])
    cli["agente_vigente"] = [limpio(prev["agente_vigente"].get(k, "")) for k in zip(cli["linea"], cli["cliente_id"])]
cli["agente_asignado"] = cli["agente_vigente"].where(cli["agente_vigente"] != "",
                                                     cli["agente_ppto_2026"].where(cli["agente_ppto_2026"] != "", cli["agente_mas_facturo"]))
cli["regla"] = np.where(cli["agente_vigente"] != "", "1 vigente (manual)",
                        np.where(cli["agente_ppto_2026"] != "", "2 presupuesto 2026", "3 el que más facturó"))
c.escribir_excel(cli.sort_values(["difieren", "venta_12m"], ascending=[False, False])
                 [["linea", "cliente_id", "cliente", "venta_12m", "agente_ppto_2026", "agente_mas_facturo", "difieren",
                   "agentes_12m", "agente_vigente", "agente_asignado", "regla"]],
                 RUTA_CLI, hoja="clientes", anchos={"cliente": 40, "agentes_12m": 60, "agente_ppto_2026": 30, "agente_mas_facturo": 30})

c.subtitulo("Agente de cada cliente")
print("Regla: 1) agente_vigente escrito a mano; 2) el del presupuesto 2026 (como la BD GENERAL original);")
print("3) el que más facturó en los últimos 12 meses.")
r = cli.groupby("regla").agg(clientes=("cliente_id", "size"), venta_12m=("venta_12m", "sum")).reset_index()
r["% venta"] = (100 * r["venta_12m"] / r["venta_12m"].sum()).round(1)
c.mostrar(r)
dif = cli[cli["difieren"] == "SI"]
print(f"\nClientes donde el presupuesto 2026 y las facturas dicen agentes distintos: {len(dif)} "
      f"({100 * dif['venta_12m'].sum() / cli['venta_12m'].sum():.1f}% de la venta). Se usa el del presupuesto;")
print("si alguno está mal, escribe el correcto en 'agente_vigente' de agentes_clientes.xlsx. Los más grandes:")
c.mostrar(dif.sort_values("venta_12m", ascending=False)[["linea", "cliente", "venta_12m", "agente_ppto_2026", "agente_mas_facturo"]], 15)

# ------------------------------------------------------------------ 3. Asignar cada fila a un agente
vigente = {k: a for k, a in zip(zip(cli["linea"], cli["cliente_id"]), cli["agente_vigente"]) if a}
asignados = []
for f in filas.itertuples():
    k_cli = (f.linea, f.cliente_id)
    if k_cli in vigente:
        agente, regla = vigente[k_cli], "1 vigente (manual)"
    elif del_ppto(f.linea, f.cliente_id, f.cliente):
        agente, regla = del_ppto(f.linea, f.cliente_id, f.cliente), "2 presupuesto 2026"
    elif (f.linea, f.cliente_id, f.producto) in mayor_fila:
        agente, regla = mayor_fila[(f.linea, f.cliente_id, f.producto)], "3 el que más facturó la fila"
    elif k_cli in mayor_cli:
        agente, regla = mayor_cli[k_cli], "3 el que más facturó al cliente"
    else:
        agente, regla = "POR DEFINIR", "4 sin agente"
    asignados.append((agente, regla))
d = filas.copy()
d["agente"], d["regla"] = [a for a, _ in asignados], [r for _, r in asignados]
d["parte"] = 1.0
d["cantidad"] = d["cantidad_2027"] * d["parte"]
d["venta_gerente"] = d["venta_final"] * d["parte"]
d["precio_gerente"] = d["precio_2027"]
d["id_fila"] = d["linea"] + "|" + d["cliente_id"] + "|" + d["clase_et"] + "|" + d["producto"] + "|" + d["agente"]
fac = v[(v["tipo_doc"] == "Factura") & (v["cantidad"] > 0) & (v["venta"] > 0)].sort_values("fecha")
ultima = fac.groupby(["linea", "cliente_id", "producto"]).agg(precio_ultima_factura=("precio_usd", "last"), fecha_ultima_factura=("fecha", "last"))
d = d.merge(ultima, on=["linea", "cliente_id", "producto"], how="left")
d["fecha_ultima_factura"] = d["fecha_ultima_factura"].dt.strftime("%Y-%m-%d").fillna("")
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
COLS = ["linea", "cliente", "clase_et", "producto", "unidad", "cantidad", "precio_gerente",
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
c.guardar_cache(cfg, "presupuesto_2027_anual", d)
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
