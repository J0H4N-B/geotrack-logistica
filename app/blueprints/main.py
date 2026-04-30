"""
app/blueprints/main.py — Blueprint principal
Sirve el frontend del mapa.
"""

from flask import Blueprint, render_template

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    return render_template("index.html")
