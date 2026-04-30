"""
app/blueprints/geo.py — Blueprint de datos geográficos
=======================================================
Genera los datos para Leaflet.js: puntos, polígonos y filtros.

Endpoints:
    GET /api/geo/points     → puntos (lat/lon) del CSV con filtros
    GET /api/geo/polygons   → polígonos del CSV (WKT) o GeoJSON completo
    GET /api/geo/filtros    → valores únicos de columnas categóricas
    GET /api/geo/kpis       → métricas agregadas según filtros
"""

from flask import Blueprint, request, jsonify, session, current_app
from app.utils.file_handler import (
    read_csv_safe,
    read_geojson_safe,
    detect_coord_columns,
    normalize_coords,
    FileValidationError,
)

geo_bp = Blueprint("geo", __name__)


def _get_session_info():
    """Retorna (filepath, file_type) desde sesión o lanza ValueError."""
    path = session.get("file_path")
    ftype = session.get("file_type")
    if not path or not ftype:
        raise ValueError("No hay ningún archivo cargado. Sube un archivo primero.")
    return path, ftype


def _apply_filters(df, params):
    """
    Aplica filtros categóricos recibidos como query params.
    Solo aplica columnas que realmente existen en el DataFrame.
    """
    cat_cols = df.select_dtypes(include="object").columns.tolist()
    for col in cat_cols:
        valores = params.getlist(col)
        if valores and col in df.columns:
            df = df[df[col].isin(valores)]
    return df


@geo_bp.route("/filtros", methods=["GET"])
def get_filtros():
    """Retorna valores únicos de columnas categóricas y numéricas para los filtros."""
    try:
        filepath, file_type = _get_session_info()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if file_type == "geojson":
        try:
            geojson   = read_geojson_safe(filepath)
            features  = geojson.get("features", [])
            prop_keys = set()
            prop_vals = {}

            for feat in features:
                props = (feat.get("properties") or {}) if isinstance(feat, dict) else {}
                for k, v in props.items():
                    prop_keys.add(k)
                    if isinstance(v, str):
                        prop_vals.setdefault(k, set()).add(v)

            filtros = {k: sorted(v) for k, v in prop_vals.items() if v}
            return jsonify({"filtros": filtros, "columnas_numericas": [], "file_type": "geojson"})
        except FileValidationError as e:
            return jsonify({"error": str(e)}), 422

    # CSV
    try:
        df       = read_csv_safe(filepath)
        analysis = detect_coord_columns(df)
        cat_cols = analysis["categorical_cols"]
        num_cols = analysis["numeric_cols"]

        filtros = {}
        for col in cat_cols:
            vals = df[col].dropna().unique().tolist()
            if vals:
                filtros[col] = sorted([str(v) for v in vals])

        return jsonify({
            "filtros":            filtros,
            "columnas_numericas": num_cols,
            "lat_col":            analysis["lat_col"],
            "lon_col":            analysis["lon_col"],
            "file_type":          "csv",
        })
    except FileValidationError as e:
        return jsonify({"error": str(e)}), 422


@geo_bp.route("/points", methods=["GET"])
def get_points():
    """
    Retorna puntos (lat, lon + propiedades) para pintar marcadores en el mapa.
    Soporta todos los formatos: decimal, DMS, UTM, WKT.
    """
    try:
        filepath, file_type = _get_session_info()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if file_type == "geojson":
        return jsonify({"points": [], "mensaje": "Usa /api/geo/geojson para archivos GeoJSON."})

    try:
        df       = read_csv_safe(filepath)
        analysis = detect_coord_columns(df)

        # El frontend puede sobreescribir lat/lon para formatos decimal y DMS
        lat_override = request.args.get("lat_col")
        lon_override = request.args.get("lon_col")
        if lat_override and lon_override:
            if lat_override in df.columns and lon_override in df.columns:
                analysis["lat_col"] = lat_override
                analysis["lon_col"] = lon_override
                # Forzar formato decimal si las columnas son numéricas
                if analysis["coord_format"] in (None, "decimal", "dms"):
                    num_cols = df.select_dtypes(include="number").columns.tolist()
                    if lat_override in num_cols and lon_override in num_cols:
                        analysis["coord_format"] = "decimal"
                    else:
                        analysis["coord_format"] = "dms"
                    analysis["has_coords"] = True

        if not analysis["has_coords"]:
            return jsonify({
                "points":   [],
                "warnings": analysis["warnings"],
                "mensaje":  "No se encontraron coordenadas válidas en el CSV.",
            })

        # Normalizar todas las coordenadas a decimal
        df, pct_ok = normalize_coords(df, analysis)

        if pct_ok < 100:
            analysis["warnings"].append(
                f"Solo el {pct_ok}% de las filas tenían coordenadas convertibles.")

        df = _apply_filters(df, request.args)
        df_clean = df.dropna(subset=["_lat_dec", "_lon_dec"])

        # Columnas originales sin las internas ni las de coordenadas
        coord_cols = {
            analysis.get("lat_col"), analysis.get("lon_col"),
            analysis.get("utm_e_col"), analysis.get("utm_n_col"),
            analysis.get("utm_zone_col"), analysis.get("wkt_col"),
            analysis.get("mgrs_col"),
        }
        prop_cols = [c for c in df.columns
                     if not c.startswith("_") and c not in coord_cols]

        points = []
        for _, row in df_clean.iterrows():
            points.append({
                "lat":   float(row["_lat_dec"]),
                "lon":   float(row["_lon_dec"]),
                "props": {col: str(row[col]) for col in prop_cols if col in row},
            })

        return jsonify({
            "points":        points,
            "total":         len(points),
            "coord_format":  analysis["coord_format"],
            "warnings":      analysis["warnings"],
        })

    except FileValidationError as e:
        return jsonify({"error": str(e)}), 422
    except Exception as e:
        current_app.logger.error(f"Error en /points: {e}")
        return jsonify({"error": "Error al generar los puntos."}), 500


@geo_bp.route("/geojson", methods=["GET"])
def get_geojson():
    """
    Retorna el GeoJSON (filtrado por propiedades si aplica).
    Para archivos GeoJSON subidos directamente.
    """
    try:
        filepath, file_type = _get_session_info()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if file_type == "csv":
        return jsonify({"error": "Usa /api/geo/points para archivos CSV."})

    try:
        geojson  = read_geojson_safe(filepath)
        features = geojson.get("features", [])

        # Filtrar por propiedades si se pasan query params
        filters = {k: v for k, v in request.args.items() if k != "color_por"}
        if filters:
            filtered = []
            for feat in features:
                props = (feat.get("properties") or {}) if isinstance(feat, dict) else {}
                if all(str(props.get(k, "")) == v for k, v in filters.items()):
                    filtered.append(feat)
            geojson["features"] = filtered

        return jsonify(geojson)

    except FileValidationError as e:
        return jsonify({"error": str(e)}), 422


@geo_bp.route("/kpis", methods=["GET"])
def get_kpis():
    """
    Retorna KPIs agregados de columnas numéricas según filtros activos.
    Solo aplica a CSV.
    """
    try:
        filepath, file_type = _get_session_info()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if file_type == "geojson":
        return jsonify({"kpis": {}, "registros": 0})

    try:
        df       = read_csv_safe(filepath)
        analysis = detect_coord_columns(df)
        df       = _apply_filters(df, request.args)
        num_cols = analysis["numeric_cols"]

        # Excluir lat/lon de los KPIs
        for c in [analysis["lat_col"], analysis["lon_col"]]:
            if c and c in num_cols:
                num_cols.remove(c)

        kpis = {}
        for col in num_cols[:5]:  # máx 5 KPIs
            kpis[col] = {
                "suma":     round(float(df[col].sum()), 2),
                "promedio": round(float(df[col].mean()), 2),
                "maximo":   round(float(df[col].max()), 2),
            }

        return jsonify({"kpis": kpis, "registros": len(df)})

    except (FileValidationError, Exception) as e:
        return jsonify({"error": str(e)}), 500


# Importación tardía para evitar circular imports
import pandas as pd
