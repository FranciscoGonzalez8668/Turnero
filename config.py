from pathlib import Path

# ==============================
# CONFIGURACIÓN BÁSICA
# ==============================

PROXY = {
    "server": "http://1.2.3.4:8080",
    "username": "user123",
    "password": "pass123",
}

EXCEL_PATH = Path("turnos.xlsx")
URL_PRINCIPAL = (
    "https://www.exteriores.gob.es/Consulados/bahiablanca/es/ServiciosConsulares/"
    "Paginas/Solicitud-de-cita-previa--Ley-de-Memoria-Democr%c3%a1tica.aspx"
)

TURNERA_SLOTS = [
    (0, 10),
    (1, 10),
    (2, 10),
    (3, 10),
]

COL_USUARIO = "Usuario"
COL_PASSWORD = "Contraseña"
COL_TURNO = "Turno Conseguido"

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
LOG_LEVEL = "INFO"

# Concurrencia
MAX_CONCURRENT_BOTS = 2  # ajustar según recursos/IP
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
]

# Selectores centralizados
SELECTORES = {
    "fecha_y_hora": "text=Fecha y hora",
    "popup_aceptar": "text=Aceptar",
    "landing_continuar": [
        "button:has-text('Continue / Continuar')",
        "text=Continue / Continuar",
        "text=Continuar",
        "a:has-text('Continuar')",
        ".clsDivContinueButton:has-text('Continuar')",
        "#idDivBktServicesContinueButton",
    ],
    "login_usuario": [
        "input[placeholder*='DNI']",
        "input[name='dni']",
        "input#dni",
        "input[name='usuario']",
    ],
    "login_password": [
        "#idIptBktAccountLoginpassword",
        "#idIptBktSignInpassword",
        "input[placeholder*='Contraseña']",
        "input[type='password']",
        "input#password",
        "input[name='password']",
    ],
    "login_submit": [
        "#idBktDefaultAccountLoginConfirmButton",
        "#idBktDefaultSignInConfirmButton",
        "button:has-text('Acceder')",
        "text=Acceder",
        "button[type='submit']",
    ],
    "login_error": "text=usuario o contraseña incorrectos",
    "continuar_turnera": "text=Continuar",
    "spinner": ".spinner",
    "cartel_condiciones": "text=condiciones",
    "cartel_aceptar": "text=Aceptar",
    "tabla_turnos": "table#turnos, .tabla-turnos",
    "botones_turno": "text=Reservar, text=Seleccionar",
    "servicio_card": [
        "text=Presentación de documentación ley",
        "text=MEMORIA DEMOCRÁTICA",
        "text=PRESENTACIÓN DE DOCUMENTACIÓN LEY",
        "text=Memoria democrática",
        "#idListServices a",
        ".clsBktServiceDataContainer a",
        ".clsBktServiceDataContainer",
    ],
    "confirmar": "text=Confirmar",
    "confirmacion_ok": "text=Turno reservado",
    "sin_turnos_text": "text=No hay horas disponibles",
    "consultar_link": "text=Cancelar o consultar mis reservas",
    "consultar_dni": [
        "#idIptBktAccountLoginlogin",
        "input[placeholder*='DNI']",
        "input[name='login']",
        "input[name='dni']",
        "input#dni",
    ],
    "consultar_password": [
        "#idIptBktAccountLoginpassword",
        "input[placeholder*='Contraseña']",
        "input[type='password']",
        "input[name='password']",
    ],
    "consultar_login_btn": [
        "#idBktDefaultAccountLoginConfirmButton",
        "button:has-text('Acceder')",
        "text=Acceder",
    ],
    "consultar_back": [
        "text=Volver a pedir cita",
        "button:has-text('Volver a pedir cita')",
        "text=Volver a pedir cita →",
    ],
    "back_arrow": [
        "#idBktDefaultAccountLoginContainer .clsDivSubHeaderBackButton",
        "#idBktDefaultAccountHistoryContainer .clsDivSubHeaderBackButton",
        "#idBktDefaultDatetimeContainer .clsDivSubHeaderBackButton",
        "#idBktDefaultSignInContainer .clsDivSubHeaderBackButton",
        "#idBktWidgetBody .clsDivSubHeaderBackButton",
        "a:has(.clsDivSubHeaderBackButton)",
        "div.clsDivSubHeaderBackButton",
        ".clsDivSubHeaderBackButton",
        "text=Volver a pedir cita",
        "a[href='#services']",
    ],
    "ver_historial": [
        "text=Ver historial",
        "#idBktWidgetDefaultFooterAccountSignOutAccountContainer a:has-text('Ver historial')",
    ],
    "loaders": [
        ".blockUI",
        "div.blockUI",
        ".loading",
        ".spinner",
        ".pace",
        ".pace-progress",
        ".spinner-border",
        ".fa-spinner",
        ".lds-spinner",
    ],
}
