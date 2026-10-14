"""Análisis 1. ¿Cómo definir Clase ET? Truncar la descripción contra usar la llave empresa + código.

Respalda las decisiones del paso 2 (catálogo). Solo lee e imprime; no guarda nada.
Correr: py analisis/a1_clase_et.py   (necesita haber corrido los pasos 0 y 1)
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import comun as c  # noqa: E402

cfg = c.cargar_config()
c.titulo("ANÁLISIS 1. CÓMO DEFINIR CLASE ET")
v = c.leer_cache(cfg, "ventas", "01_ventas.py")
v = v[~v["es_ajuste"] & (v["descripcion"].str.strip() != "")].copy()
v["clase_n"] = v["clase_original"].map(c.norm)
v["desc_n"] = v["descripcion"].map(c.norm)

# ------------------------------------------------------------------ 1. La regla de truncar la descripción
c.subtitulo("1. Si la clase fuera 'la descripción cortada antes del empaque', ¿coincide con la clase del Excel?")
pares = v.groupby(["linea", "clase_n", "desc_n"], as_index=False).agg(filas=("venta", "size"), venta=("venta", "sum"))
pares["nombre"] = pares["desc_n"].map(c.nombre_desde_descripcion)


def inicio(a, b):
    return bool(a) and b.startswith(a) and (len(b) == len(a) or not b[len(a)].isalnum())


def grupo(f):
    cl, n, d = f["clase_n"], f["nombre"], f["desc_n"]
    if cl == "MUESTRA":
        return "4 Clase Muestra"
    if cl == n:
        return "1 Igual al nombre truncado"
    if inicio(cl, n):
        return "2 Agrupador: la clase es más corta que el nombre"
    if inicio(cl, d) or inicio(n, cl):
        return "3 La clase trae de más (empaque o texto extra)"
    return "3 No coincide (sinónimo, otro orden o error)"


pares["grupo"] = pares.apply(grupo, axis=1)
t = pares.groupby("grupo").agg(pares=("filas", "size"), venta=("venta", "sum"))
t["% pares"] = (100 * t["pares"] / t["pares"].sum()).round(1)
t["% venta"] = (100 * t["venta"] / t["venta"].sum()).round(1)
print(t.to_string())
print("\nPor línea (número de pares clase + descripción):")
print(pd.crosstab(pares["linea"], pares["grupo"].str[:1]).reindex(c.LINEAS).rename(
    columns={"1": "igual", "2": "agrupador", "3": "no coincide", "4": "muestra"}).to_string())
print("\nCONCLUSIÓN 1: truncar la descripción solo reproduce la clase en una parte de los casos. En Care Chemicals y")
print("Delivery Systems la clase es una familia o categoría que no sale de cortar el texto.")

# ------------------------------------------------------------------ 2. El código solo no identifica al producto
c.subtitulo("2. ¿El código de artículo identifica al producto?")
emp = v.groupby("codigo")["empresa"].nunique()
rep = emp[emp > 1].index
print(f"Códigos usados en más de una empresa: {len(rep)} de {len(emp)}")
ej = v[v["codigo"].isin(rep)].groupby(["codigo", "empresa"]).agg(descripcion=("descripcion", "first"), clase=("clase_n", lambda s: s.value_counts().index[0]),
                                                                 filas=("venta", "size")).reset_index()
distinto = ej.groupby("codigo")["clase"].nunique()
print(f"De esos, con clase distinta según la empresa (es decir, son otro producto): {int((distinto > 1).sum())}")
c.mostrar(ej[ej["codigo"].isin(distinto[distinto > 1].index)].sort_values(["codigo", "empresa"]), 8)
print("\nCONCLUSIÓN 2: el mismo código puede ser otro producto en otra empresa. La llave debe ser empresa + código.")

# ------------------------------------------------------------------ 3. Con la llave empresa + código
c.subtitulo("3. Con la llave empresa + código, ¿cada producto tiene una sola clase?")
real = v[v["clase_n"] != "MUESTRA"]
n = real.groupby("key_id")["clase_n"].nunique()
print(f"Productos (key_id): {len(n):,} | con una sola clase: {int((n == 1).sum()):,} ({100 * (n == 1).mean():.1f}%) | con dos o más: {int((n > 1).sum())}")
habitual = real.groupby("key_id")["clase_n"].agg(lambda s: s.value_counts().index[0])
fuera = real[real["clase_n"] != real["key_id"].map(habitual)]
print(f"Facturas con una clase distinta a la habitual de su producto: {len(fuera):,} de {len(real):,} ({fuera['venta'].sum():,.0f} USD)")
print("\nMeses con más facturas fuera de su clase habitual:")
c.mostrar(fuera.groupby(fuera["fecha"].dt.strftime("%Y-%m")).agg(facturas=("venta", "size"), venta=("venta", "sum"))
          .sort_values("facturas", ascending=False).head(6).reset_index().rename(columns={"fecha": "mes"}))
print("\nCONCLUSIÓN 3: con la llave correcta casi todos los productos tienen una sola clase. Los errores se concentran")
print("en pocos productos y en meses específicos, y se corrigen con la regla de la mayoría del paso 2.")
c.cierre("ANÁLISIS 1")
