"""
app/blueprints/upload.py — Blueprint de carga de archivos
==========================================================
Maneja CSV y GeoJSON. Detecta coordenadas y valida geometrías
antes de pasar al mapa.

Endpoints:
    POST /api/upload/file        → sube CSV o GeoJSON
    GET  /api/upload/sample/csv  → descarga CSV de ejemplo
    GET  /api/upload/sample/geo  → descarga GeoJSON de ejemplo
"""

import os
from flask import Blueprint, request, jsonify, session, current_app, send_file
from app.utils.file_handler import (
    save_uploaded_file,
    read_csv_safe,
    read_geojson_safe,
    detect_coord_columns,
    analyze_geojson,
    cleanup_old_uploads,
    FileValidationError,
)

upload_bp = Blueprint("upload", __name__)


@upload_bp.route("/file", methods=["POST"])
def upload_file():
    """
    Recibe un CSV o GeoJSON.
    - CSV:     detecta columnas de coordenadas y retorna análisis
    - GeoJSON: valida estructura y retorna metadata de propiedades
    """
    if "file" not in request.files:
        return jsonify({"error": "No se encontró el campo 'file'."}), 400

    file = request.files["file"]

    try:
        filepath, file_type = save_uploaded_file(file)
        cleanup_old_uploads(current_app.config["UPLOAD_FOLDER"], max_files=50)

        # Guardar en sesión (nunca exponer ruta al cliente)
        session["file_path"] = filepath
        session["file_type"] = file_type
        session["file_name"] = file.filename

        # ── Procesar según tipo ──────────────────────────
        if file_type == "csv":
            df       = read_csv_safe(filepath)
            analysis = detect_coord_columns(df)

            return jsonify({
                "ok":        True,
                "file_type": "csv",
                "filename":  file.filename,
                "filas":     len(df),
                "columnas":  len(df.columns),
                "coord_info":    analysis,                "preview":   df.head(5).to_dict(orient="records"),
            })

        else:  # geojson
            geojson  = read_geojson_safe(filepath)
            analysis = analyze_geojson(geojson)

            return jsonify({
                "ok":        True,
                "file_type": "geojson",
                "filename":  file.filename,
                "coord_info": {
                    "has_point_coords": True,
                    "has_polygon_col":  True,
                    "warnings":         [],
                },
                **analysis,
            })

    except FileValidationError as e:
        return jsonify({"error": str(e)}), 422
    except Exception as e:
        current_app.logger.error(f"Error en upload: {e}")
        return jsonify({"error": "Error interno al procesar el archivo."}), 500


@upload_bp.route("/sample/csv", methods=["GET"])
def sample_csv():
    path = os.path.abspath(
        os.path.join(current_app.root_path, "..", "data", "samples", "rutas_ejemplo.csv")
    )
    if not os.path.exists(path):
        return jsonify({"error": "Archivo de ejemplo no encontrado."}), 404
    return send_file(path, as_attachment=True, download_name="rutas_ejemplo.csv")


@upload_bp.route("/sample/geo", methods=["GET"])
def sample_geo():
    path = os.path.abspath(
        os.path.join(current_app.root_path, "..", "data", "samples", "zonas_ejemplo.geojson")
    )
    if not os.path.exists(path):
        return jsonify({"error": "Archivo de ejemplo no encontrado."}), 404
    return send_file(path, as_attachment=True, download_name="zonas_ejemplo.geojson")


@upload_bp.route("/sample/dms", methods=["GET"])
def sample_dms():
    path = os.path.abspath(
        os.path.join(current_app.root_path, "..", "data", "samples", "rutas_dms.csv")
    )
    if not os.path.exists(path):
        return jsonify({"error": "Archivo de ejemplo no encontrado."}), 404
    return send_file(path, as_attachment=True, download_name="rutas_dms.csv")


@upload_bp.route("/sample/utm", methods=["GET"])
def sample_utm():
    path = os.path.abspath(
        os.path.join(current_app.root_path, "..", "data", "samples", "rutas_utm.csv")
    )
    if not os.path.exists(path):
        return jsonify({"error": "Archivo de ejemplo no encontrado."}), 404
    return send_file(path, as_attachment=True, download_name="rutas_utm.csv")


@upload_bp.route("/sample/wkt", methods=["GET"])
def sample_wkt():
    path = os.path.abspath(
        os.path.join(current_app.root_path, "..", "data", "samples", "rutas_wkt.csv")
    )
    if not os.path.exists(path):
        return jsonify({"error": "Archivo de ejemplo no encontrado."}), 404
    return send_file(path, as_attachment=True, download_name="rutas_wkt.csv")


@upload_bp.route("/sample/mgrs", methods=["GET"])
def sample_mgrs():
    path = os.path.abspath(
        os.path.join(current_app.root_path, "..", "data", "samples", "rutas_mgrs.csv")
    )
    if not os.path.exists(path):
        return jsonify({"error": "Archivo de ejemplo no encontrado."}), 404
    return send_file(path, as_attachment=True, download_name="rutas_mgrs.csv")
