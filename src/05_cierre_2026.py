"""Paso 5. Cierre 2026: ventas reales + estimado de los meses que faltan.

Entrada : consulta/cache/base.parquet y ordenes.parquet, consulta/catalogo.xlsx
Salida  : consulta/ordenes_revision.xlsx      (los gerentes marcan cada orden; se respetan sus cambios)
          consulta/cierre_2026_ajustes.xlsx   (opcional: un número por línea si el gerente lo corrige)
          output/cierre_2026.xlsx             (entregable)
          consulta/cache/cierre_2026.parquet  (para los pasos siguientes)
Correr  : py src/05_cierre_2026.py
"""
import pandas as pd

import comun as c

DECISIONES = ["CIERRA_2026", "PASA_2027", "DUDOSA"]
ALERTA_ORDENES = 1.3        # aviso si las órdenes firmes superan 1.3 veces el ritmo de la línea

cfg = c.cargar_config()
RUTA_ORD = cfg["carpeta_consulta"] / "ordenes_revision.xlsx"
RUTA_AJ = cfg["carpeta_consulta"] / "cierre_2026_ajustes.xlsx"
RUTA_OUT = cfg["carpeta_output"] / "cierre_2026.xlsx"
c.titulo("PASO 5. CIERRE 2026: real + estimado de los meses que faltan")

base = c.leer_cache(cfg, "base", "04_base.py")
o = c.leer_cache(cfg, "ordenes", "00_preparar.py")
cat = pd.read_excel(cfg["carpeta_consulta"] / "catalogo.xlsx", dtype=str).fillna("")
clase_de = cat.set_index("key_id")["clase_et"].map(c.norm)

real = base[base["version"] == "REAL"]
real26 = real[real["anio"] == 2026]
ULTIMO = int(real26["mes"].max())                       # último mes con ventas reales
FALTAN = list(range(ULTIMO + 1, 13))
print(f"Último mes real de 2026: {ULTIMO}. Meses por estimar: {FALTAN}")
if not FALTAN:
    raise SystemExit("El año 2026 ya está completo: no hay nada que estimar.")
pesos = c.patron_mensual(real)
factor = {l: pesos.loc[l, FALTAN].sum() / pesos.loc[l, list(range(1, ULTIMO + 1))].sum() for l in c.LINEAS}

# ------------------------------------------------------------------ 1. Órdenes: hoja para que marquen los gerentes
c.subtitulo("Órdenes abiertas: decisión de los gerentes")
o = o[o["linea"].isin(c.LINEAS)].copy()
o["key_id"] = c.EMPRESA_ORDENES + "-" + o["codigo"]
o["clase_et"] = o["key_id"].map(clase_de).fillna("SIN CATALOGO")
o["mes_entrega"] = o["fecha_entrega"].dt.month
o["anio_entrega"] = o["fecha_entrega"].dt.year
base_id = o["documento"] + "|" + o["codigo"] + "|" + o["fecha_entrega"].dt.strftime("%Y-%m-%d")
o["id_orden"] = base_id + "|" + (o.groupby(base_id).cumcount() + 1).astype(str)
por_cliente = o.groupby(["linea", "cliente"])["usd_abierto"].transform("sum")
por_linea = o.groupby("linea")["usd_abierto"].transform("sum")
alertas = []
for i, f in o.iterrows():
    a = []
    if f["fecha_orden"].year < 2026:
        a.append(f"ORDEN ANTIGUA ({f['fecha_orden'].year})")
    if por_cliente[i] / por_linea[i] >= 0.15:
        a.append("CLIENTE CONCENTRA 15% O MÁS DE LA LÍNEA")
    if f["usd_abierto"] >= 100000:
        a.append("MONTO ALTO")
    alertas.append("; ".join(a))
o["alerta"] = alertas
o["decision"] = "CIERRA_2026"
o["comentario"] = ""
if RUTA_ORD.exists():
    previo = pd.read_excel(RUTA_ORD, dtype=str).fillna("").drop_duplicates("id_orden").set_index("id_orden")
    for col in ("decision", "comentario"):
        anterior = o["id_orden"].map(previo[col])
        o[col] = anterior.where(anterior.notna() & (anterior != ""), o[col])
    print(f"Ya existía ordenes_revision.xlsx: se respetaron {int(o['id_orden'].isin(previo.index).sum()):,} decisiones.")
o["decision"] = o["decision"].str.upper().str.strip().str.replace(" ", "_")
malas = o[~o["decision"].isin(DECISIONES)]
if len(malas):
    c.aviso(f"{len(malas)} órdenes tienen una decisión no válida (se toman como DUDOSA). Valores válidos: {DECISIONES}")
    o.loc[malas.index, "decision"] = "DUDOSA"
hoja = o[["id_orden", "linea", "cliente", "clase_et", "descripcion", "fecha_orden", "fecha_entrega",
          "cantidad_abierta", "unidad", "usd_abierto", "alerta", "decision", "comentario"]].copy()
hoja["fecha_orden"] = hoja["fecha_orden"].dt.strftime("%Y-%m-%d")
hoja["fecha_entrega"] = hoja["fecha_entrega"].dt.strftime("%Y-%m-%d")
hoja = hoja.sort_values(["linea", "alerta", "usd_abierto"], ascending=[True, False, False])
c.escribir_excel(hoja, RUTA_ORD, hoja="ordenes", anchos={"descripcion": 50, "alerta": 45, "cliente": 35})
c.mostrar((o.pivot_table(index="linea", columns="decision", values="usd_abierto", aggfunc="sum") / 1e6)
          .reindex(c.LINEAS).round(2).fillna(0).reset_index())
con_alerta = o[o["alerta"] != ""]
print(f"Órdenes con alerta: {len(con_alerta):,} de {len(o):,} ({con_alerta['usd_abierto'].sum() / 1e6:,.2f} de "
      f"{o['usd_abierto'].sum() / 1e6:,.2f} millones). Son las primeras que deben revisar los gerentes.")

firmes = o[(o["decision"] == "CIERRA_2026") & (o["anio_entrega"] == 2026) & (o["mes_entrega"].isin(FALTAN))]
piso = firmes.groupby(["linea", "clase_et", "mes_entrega"])["usd_abierto"].sum().rename("piso").reset_index() \
    .rename(columns={"mes_entrega": "mes"})

# ------------------------------------------------------------------ 2. Estimado por línea
c.subtitulo("Estimado de los meses que faltan, por línea (millones USD)")
productos = real26[real26["clase_et"] != "AJUSTE SIN PRODUCTO"]
ytd = productos.groupby(["linea", "clase_et"])["venta"].sum().clip(lower=0).rename("ytd").reset_index()
ytd["ritmo"] = ytd["ytd"] * ytd["linea"].map(factor)            # lo que vendería al ritmo del año
ppto = base[base["version"] == "PPTO_2026"]
lin = pd.DataFrame({
    "real_a_la_fecha": real26.groupby("linea")["venta"].sum(),
    "ordenes_firmes": piso.groupby("linea")["piso"].sum(),
    "ritmo_del_anio": ytd.groupby("linea")["ritmo"].sum(),
    "ppto_restante": ppto[ppto["mes"].isin(FALTAN)].groupby("linea")["venta"].sum(),
    "ppto_a_la_fecha": ppto[~ppto["mes"].isin(FALTAN)].groupby("linea")["venta"].sum(),
}).reindex(c.LINEAS).fillna(0)
lin["cumplimiento"] = lin["real_a_la_fecha"] / lin["ppto_a_la_fecha"]
lin["ppto_restante_ajustado"] = lin["ppto_restante"] * lin["cumplimiento"]
# Regla: las órdenes firmes son el piso; si no alcanzan el ritmo del año, se usa el ritmo.
lin["estimado_resto"] = lin[["ordenes_firmes", "ritmo_del_anio"]].max(axis=1)
lin["origen_estimado"] = (lin["ordenes_firmes"] >= lin["ritmo_del_anio"]).map({True: "órdenes", False: "ritmo"})

# Corrección opcional del gerente: un número por línea
if not RUTA_AJ.exists():
    c.escribir_excel(pd.DataFrame({"linea": c.LINEAS, "estimado_resto_gerente": "", "comentario": ""}),
                     RUTA_AJ, hoja="ajustes")
aj = pd.read_excel(RUTA_AJ).set_index("linea")["estimado_resto_gerente"]
aj = pd.to_numeric(aj, errors="coerce").dropna()
for l, valor in aj.items():
    if l in lin.index:
        if valor < lin.loc[l, "ordenes_firmes"]:
            c.aviso(f"{l}: el gerente estimó {valor:,.0f}, menos que las órdenes firmes "
                    f"({lin.loc[l, 'ordenes_firmes']:,.0f}). Revisa las decisiones de las órdenes.")
        lin.loc[l, ["estimado_resto", "origen_estimado"]] = [valor, "gerente"]
lin["cierre_2026"] = lin["real_a_la_fecha"] + lin["estimado_resto"]
lin["cierre_metodo_actual"] = lin["real_a_la_fecha"] + lin["ppto_restante"]     # como la pestaña PROYECCION (8+4)
num = lin.select_dtypes("number").columns.drop("cumplimiento")
vista = lin.copy()
vista[num] = (vista[num] / 1e6).round(2)
vista["cumplimiento"] = (vista["cumplimiento"] * 100).round(1)
print(vista.T.to_string())
print("\nCómo leerlo: 'estimado_resto' es lo que se usa. 'ppto_restante' y 'ppto_restante_ajustado' son referencias.")
for l in c.LINEAS:
    if lin.loc[l, "ordenes_firmes"] > ALERTA_ORDENES * lin.loc[l, "ritmo_del_anio"]:
        c.aviso(f"{l}: las órdenes firmes ({lin.loc[l, 'ordenes_firmes'] / 1e6:,.2f} M) superan {ALERTA_ORDENES} veces "
                f"el ritmo del año ({lin.loc[l, 'ritmo_del_anio'] / 1e6:,.2f} M). Probablemente no todas se facturan "
                "en 2026: pide al gerente marcar las que PASAN a 2027.")

# ------------------------------------------------------------------ 3. Bajar el estimado a clase y mes
# Cada clase recibe al menos sus órdenes firmes. Lo que falta para llegar al estimado de la línea
# se reparte entre las clases cuyo ritmo no está cubierto por órdenes.
piso_clase = piso.groupby(["linea", "clase_et"])["piso"].sum().rename("piso").reset_index()
t = ytd.merge(piso_clase, on=["linea", "clase_et"], how="outer").fillna(0)
t["descubierto"] = (t["ritmo"] - t["piso"]).clip(lower=0)
filas = []
for l, g in t.groupby("linea"):
    falta = max(lin.loc[l, "estimado_resto"] - g["piso"].sum(), 0)
    if g["descubierto"].sum() > 0:
        reparto = g["descubierto"] / g["descubierto"].sum() * falta
    else:
        reparto = pd.Series(0.0, index=g.index)
    escala = 1.0
    if lin.loc[l, "estimado_resto"] < g["piso"].sum() and g["piso"].sum() > 0:      # el gerente bajó el piso
        escala = lin.loc[l, "estimado_resto"] / g["piso"].sum()
    w = pesos.loc[l, FALTAN] / pesos.loc[l, FALTAN].sum()
    pm = piso[piso["linea"] == l].set_index(["clase_et", "mes"])["piso"]
    for clase, extra in zip(g["clase_et"], reparto):
        for m in FALTAN:
            filas.append({"linea": l, "clase_et": clase, "mes": m,
                          "venta": pm.get((clase, m), 0.0) * escala + extra * w[m]})
est = pd.DataFrame(filas)
est = est[est["venta"].abs() > 0.005]
est["tipo"] = "ESTIMADO"
rr = real26.groupby(["linea", "clase_et", "mes"], as_index=False)["venta"].sum()
rr["tipo"] = "REAL"
cierre = pd.concat([rr, est], ignore_index=True)
cierre["anio"] = 2026
c.guardar_cache(cfg, "cierre_2026", cierre)
pasan = o[o["decision"] == "PASA_2027"].groupby(["linea", "clase_et"], as_index=False)["usd_abierto"].sum()
c.guardar_cache(cfg, "ordenes_2027", pasan.rename(columns={"usd_abierto": "ordenes_2027"}))

# ------------------------------------------------------------------ 4. Entregable y controles
por_clase = cierre.pivot_table(index=["linea", "clase_et"], columns="tipo", values="venta", aggfunc="sum").fillna(0)
por_clase["cierre_2026"] = por_clase.sum(axis=1)
por_clase["venta_2025"] = real[real["anio"] == 2025].groupby(["linea", "clase_et"])["venta"].sum()
por_clase = por_clase.fillna(0).reset_index().sort_values(["linea", "cierre_2026"], ascending=[True, False])
por_mes = cierre.pivot_table(index="linea", columns="mes", values="venta", aggfunc="sum").reindex(c.LINEAS)
with pd.ExcelWriter(RUTA_OUT, engine="openpyxl") as w:
    lin.reset_index().rename(columns={"index": "linea"}).to_excel(w, sheet_name="por_linea", index=False)
    por_mes.reset_index().to_excel(w, sheet_name="por_mes", index=False)
    por_clase.to_excel(w, sheet_name="por_clase", index=False)

c.subtitulo("Cierre 2026 por línea y mes (millones USD). Los meses estimados son los últimos")
print((por_mes / 1e6).round(2).to_string())
c.subtitulo("Controles")
dif = abs(cierre.groupby("linea")["venta"].sum().reindex(c.LINEAS) - lin["cierre_2026"]).max()
(c.ok if dif < 1 else c.aviso)(f"La suma por clase coincide con el cierre por línea (diferencia máxima {dif:,.2f})")
neg = int((est["venta"] < 0).sum())
(c.ok if neg == 0 else c.aviso)(f"Meses estimados negativos: {neg}")
print(f"\nCierre 2026 estimado: {lin['cierre_2026'].sum() / 1e6:,.2f} millones "
      f"(con el método actual, real + presupuesto restante: {lin['cierre_metodo_actual'].sum() / 1e6:,.2f}; "
      f"presupuesto anual: {ppto['venta'].sum() / 1e6:,.2f}).")
print(f"Guardado: {RUTA_OUT}\nGuardado: {RUTA_ORD}\nGuardado: {RUTA_AJ}")
c.cierre("PASO 5")
