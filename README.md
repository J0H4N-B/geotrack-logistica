# 🗺️ GeoTrack — Sistema de Georreferenciación Logística

Dashboard interactivo para visualizar rutas comerciales y zonas de distribución
sobre un mapa. Soporta archivos **CSV** (con columnas de coordenadas) y **GeoJSON**
(polígonos, puntos, líneas). Detecta automáticamente las columnas de coordenadas.

## 🛠️ Stack

| Capa       | Tecnología                          |
|------------|-------------------------------------|
| Backend    | Python 3.9+ · Flask · Blueprints    |
| Datos      | Pandas · CSV / GeoJSON              |
| Frontend   | HTML · CSS · JavaScript             |
| Mapas      | Leaflet.js                          |
| Iconos     | Boxicons                            |
| Seguridad  | Werkzeug · python-dotenv            |

## 🚀 Instalación

```bash
git clone https://github.com/TU_USUARIO/geotrack-logistica.git
cd geotrack-logistica

python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env       # Edita SECRET_KEY

python run.py
# http://localhost:5000
```

## 📁 Estructura

```
proyecto2_geo/
├── run.py
├── config.py
├── requirements.txt
├── .env.example
├── data/
│   ├── samples/
│   │   ├── rutas_ejemplo.csv        # CSV con lat/lon por punto de visita
│   │   └── zonas_ejemplo.geojson    # GeoJSON con polígonos de zonas
│   └── uploads/                     # Archivos subidos (auto-creada)
├── app/
│   ├── __init__.py
│   ├── blueprints/
│   │   ├── main.py                  # Sirve el frontend
│   │   ├── upload.py                # /api/upload — carga y análisis
│   │   └── geo.py                   # /api/geo   — datos del mapa
│   └── utils/
│       └── file_handler.py          # Validación CSV y GeoJSON
└── templates/
    └── index.html
```

## 📋 Formatos soportados

### CSV
Debe tener columnas de coordenadas. El sistema las detecta automáticamente
buscando nombres como:

| Latitud                        | Longitud                         |
|-------------------------------|----------------------------------|
| `lat`, `latitude`, `latitud`  | `lon`, `lng`, `longitude`, `longitud` |
| `y_coord`, `coord_y`          | `x_coord`, `coord_x`            |

Si no las detecta automáticamente, puedes seleccionarlas manualmente en la interfaz.

### GeoJSON
Cualquier GeoJSON válido con `FeatureCollection`, `Feature` o geometría directa.
Se validan automáticamente:
- Estructura JSON correcta
- Presencia de features
- Existencia de coordenadas en las geometrías

## ✨ Funcionalidades

- **Upload dinámico** de CSV o GeoJSON (drag & drop)
- **Detección automática** de columnas lat/lon con validación de rangos
- **Validación de GeoJSON** — estructura, features y coordenadas
- **Marcadores configurables** — color y tamaño por columna del CSV
- **Polígonos interactivos** — hover y popup con propiedades
- **Filtros por pills** generados dinámicamente desde el archivo
- **KPIs agregados** de columnas numéricas según filtros activos
- **Cambio de mapa base** — oscuro (CartoDB) / satélite (Esri)
- **Popups informativos** con todas las propiedades del punto/zona

## 🔒 Seguridad

- Solo `.csv` y `.geojson` permitidos
- Nombre sanitizado con UUID único
- Ruta en sesión del servidor (no expuesta al cliente)
- Límite de 10 MB configurable en `.env`
- Límite de 50.000 filas para CSV
- Validación de rangos lat (-90/90) y lon (-180/180)
- Columnas de filtro validadas contra el DataFrame real

## 📄 Licencia

MIT
