"""
run.py — Punto de entrada
==========================
Desarrollo:   python run.py
Producción:   gunicorn "run:app" --bind 0.0.0.0:8000 --workers 4
"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
