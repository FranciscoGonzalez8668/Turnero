# Turnero

Guía rápida para que tu cliente lo ejecute en Windows con Python + venv.

## Requisitos
- Python 3.11/3.12 instalado y disponible como `python`.
- Acceso a internet la primera vez para descargar Chromium de Playwright.

## Pasos en PowerShell
```powershell
cd ruta\al\proyecto

# Crear y activar venv
python -m venv .venv
.\.venv\Scripts\activate

# Instalar dependencias
pip install --upgrade pip
pip install -r requirements.txt

# Descargar el navegador de Playwright (solo la primera vez)
python -m playwright install chromium

# Ejecutar el bot
python main.py
```

## Notas
- Los logs quedan en `logs/turnero_*.log` dentro de la carpeta donde ejecutes el comando.
- Los comprobantes descargados se guardan en el directorio de ejecución (`cwd`).
