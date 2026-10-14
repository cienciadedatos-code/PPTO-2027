"""Funciones comunes del proyecto Presupuesto 2027.

Todos los scripts de la carpeta src importan de aquí: rutas, lectura de la
copia rápida (caché), limpieza de textos y los controles que se imprimen.
"""
from pathlib import Path
import json
import re
import sys
import unicodedata

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
try:                                             # para que los acentos se impriman bien en Windows
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---------------------------------------------------------------- reglas del negocio
LINEAS = ["BU-PHARMA", "BU-ANIMAL HEALTH", "BU-DELIVERY SYSTEMS",
          "BU-CARE CHEMICALS", "BU-NUTRITION"]
AGENTES_EXCLUIDOS = ["Interempresa", "Carolina Alcaraz"]
HOJA_RENTABILIDAD = "BD RENTABILIDAD"
HOJA_ORDENES = "POs SEP-DIC 2026"
HOJA_PPTO = "BD PPTO 2026 V1.8.1"
HOJA_VIP = "VIP"
EMPRESA_ORDENES = "CEN"      # la pestaña de órdenes no trae empresa (pendiente de confirmar)

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 30)
pd.set_option("display.max_colwidth", 60)
pd.set_option("display.max_rows", 500)
pd.options.display.float_format = "{:,.2f}".format


# ---------------------------------------------------------------- configuración y rutas
def cargar_config():
    """Lee config/config.local.json y devuelve las tres rutas."""
    ruta = RAIZ / "config" / "config.local.json"
    if not ruta.exists():
        sys.exit(f"ERROR: no existe {ruta}. Copia config.example.json con ese nombre y pon tus rutas.")
    try:
        cfg = json.loads(ruta.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: config.local.json está mal escrito ({e}). Usa diagonales / en las rutas.")
    faltan = [k for k in ("raw_excel", "carpeta_consulta", "carpeta_output") if k not in cfg]
    if faltan:
        sys.exit(f"ERROR: faltan llaves en config.local.json: {faltan}")
    cfg = {k: Path(v) for k, v in cfg.items()}
    if not cfg["raw_excel"].exists():
        sys.exit(f"ERROR: no encuentro el Excel en {cfg['raw_excel']}. Revisa la ruta raw_excel.")
    for k in ("carpeta_consulta", "carpeta_output"):
        if not cfg[k].exists():
            sys.exit(f"ERROR: no existe la carpeta {cfg[k]}. Revisa la ruta {k}.")
    (cfg["carpeta_consulta"] / "cache").mkdir(exist_ok=True)
    return cfg


def ruta_cache(cfg, nombre):
    return cfg["carpeta_consulta"] / "cache" / f"{nombre}.parquet"


def guardar_cache(cfg, nombre, df):
    df.to_parquet(ruta_cache(cfg, nombre), index=False)


def leer_cache(cfg, nombre, paso_que_lo_crea):
    ruta = ruta_cache(cfg, nombre)
    if not ruta.exists():
        sys.exit(f"ERROR: falta {ruta.name}. Corre primero {paso_que_lo_crea}.")
    return pd.read_parquet(ruta)


# ---------------------------------------------------------------- impresión y controles
_conteo = {"ok": 0, "aviso": 0}


def titulo(texto):
    print("\n" + "=" * 78)
    print(texto)
    print("=" * 78)


def subtitulo(texto):
    print(f"\n--- {texto}")


def ok(texto):
    _conteo["ok"] += 1
    print(f"[OK]    {texto}")


def aviso(texto):
    _conteo["aviso"] += 1
    print(f"[AVISO] {texto}")


def control(nombre, obtenido, esperado, tolerancia=0):
    """Compara una cifra contra la esperada e imprime OK o AVISO."""
    f = (lambda x: f"{x:,.0f}") if float(esperado).is_integer() and float(obtenido).is_integer() \
        else (lambda x: f"{x:,.2f}")
    if abs(obtenido - esperado) <= tolerancia:
        ok(f"{nombre}: {f(obtenido)}")
        return True
    aviso(f"{nombre}: obtuve {f(obtenido)} y esperaba {f(esperado)} "
          f"(diferencia {f(obtenido - esperado)})")
    return False


def cierre(paso):
    print("\n" + "-" * 78)
    print(f"FIN DE {paso}: {_conteo['ok']} controles OK, {_conteo['aviso']} avisos.")
    if _conteo["aviso"]:
        print("Revisa las líneas que empiezan con [AVISO].")
    print("-" * 78)


def mostrar(df, n=None):
    """Imprime una tabla completa (o sus primeras n filas) sin índice."""
    d = df if n is None else df.head(n)
    print(d.to_string(index=False))
    if n is not None and len(df) > n:
        print(f"... ({len(df) - n} filas más; todas quedan en el archivo)")


# ---------------------------------------------------------------- textos
def norm(s):
    """Mayúsculas, sin acentos ni símbolos ® ™ ni comillas, espacios simples."""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[®™️\"“”‎]", "", s)
    return re.sub(r"\s+", " ", s.upper()).strip()


def solo_letras_numeros(s):
    return re.sub(r"[^A-Z0-9]", "", norm(s))


# Códigos de empaque de los envases: 1G, 1H2, 1A1, 5H4, 3H1, 4G, 5B, 6PB1, IP22...
_EMPAQUE = r"(?:11|13|21|31|[1-6])[A-HLMNP]{1,2}\d?[A-Z]?|IP\d+[A-Z]?"
_COLA_EMPAQUE = re.compile(r"\s+(?:" + _EMPAQUE + r")(?:\s*:?\s*\d+(?:[.,]\d+)?\s?[A-Z]{0,3})?\s*$")


def limpiar_clase(s):
    """Regla de escritura de Clase ET: texto normalizado y sin empaque al final."""
    t = norm(s)
    t = t.strip(" /-:")
    anterior = None
    while anterior != t:                      # quita "1G", "1H2", "1G:25KGM", "IP22" al final
        anterior = t
        t = _COLA_EMPAQUE.sub("", t).strip(" /-:")
    return t


_INICIO_EMPAQUE = re.compile(
    r"(?<![A-Z0-9\-])(?:(?:" + _EMPAQUE + r")(?:(?:\s*:\s*|\s+|(?=\d))(?:TI\s*:?\s*)?"
    r"(?:\.?\d+(?:[.,]\d+)?\s?[A-Z]{0,3}\.?(?![A-Z0-9])|KGM\b)|\s*$)|I[GH]\d?\s*:|(?:TI|T|C|S)\s*:\s*\.?\d)")
_CANTIDAD = re.compile(r"(?<![A-Z0-9])\.?\d+(?:[.,]\d+)?\s?(?:KGM|KGS|KGB|KG|GRM|GRS|MGM|MG|MLT|LTR|BOU|PZA)(?![A-Z])")


def nombre_desde_descripcion(desc):
    """Nombre del producto: la descripción cortada antes del empaque y la presentación.

    'TILMICOSINA FOSFATO 1G:20KGM (SLS)' -> 'TILMICOSINA FOSFATO'. Sirve para sugerir una
    clase a productos que no tienen (nuevos o que solo aparecen como Muestra)."""
    t = norm(desc)
    cortes = [m.start() for m in (_INICIO_EMPAQUE.search(t), _CANTIDAD.search(t)) if m and m.start() > 0]
    if cortes:
        t = t[:min(cortes)]
    t = re.sub(r"\s*\([A-Z0-9\-]{2,7}\)\s*$", "", t)            # siglas del fabricante: (SLS)
    if not cortes:
        t = re.sub(r"(?:\s*[-/]\s*|\s+)[A-Z]{0,6}\d{5,}\s*$", "", t)   # código de material al final
    return t.strip(" /-:")


def texto(serie):
    """Convierte una columna a texto limpio (vacíos como '')."""
    return serie.map(lambda x: "" if x is None or (isinstance(x, float) and pd.isna(x)) else str(x).strip())


def numero(serie):
    return pd.to_numeric(serie, errors="coerce").fillna(0.0)


def fecha(serie):
    """Convierte a fecha aunque venga como fecha, número de Excel o texto dd/mm/aaaa."""
    def una(x):
        if x is None or (isinstance(x, float) and pd.isna(x)) or x == "":
            return pd.NaT
        if isinstance(x, (int, float)):
            return pd.Timestamp("1899-12-30") + pd.Timedelta(days=float(x))
        if isinstance(x, str):
            return pd.to_datetime(x.strip(), dayfirst=True, errors="coerce")
        return pd.Timestamp(x)
    return pd.to_datetime(serie.map(una))


def escribir_excel(df, ruta, hoja="datos", anchos=None):
    """Guarda un Excel con encabezado fijo, filtros y columnas anchas.

    'df' puede ser una tabla o un diccionario {nombre_de_hoja: tabla} para varias hojas."""
    from openpyxl.utils import get_column_letter
    hojas = df if isinstance(df, dict) else {hoja: df}
    try:
        open(ruta, "ab").close()                 # falla si el archivo está abierto en Excel
    except PermissionError:
        sys.exit(f"ERROR: no puedo escribir {ruta.name} porque está abierto. Ciérralo en Excel y vuelve a correr.")
    with pd.ExcelWriter(ruta, engine="openpyxl") as w:
        for nombre, tabla in hojas.items():
            tabla.to_excel(w, sheet_name=nombre, index=False)
            ws = w.sheets[nombre]
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for i, col in enumerate(tabla.columns, start=1):
                ancho = (anchos or {}).get(col)
                if ancho is None:
                    largos = [len(str(x)) for x in tabla[col].head(200)]
                    ancho = min(max([len(str(col))] + largos) + 2, 60)
                ws.column_dimensions[get_column_letter(i)].width = ancho


# ---------------------------------------------------------------- patrón mensual
def patron_mensual(real, anios=(2022, 2023, 2024, 2025)):
    """Peso de cada mes dentro del año, por línea (los 12 pesos de una línea suman 1).

    Se calcula con años completos. Se usa el patrón de la línea y no el de cada clase
    porque, con estos datos, el patrón propio de una clase no se repite de un año a otro."""
    d = real[real["anio"].isin(anios)]
    m = d.groupby(["linea", "anio", "mes"])["venta"].sum().unstack("mes").fillna(0)
    m = m.div(m.sum(axis=1), axis=0)                      # parte de cada mes en su año
    pesos = m.groupby("linea").mean()
    return pesos.div(pesos.sum(axis=1), axis=0)


def mezcla_reciente(ventas, catalogo, meses=12):
    """Ventas de los últimos 'meses' con la clase y el producto del catálogo.

    El producto se identifica por la descripción del catálogo: así un producto que cambió de
    empresa o de código (por ejemplo de PRE a CEN) queda en un solo renglón."""
    v = ventas[~ventas["es_ajuste"]].copy()
    clase = catalogo.set_index("key_id")["clase_et"].map(norm)
    desc = catalogo.set_index("key_id")["descripcion"].map(norm)
    v["clase_et"] = v["key_id"].map(clase).fillna("SIN CATALOGO")
    v["producto"] = v["key_id"].map(desc).fillna(v["descripcion"].map(norm))
    fin = v["fecha"].max()
    return v, v[v["fecha"] > fin - pd.DateOffset(months=meses)], fin
