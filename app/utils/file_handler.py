"""
app/utils/file_handler.py — Manejo seguro de archivos CSV y GeoJSON
====================================================================
Formatos de coordenadas soportados en CSV:
  1. Decimal   → columnas numéricas lat/lon directas
  2. DMS       → "4°42'39\"N" / "74°4'19\"W"
  3. UTM       → columnas utm_easting, utm_northing, zona_utm
  4. WKT Point → "POINT(-74.07 4.71)"
  5. MGRS      → "18NXL0292120787"

Para agregar un nuevo formato:
  1. Agrega un conversor en la sección CONVERSORES
  2. Agrega su heurística en detect_coord_columns()
  3. Agrega su rama en normalize_coords()
"""

import os, re, json, uuid, math
import pandas as pd
import mgrs as mgrs_lib
from flask import current_app
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage


class FileValidationError(Exception):
    pass


# ══════════════════════════════════════════════════════════════
# PATRONES DE DETECCIÓN
# ══════════════════════════════════════════════════════════════
LAT_P    = re.compile(r"^(lat(itud)?e?|y_?coord(enada)?|coord_?y)$", re.I)
LON_P    = re.compile(r"^(lon(gitud)?e?|lng|x_?coord(enada)?|coord_?x)$", re.I)
DMS_LAT  = re.compile(r"^(lat|latitud)_?dms$", re.I)
DMS_LON  = re.compile(r"^(lon|lng|longitud)_?dms$", re.I)
UTM_E    = re.compile(r"^(utm_?)?east(ing)?$|^este$", re.I)
UTM_N    = re.compile(r"^(utm_?)?north(ing)?$|^norte$", re.I)
# Más estricto: requiere 'utm' en algún lugar para no confundir con columnas
# de negocio como 'zona' (Norte/Sur). Acepta: utm_zone, zona_utm, zone_utm, zona_number, zona_letra
UTM_ZONE = re.compile(r"^(utm_zone|zone_utm|zona_utm|utm_zona|zona_number|zona_letra|zona_zone)$", re.I)
WKT_COL  = re.compile(r"^(wkt|geometry|geom|point|shape)$", re.I)
MGRS_COL = re.compile(r"^(mgrs|grid_?ref(erence)?|militar)$", re.I)

DMS_RE  = re.compile(
    r'(\d{1,3})\s*[°d]\s*(\d{1,2})\s*[\'\u2019m]\s*'
    r'(\d{1,2}(?:\.\d+)?)\s*["\u201d\u2033s]?\s*([NSEW])', re.I)
WKT_RE  = re.compile(
    r'POINT\s*\(\s*(-?\d+\.?\d*)\s+(-?\d+\.?\d*)\s*\)', re.I)
MGRS_RE = re.compile(
    r'^\d{1,2}[C-HJ-NP-X][A-HJ-NP-Z]{2}\d{2,10}$', re.I)


# ══════════════════════════════════════════════════════════════
# CONVERSORES
# ══════════════════════════════════════════════════════════════

def dms_to_decimal(value) -> float | None:
    """Convierte DMS ("4°42'39\"N") a grados decimales."""
    m = DMS_RE.search(str(value))
    if not m:
        return None
    deg, mins, secs, hemi = int(m.group(1)), int(m.group(2)), float(m.group(3)), m.group(4).upper()
    result = deg + mins/60 + secs/3600
    return -result if hemi in ('S', 'W') else result


def utm_to_latlon(easting: float, northing: float,
                  zone_number: int, zone_letter: str) -> tuple:
    """Convierte UTM a (lat, lon) decimal WGS84 — implementación pura sin librerías."""
    a=6378137.0; e2=0.00669437999014; ep2=e2/(1-e2); k0=0.9996
    x=easting-500000.0
    y=northing if zone_letter.upper() >= 'N' else northing-10_000_000.0
    lon0=math.radians((zone_number-1)*6-180+3)
    M=y/k0; mu=M/(a*(1-e2/4-3*e2**2/64-5*e2**3/256))
    e1=(1-math.sqrt(1-e2))/(1+math.sqrt(1-e2))
    phi1=(mu+(3*e1/2-27*e1**3/32)*math.sin(2*mu)
          +(21*e1**2/16-55*e1**4/32)*math.sin(4*mu)
          +(151*e1**3/96)*math.sin(6*mu)+(1097*e1**4/512)*math.sin(8*mu))
    N1=a/math.sqrt(1-e2*math.sin(phi1)**2)
    T1=math.tan(phi1)**2; C1=ep2*math.cos(phi1)**2
    R1=a*(1-e2)/(1-e2*math.sin(phi1)**2)**1.5; D=x/(N1*k0)
    lat=phi1-(N1*math.tan(phi1)/R1)*(D**2/2
        -(5+3*T1+10*C1-4*C1**2-9*ep2)*D**4/24
        +(61+90*T1+298*C1+45*T1**2-252*ep2-3*C1**2)*D**6/720)
    lon=lon0+(D-(1+2*T1+C1)*D**3/6
        +(5-2*C1+28*T1-3*C1**2+8*ep2+24*T1**2)*D**5/120)/math.cos(phi1)
    return round(math.degrees(lat), 6), round(math.degrees(lon), 6)


def parse_utm_zone(zone_str: str) -> tuple:
    """Parsea '18N' o '18 N' → (18, 'N'). Retorna (None, None) si falla."""
    m = re.match(r'(\d{1,2})\s*([C-X])', str(zone_str).strip(), re.I)
    return (int(m.group(1)), m.group(2).upper()) if m else (None, None)


def wkt_point_to_latlon(value) -> tuple:
    """Extrae (lat, lon) de WKT Point — WKT usa orden (lon lat)."""
    m = WKT_RE.search(str(value))
    if not m:
        return None, None
    lon, lat = float(m.group(1)), float(m.group(2))
    return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else (None, None)


_mgrs_converter = mgrs_lib.MGRS()

def mgrs_to_latlon(value) -> tuple:
    """
    Convierte una cadena MGRS a (lat, lon) decimal usando la librería mgrs.
    Acepta formatos con o sin espacios: "18NXL0292120787" o "18N XL 02921 20787".
    """
    try:
        clean = re.sub(r'\s+', '', str(value)).upper()
        if not MGRS_RE.match(clean):
            return None, None
        lat, lon = _mgrs_converter.toLatLon(clean)
        return round(float(lat), 6), round(float(lon), 6)
    except Exception:
        return None, None


# ══════════════════════════════════════════════════════════════
# GUARDADO SEGURO
# ══════════════════════════════════════════════════════════════

def allowed_file(filename: str) -> bool:
    allowed = current_app.config.get("ALLOWED_EXTENSIONS", {"csv","geojson","json"})
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed

def get_file_type(filename: str) -> str:
    return "csv" if filename.rsplit(".", 1)[1].lower() == "csv" else "geojson"

def save_uploaded_file(file: FileStorage) -> tuple:
    if not file or file.filename == "":
        raise FileValidationError("No se recibió ningún archivo.")
    if not allowed_file(file.filename):
        raise FileValidationError("Solo se aceptan archivos .csv, .geojson, .json")
    safe     = secure_filename(file.filename)
    unique   = f"{uuid.uuid4().hex}_{safe}"
    filepath = os.path.join(current_app.config["UPLOAD_FOLDER"], unique)
    file.save(filepath)
    return filepath, get_file_type(file.filename)


# ══════════════════════════════════════════════════════════════
# LECTURA SEGURA CSV
# ══════════════════════════════════════════════════════════════

def read_csv_safe(filepath: str, max_rows: int = 50_000) -> pd.DataFrame:
    if not os.path.exists(filepath):
        raise FileValidationError("Archivo no encontrado.")
    df = None
    for enc in ("utf-8", "latin-1", "utf-8-sig"):
        try:
            df = pd.read_csv(filepath, nrows=max_rows, encoding=enc); break
        except UnicodeDecodeError:
            continue
        except Exception as e:
            raise FileValidationError(f"Error al leer el CSV: {e}")
    if df is None:
        raise FileValidationError("No se pudo decodificar el CSV.")
    if df.empty:
        raise FileValidationError("El CSV está vacío.")
    if len(df.columns) < 2:
        raise FileValidationError("El CSV debe tener al menos 2 columnas.")
    df.columns = (df.columns.str.strip().str.lower()
                  .str.replace(" ", "_").str.replace(r"[^\w]", "", regex=True))
    return df


# ══════════════════════════════════════════════════════════════
# DETECCIÓN DE FORMATO DE COORDENADAS
# ══════════════════════════════════════════════════════════════

def detect_coord_columns(df: pd.DataFrame) -> dict:
    """
    Detecta automáticamente el formato de coordenadas.
    Prioridad: decimal → DMS → UTM → WKT → MGRS → ninguno.
    Retorna un dict con toda la información necesaria para normalize_coords().
    """
    result = {
        "coord_format":     None,
        "has_coords":       False,
        "lat_col":          None,
        "lon_col":          None,
        "utm_e_col":        None,
        "utm_n_col":        None,
        "utm_zone_col":     None,
        "wkt_col":          None,
        "mgrs_col":         None,
        "numeric_cols":     df.select_dtypes(include="number").columns.tolist(),
        "categorical_cols": df.select_dtypes(include="object").columns.tolist(),
        "all_cols":         df.columns.tolist(),
        "warnings":         [],
    }
    cols = df.columns.tolist()

    # ── 1. Decimal ─────────────────────────────────────────
    lat_c = next((c for c in cols if LAT_P.match(c)), None)
    lon_c = next((c for c in cols if LON_P.match(c)), None)
    if lat_c and lon_c:
        lv  = pd.to_numeric(df[lat_c], errors="coerce").dropna()
        lnv = pd.to_numeric(df[lon_c], errors="coerce").dropna()
        if len(lv) and lv.between(-90, 90).all() and lnv.between(-180, 180).all():
            result.update({"coord_format":"decimal","has_coords":True,
                           "lat_col":lat_c,"lon_col":lon_c})
            return result
        result["warnings"].append(
            f"Columnas '{lat_c}'/'{lon_c}' fuera de rango válido.")

    # ── 2. DMS ──────────────────────────────────────────────
    dms_lat = next((c for c in cols if DMS_LAT.match(c)), None)
    dms_lon = next((c for c in cols if DMS_LON.match(c)), None)
    if not (dms_lat and dms_lon):
        lat_cands, lon_cands = [], []
        for col in result["categorical_cols"]:
            sample = df[col].dropna().head(5).astype(str)
            matches = [DMS_RE.search(v) for v in sample]
            if all(matches):
                hems = {m.group(4).upper() for m in matches if m}
                if hems <= {'N','S'}:
                    lat_cands.append(col)
                elif hems <= {'E','W'}:
                    lon_cands.append(col)
        if lat_cands and lon_cands:
            dms_lat = dms_lat or lat_cands[0]
            dms_lon = dms_lon or lon_cands[0]
    if dms_lat and dms_lon:
        result.update({"coord_format":"dms","has_coords":True,
                       "lat_col":dms_lat,"lon_col":dms_lon})
        return result

    # ── 3. UTM ──────────────────────────────────────────────
    utm_e  = next((c for c in cols if UTM_E.match(c)), None)
    utm_n  = next((c for c in cols if UTM_N.match(c)), None)
    utm_z  = next((c for c in cols if UTM_ZONE.match(c)), None)
    if utm_e and utm_n:
        ev = pd.to_numeric(df[utm_e], errors="coerce").dropna()
        nv = pd.to_numeric(df[utm_n], errors="coerce").dropna()
        if len(ev) and ev.between(100_000, 900_000).all() and nv.between(0, 10_000_000).all():
            result.update({"coord_format":"utm","has_coords":True,
                           "utm_e_col":utm_e,"utm_n_col":utm_n,"utm_zone_col":utm_z})
            if not utm_z:
                result["warnings"].append(
                    "Sin columna de zona UTM — se usará 18N (Colombia) por defecto.")
            return result

    # ── 4. WKT Point ────────────────────────────────────────
    wkt_c = next((c for c in cols if WKT_COL.match(c)), None)
    if not wkt_c:
        for col in result["categorical_cols"]:
            sample = df[col].dropna().head(5).astype(str)
            if sample.apply(lambda v: bool(WKT_RE.search(v))).all():
                wkt_c = col; break
    if wkt_c:
        result.update({"coord_format":"wkt","has_coords":True,"wkt_col":wkt_c})
        return result

    # ── 5. MGRS ─────────────────────────────────────────────
    mgrs_c = next((c for c in cols if MGRS_COL.match(c)), None)
    if not mgrs_c:
        for col in result["categorical_cols"]:
            sample = df[col].dropna().head(5).astype(str)
            cleaned = sample.apply(lambda v: re.sub(r'\s+','',v).upper())
            if cleaned.apply(lambda v: bool(MGRS_RE.match(v))).all():
                mgrs_c = col; break
    if mgrs_c:
        result.update({"coord_format":"mgrs","has_coords":True,"mgrs_col":mgrs_c})
        return result

    # ── Sin coordenadas ──────────────────────────────────────
    result["warnings"].append(
        "No se detectaron coordenadas en formato decimal, DMS, UTM, WKT ni MGRS. "
        "Puedes seleccionar las columnas manualmente.")
    return result


# ══════════════════════════════════════════════════════════════
# NORMALIZACIÓN A DECIMAL
# ══════════════════════════════════════════════════════════════

def normalize_coords(df: pd.DataFrame, coord_info: dict) -> tuple:
    """
    Convierte todas las coordenadas a decimal, añadiendo '_lat_dec' y '_lon_dec'.
    Retorna (df_con_columnas_nuevas, porcentaje_convertido).
    """
    fmt = coord_info.get("coord_format")
    df  = df.copy()

    if fmt == "decimal":
        df["_lat_dec"] = pd.to_numeric(df[coord_info["lat_col"]], errors="coerce")
        df["_lon_dec"] = pd.to_numeric(df[coord_info["lon_col"]], errors="coerce")

    elif fmt == "dms":
        df["_lat_dec"] = df[coord_info["lat_col"]].apply(dms_to_decimal)
        df["_lon_dec"] = df[coord_info["lon_col"]].apply(dms_to_decimal)

    elif fmt == "utm":
        ec, nc, zc = coord_info["utm_e_col"], coord_info["utm_n_col"], coord_info.get("utm_zone_col")
        def _utm(row):
            try:
                e, n = float(row[ec]), float(row[nc])
                zn, zl = parse_utm_zone(str(row[zc])) if zc and pd.notna(row[zc]) else (18,'N')
                if zn is None: return pd.Series([None,None])
                return pd.Series(list(utm_to_latlon(e, n, zn, zl)))
            except Exception:
                return pd.Series([None,None])
        df[["_lat_dec","_lon_dec"]] = df.apply(_utm, axis=1)

    elif fmt == "wkt":
        def _wkt(v): return pd.Series(list(wkt_point_to_latlon(v)))
        df[["_lat_dec","_lon_dec"]] = df[coord_info["wkt_col"]].apply(_wkt)

    elif fmt == "mgrs":
        def _mgrs(v): return pd.Series(list(mgrs_to_latlon(v)))
        df[["_lat_dec","_lon_dec"]] = df[coord_info["mgrs_col"]].apply(_mgrs)

    else:
        raise FileValidationError("Formato de coordenadas no reconocido.")

    valid = df.dropna(subset=["_lat_dec","_lon_dec"])
    if valid.empty:
        raise FileValidationError(
            "No se pudo convertir ninguna coordenada. Verifica el formato del archivo.")
    return df, round(len(valid)/len(df)*100, 1)


# ══════════════════════════════════════════════════════════════
# GEOJSON
# ══════════════════════════════════════════════════════════════

def read_geojson_safe(filepath: str) -> dict:
    if not os.path.exists(filepath):
        raise FileValidationError("Archivo no encontrado.")
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise FileValidationError(f"JSON inválido: {e}")

    geo_type = data.get("type")
    VALID = {"FeatureCollection","Feature","GeometryCollection",
             "Point","MultiPoint","LineString","MultiLineString","Polygon","MultiPolygon"}
    if geo_type not in VALID:
        raise FileValidationError(f"Estructura GeoJSON inválida. Tipo recibido: '{geo_type}'")

    if geo_type != "FeatureCollection":
        data = ({"type":"FeatureCollection","features":[data]}
                if geo_type == "Feature"
                else {"type":"FeatureCollection",
                      "features":[{"type":"Feature","geometry":data,"properties":{}}]})

    features = data.get("features", [])
    if not features:
        raise FileValidationError("El GeoJSON no contiene features.")
    if not any(isinstance(f,dict) and f.get("geometry",{}).get("coordinates")
               for f in features):
        raise FileValidationError(
            "El GeoJSON no contiene coordenadas en ninguna de sus features.")
    return data


def analyze_geojson(geojson: dict) -> dict:
    features = geojson.get("features", [])
    geo_types, prop_keys = set(), set()
    for f in features:
        if not isinstance(f, dict): continue
        geom = f.get("geometry") or {}
        if geom.get("type"): geo_types.add(geom["type"])
        prop_keys.update((f.get("properties") or {}).keys())
    return {"total_features":len(features),
            "geometry_types":sorted(geo_types),
            "properties":sorted(prop_keys)}


# ══════════════════════════════════════════════════════════════
# LIMPIEZA
# ══════════════════════════════════════════════════════════════

def cleanup_old_uploads(upload_folder: str, max_files: int = 50) -> None:
    try:
        files = sorted(
            [os.path.join(upload_folder, f) for f in os.listdir(upload_folder)
             if os.path.isfile(os.path.join(upload_folder, f))],
            key=os.path.getctime)
        while len(files) > max_files:
            os.remove(files.pop(0))
    except Exception:
        pass
