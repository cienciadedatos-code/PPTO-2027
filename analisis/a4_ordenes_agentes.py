"""Análisis 4. Órdenes abiertas contra el ritmo de venta, y agentes por cliente.

Respalda las decisiones del paso 5 (las órdenes no son piso automático) y del paso 8 (reparto por agente).
Correr: py analisis/a4_ordenes_agentes.py   (necesita haber corrido hasta el paso 4)
"""
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import comun as c  # noqa: E402

cfg = c.cargar_config()
c.titulo("ANÁLISIS 4. ÓRDENES ABIERTAS Y AGENTES")
ventas = c.leer_cache(cfg, "ventas", "01_ventas.py")
o = c.leer_cache(cfg, "ordenes", "00_preparar.py")
o = o[o["linea"].isin(c.LINEAS)]
v = ventas[~ventas["es_ajuste"]]
FIN = v["fecha"].max()

c.subtitulo("1. ¿Cuántos meses de venta hay en órdenes abiertas?")
anio = v[v["anio"] == FIN.year]
ritmo = anio.groupby("linea")["venta"].sum() / FIN.month
t = pd.DataFrame({"órdenes abiertas (M)": o.groupby("linea")["usd_abierto"].sum() / 1e6, "venta mensual del año (M)": ritmo / 1e6}).reindex(c.LINEAS)
t["meses de venta en órdenes"] = t["órdenes abiertas (M)"] / t["venta mensual del año (M)"]
t["meses que faltan del año"] = 12 - FIN.month
print(t.round(2).to_string())
print("\nÓrdenes según el año en que se levantaron (millones USD):")
print((o.pivot_table(index="linea", columns=o["fecha_orden"].dt.year, values="usd_abierto", aggfunc="sum") / 1e6)
      .reindex(c.LINEAS).round(2).fillna(0).to_string())
print("\nClientes con más órdenes por línea, y lo que compraron en el año:")
top = o.groupby(["linea", "cliente"])["usd_abierto"].sum().reset_index().sort_values("usd_abierto", ascending=False).groupby("linea").head(2)
compra = anio.groupby(["linea", "cliente"])["venta"].sum()
top["venta_del_año"] = [compra.get((l, k), 0.0) for l, k in zip(top["linea"], top["cliente"])]
c.mostrar(top.sort_values(["linea", "usd_abierto"], ascending=[True, False]))
print("\nCONCLUSIÓN 1: si una línea tiene en órdenes muchos más meses de venta que los que faltan del año, parte de")
print("esas órdenes se facturará el año siguiente. Por eso el gerente debe marcar cada orden.")

c.subtitulo("2. ¿Cada cliente tiene un solo agente?")
ult = v[v["fecha"] > FIN - pd.DateOffset(months=12)].copy()
ult["agente"] = ult["agente"].map(lambda s: re.sub(r"[\u200e\u200f]", "", str(s)).strip())
ruta = cfg["carpeta_consulta"] / "agentes_nombres.xlsx"
if ruta.exists():
    nom = pd.read_excel(ruta, dtype=str).fillna("").set_index("nombre_en_facturas")["nombre_final"]
    ult["agente"] = ult["agente"].map(nom).fillna(ult["agente"])
print(f"Facturas de 12 meses: {len(ult):,} | sin agente: {int(ult['agente'].isin(['', '0']).sum())} | agentes: {ult['agente'].nunique()}")
g = ult.groupby(["linea", "cliente_id", "agente"])["venta"].sum().reset_index()
g = g[g["venta"] > 0]
g["parte"] = g["venta"] / g.groupby(["linea", "cliente_id"])["venta"].transform("sum")
cli = g.groupby(["linea", "cliente_id"]).agg(agentes=("agente", "size"), parte_principal=("parte", "max"), venta=("venta", "sum"))
tot = cli["venta"].sum()
print(f"Clientes (por línea) con un solo agente: {int((cli['agentes'] == 1).sum())} de {len(cli)} ({100 * cli[cli['agentes'] == 1]['venta'].sum() / tot:.0f}% de la venta)")
print(f"Con varios agentes, pero el principal lleva 90% o más: {int(((cli['agentes'] > 1) & (cli['parte_principal'] >= 0.9)).sum())} "
      f"({100 * cli[(cli['agentes'] > 1) & (cli['parte_principal'] >= 0.9)]['venta'].sum() / tot:.0f}% de la venta)")
rep = cli[cli["parte_principal"] < 0.9]
print(f"Realmente repartidos (el principal lleva menos de 90%): {len(rep)} ({100 * rep['venta'].sum() / tot:.0f}% de la venta)")
print("\nCONCLUSIÓN 2: las facturas ya traen el agente, así que el reparto se puede hacer hoy. Los clientes realmente")
print("repartidos entre agentes son pocos; para esos conviene confirmar el agente vigente con el negocio.")
c.cierre("ANÁLISIS 4")
