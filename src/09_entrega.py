"""Paso 9. Entrega: presupuesto 2027 en Excel y tablas para Power BI.

Entrada : las copias rápidas de los pasos anteriores y consulta/catalogo.xlsx
Salida  : output/presupuesto_2027.xlsx       (resumen, por mes, por clase y detalle)
          output/powerbi/hechos.xlsx          (todas las versiones en una sola tabla)
          output/powerbi/dim_catalogo.xlsx, dim_clientes.xlsx, dim_calendario.xlsx
Correr  : py src/09_entrega.py
"""
import pandas as pd

import comun as c

cfg = c.cargar_config()
PBI = cfg["carpeta_output"] / "powerbi"
PBI.mkdir(exist_ok=True)
c.titulo("PASO 9. ENTREGA: presupuesto 2027 y tablas para Power BI")
base = c.leer_cache(cfg, "base", "04_base.py")
cierre = c.leer_cache(cfg, "cierre_2026", "05_cierre_2026.py")
mens = c.leer_cache(cfg, "proyeccion_base_mensual", "06_proyeccion_2027.py")
clases = c.leer_cache(cfg, "proyeccion_base", "06_proyeccion_2027.py")
filas = c.leer_cache(cfg, "filas_gerentes", "07_gerentes.py")
ppto = c.leer_cache(cfg, "presupuesto_2027", "08_agentes.py")
det = c.leer_cache(cfg, "presupuesto_2027_anual", "08_agentes.py")
cat = pd.read_excel(cfg["carpeta_consulta"] / "catalogo.xlsx", dtype=str).fillna("")

# ------------------------------------------------------------------ 1. Tabla de hechos: todas las versiones
COLS = ["version", "anio", "mes", "linea", "agente", "cliente_id", "cliente", "key_id", "clase_et",
        "producto", "unidad", "cantidad", "venta"]


def version(df, nombre):
    df = df.copy()
    df["version"] = nombre
    for col in COLS:
        if col not in df.columns:
            df[col] = 0.0 if col in ("cantidad", "venta") else ""
    return df[COLS]


b = base.rename(columns={"descripcion": "producto"})
partes = [version(b[b["version"] == x], x) for x in ("REAL", "ORDENES", "PPTO_2026")]
partes.append(version(cierre[cierre["tipo"] == "ESTIMADO"], "CIERRE_2026_ESTIMADO"))
partes.append(version(mens.rename(columns={"venta_base": "venta"}), "BASE_2027"))
partes.append(version(ppto.drop(columns="venta").rename(columns={"venta_gerentes": "venta", "key_ref": "key_id"}), "GERENTES_2027"))
partes.append(version(ppto.rename(columns={"key_ref": "key_id"}), "FINAL_2027"))
hechos = pd.concat(partes, ignore_index=True)
hechos["cantidad"] = hechos["cantidad"].fillna(0)
hechos = hechos[(hechos["venta"].abs() > 0.005) | (hechos["cantidad"].abs() > 0)]
hechos["fecha"] = pd.to_datetime(dict(year=hechos["anio"], month=hechos["mes"], day=1)).dt.strftime("%Y-%m-%d")

dim_cat = cat[["key_id", "empresa", "codigo", "linea", "descripcion", "fabricante", "unidad", "clase_et"]]
dim_cli = base[base["cliente_id"] != ""].groupby("cliente_id", as_index=False).agg(cliente=("cliente", "last"))
fechas = pd.date_range("2022-01-01", "2027-12-01", freq="MS")
NOMBRES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
dim_cal = pd.DataFrame({"fecha": fechas.strftime("%Y-%m-%d"), "anio": fechas.year, "mes": fechas.month,
                        "mes_nombre": [NOMBRES[m - 1] for m in fechas.month], "trimestre": "T" + fechas.quarter.astype(str)})

# ------------------------------------------------------------------ 2. Excel del presupuesto 2027
real = base[base["version"] == "REAL"]
res = pd.DataFrame({
    "real_2024": real[real["anio"] == 2024].groupby("linea")["venta"].sum(),
    "real_2025": real[real["anio"] == 2025].groupby("linea")["venta"].sum(),
    "ppto_2026": base[base["version"] == "PPTO_2026"].groupby("linea")["venta"].sum(),
    "cierre_2026_estimado": cierre.groupby("linea")["venta"].sum(),
    "base_2027": clases.groupby("linea")["base_2027"].sum(),
    "gerentes_2027": filas.groupby("linea")["venta_final"].sum(),
    "final_2027": ppto.groupby("linea")["venta"].sum(),
}).reindex(c.LINEAS)
res.loc["TOTAL"] = res.sum()
res["final 2027 vs cierre 2026 %"] = (100 * (res["final_2027"] / res["cierre_2026_estimado"] - 1)).round(1)
por_mes = ppto.pivot_table(index="linea", columns="mes", values="venta", aggfunc="sum").reindex(c.LINEAS)
por_mes["total"] = por_mes.sum(axis=1)
por_clase = det.groupby(["linea", "clase_et"], as_index=False).agg(final_2027=("venta_final_agente", "sum")).merge(
    clases[["linea", "clase_et", "grupo", "venta_2025", "ultimos_12m", "cierre_2026", "base_2027"]], on=["linea", "clase_et"], how="left") \
    .sort_values(["linea", "final_2027"], ascending=[True, False])
detalle = det[["linea", "agente", "cliente", "clase_et", "producto", "unidad", "cantidad", "precio_final", "venta_final_agente",
               "confianza", "motivo", "comentario"]].rename(columns={"precio_final": "precio", "venta_final_agente": "venta",
                                                                     "motivo": "motivo_gerente", "comentario": "comentario_agente"}) \
    .sort_values(["linea", "venta"], ascending=[True, False])

print("Escribiendo los Excel (la tabla de hechos tarda uno o dos minutos)...")
c.escribir_excel({"resumen": res.reset_index().rename(columns={"index": "linea"}), "por_mes": por_mes.reset_index(),
                  "por_clase": por_clase, "detalle": detalle}, cfg["carpeta_output"] / "presupuesto_2027.xlsx",
                 anchos={"cliente": 36, "producto": 52, "clase_et": 30})
c.escribir_excel(hechos, PBI / "hechos.xlsx", hoja="hechos")
c.escribir_excel(dim_cat, PBI / "dim_catalogo.xlsx", hoja="catalogo")
c.escribir_excel(dim_cli, PBI / "dim_clientes.xlsx", hoja="clientes")
c.escribir_excel(dim_cal, PBI / "dim_calendario.xlsx", hoja="calendario")

# ------------------------------------------------------------------ 3. Lo que se imprime
c.subtitulo("Resumen por línea (millones USD)")
vista = (res.drop(columns="final 2027 vs cierre 2026 %") / 1e6).round(2)
vista["final 2027 vs cierre 2026 %"] = res["final 2027 vs cierre 2026 %"]
print(vista.T.to_string())
c.subtitulo("Presupuesto 2027 por línea y mes (millones USD)")
print((por_mes / 1e6).round(2).to_string())
c.subtitulo("Tabla de hechos para Power BI")
c.mostrar(hechos.groupby(["version", "anio"]).agg(filas=("venta", "size"), venta=("venta", "sum")).reset_index())

c.subtitulo("Controles")
t = hechos.groupby("version")["venta"].sum()
c.control("REAL en hechos = REAL en la base", t["REAL"], real["venta"].sum(), 1)
c.control("GERENTES_2027 en hechos = lo revisado en el paso 7", t["GERENTES_2027"], filas["venta_final"].sum(), 1)
c.control("FINAL_2027 en hechos = presupuesto del paso 8", t["FINAL_2027"], ppto["venta"].sum(), 1)
c.control("Detalle del Excel = presupuesto final", detalle["venta"].sum(), ppto["venta"].sum(), 1)
print(f"\nGuardado: {cfg['carpeta_output'] / 'presupuesto_2027.xlsx'}\nGuardado: {PBI}")
c.cierre("PASO 9")
