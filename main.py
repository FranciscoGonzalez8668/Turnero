import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
import re

import pandas as pd
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


# ==============================
# CONFIGURACIÓN
# ==============================

PROXY = {
    "server": "http://1.2.3.4:8080",   # IP y puerto del proxy
    "username": "user123",
    "password": "pass123"
}

EXCEL_PATH = Path("turnos.xlsx")
URL_PRINCIPAL = (
    "https://www.exteriores.gob.es/Consulados/bahiablanca/es/ServiciosConsulares/"
    "Paginas/Solicitud-de-cita-previa--Ley-de-Memoria-Democr%c3%a1tica.aspx"
)

# Horarios de apertura de turnera (hh, mm) -> ajustar según realidad
TURNERA_SLOTS = [
    (0, 10),
    (1, 10),
    (2, 10),
    (3, 10),
    # Agregar más si hace falta...
]

# Nombre de columnas en el Excel
COL_USUARIO = "Usuario"
COL_PASSWORD = "Contraseña"
COL_TURNO = "Turno Conseguido"

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
LOG_LEVEL = logging.INFO

# Selectores centralizados para ajustarlos en un solo lugar
SELECTORES = {
    "fecha_y_hora": "text=Fecha y hora",
    "popup_aceptar": "text=Aceptar",
    "landing_continuar": [
        "button:has-text('Continue / Continuar')",
        "text=Continue / Continuar",
        "text=Continuar",
    ],
    "login_usuario": [
        "input[placeholder*='DNI']",
        "input[name='dni']",
        "input#dni",
        "input[name='usuario']",
    ],
    "login_password": [
        "input[placeholder*='Contraseña']",
        "input[type='password']",
        "input#password",
        "input[name='password']",
    ],
    "login_submit": [
        "button:has-text('Acceder')",
        "text=Acceder",
        "button[type='submit']",
    ],
    "login_error": "text=usuario o contraseña incorrectos",  # Ajustar
    "continuar_turnera": "text=Continuar",  # Ajustar
    "spinner": ".spinner",  # Ajustar o remover
    "cartel_condiciones": "text=condiciones",  # Ajustar
    "cartel_aceptar": "text=Aceptar",  # Ajustar
    "tabla_turnos": "table#turnos, .tabla-turnos",  # Ajustar
    "botones_turno": "text=Reservar, text=Seleccionar",  # Ajustar
    "confirmar": "text=Confirmar",  # Ajustar
    "confirmacion_ok": "text=Turno reservado",  # Ajustar
    "sin_turnos_text": "text=No hay horas disponibles",  # Ajustar
    # Flujo “consultar mis reservas” cuando no hay turnos
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


# ==============================
# UTILIDADES DE TIEMPO
# ==============================

def calcular_proximo_horario_turnera(now: datetime | None = None) -> datetime:
    """
    Devuelve el próximo datetime en el que se abre la turnera según TURNERA_SLOTS.
    Si ya pasaron todos los slots de hoy, devuelve el primero de mañana.
    """
    if now is None:
        now = datetime.now()

    candidatos = []
    for h, m in TURNERA_SLOTS:
        dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if dt > now:
            candidatos.append(dt)

    if candidatos:
        return min(candidatos)

    # Ningún slot futuro hoy -> tomar el primero de mañana
    h, m = TURNERA_SLOTS[0]
    mañana = now + timedelta(days=1)
    return mañana.replace(hour=h, minute=m, second=0, microsecond=0)


def esperar_hasta(target: datetime):
    """Bloquea el proceso hasta el datetime target."""
    while True:
        now = datetime.now()
        if now >= target:
            break
        # dormir en bloques, más largos al principio, más cortos al final
        diff = (target - now).total_seconds()
        if diff > 60:
            time.sleep(30)
        elif diff > 10:
            time.sleep(5)
        else:
            time.sleep(0.5)


# ==============================
# UTILIDADES DE PLAYWRIGHT
# ==============================

def _log_exception(usuario: str, msg: str, err: Exception):
    logging.exception("[%s] %s: %s", usuario, msg, err)


def _safe_click(page, selector: str, usuario: str, timeout: int = 30000, optional: bool = False) -> bool:
    try:
        page.click(selector, timeout=timeout)
        return True
    except PlaywrightTimeoutError:
        if optional:
            logging.info("[%s] Elemento opcional no encontrado: %s", usuario, selector)
        else:
            logging.warning("[%s] No se pudo clickear selector: %s", usuario, selector)
        return False
    except Exception as err:  # noqa: BLE001
        _log_exception(usuario, f"Error haciendo click en {selector}", err)
        return False


def _wait_selector(page, selector: str, usuario: str, timeout: int = 30000) -> bool:
    try:
        page.wait_for_selector(selector, timeout=timeout)
        return True
    except PlaywrightTimeoutError:
        logging.warning("[%s] No se encontró selector: %s", usuario, selector)
        return False
    except Exception as err:  # noqa: BLE001
        _log_exception(usuario, f"Error esperando selector {selector}", err)
        return False


def _click_first_available(page, selectors, usuario: str, timeout: int = 30000) -> bool:
    """Intenta clickear el primer selector que funcione."""
    for selector in selectors:
        if _safe_click(page, selector, usuario, timeout=timeout):
            return True
    logging.warning("[%s] Ningún selector funcionó: %s", usuario, selectors)
    return False


def _click_first_available_any_frame(page, selectors, usuario: str, timeout: int = 30000) -> bool:
    """
    Intenta clickear el primer selector probando el main frame y todos los iframes.
    Útil cuando la landing está embebida.
    """
    frames = [("page", page)] + [(f"frame:{idx}", frame) for idx, frame in enumerate(page.frames)]
    for frame_name, frame in frames:
        for selector in selectors:
            try:
                frame.click(selector, timeout=timeout)
                logging.info("[%s] Click en '%s' dentro de %s", usuario, selector, frame_name)
                return True
            except PlaywrightTimeoutError:
                continue
            except Exception as err:  # noqa: BLE001
                _log_exception(usuario, f"Error click en {selector} ({frame_name})", err)
                continue
    logging.warning("[%s] No se pudo clickear con ningún selector en ningún frame: %s", usuario, selectors)
    return False


def _contains_text_any_frame(page, textos: list[str]) -> bool:
    """Devuelve True si alguno de los textos aparece en cualquier frame."""
    for frame in page.frames:
        try:
            html = frame.content()
        except Exception:
            continue
        for txt in textos:
            if txt.lower() in html.lower():
                return True
    return False


def _fill_first_available_any_frame(page, selectors, value: str, usuario: str) -> bool:
    sels = selectors if isinstance(selectors, list) else [selectors]
    for frame in page.frames:
        for selector in sels:
            try:
                frame.click(selector, timeout=3000)
                frame.fill(selector, value, timeout=5000)
                logging.info("[%s] Fill '%s' en frame %s", usuario, selector, frame.url)
                return True
            except PlaywrightTimeoutError:
                logging.debug("[%s] Selector no disponible aún: %s en frame %s", usuario, selector, frame.url)
                continue
            except Exception as err:  # noqa: BLE001
                _log_exception(usuario, f"Error llenando {selector} ({frame.url})", err)
                continue
    logging.warning("[%s] No se pudo llenar ningún selector: %s", usuario, selectors)
    return False


def _wait_for_loading_end(page, usuario: str, timeout_ms: int = 20000) -> bool:
    """
    Espera a que desaparezcan loaders conocidos en cualquier frame,
    sin depender de dormir por segundos fijos.
    """
    deadline = time.time() + timeout_ms / 1000
    loaders = SELECTORES["loaders"]

    while time.time() < deadline:
        loader_found = False
        for frame in page.frames:
            for sel in loaders:
                try:
                    handle = frame.query_selector(sel)
                except Exception:
                    continue
                if handle:
                    loader_found = True
                    try:
                        frame.wait_for_selector(sel, state="hidden", timeout=2000)
                    except PlaywrightTimeoutError:
                        # seguir intentando hasta deadline
                        pass
        if not loader_found:
            # Confirmar que no hay requests en vuelo
            try:
                page.wait_for_load_state("networkidle", timeout=2000)
            except PlaywrightTimeoutError:
                pass
            return True
    logging.warning("[%s] Timeout esperando fin de loading", usuario)
    return False


def _wait_for_any_frame_selector(page, selectors, usuario: str, timeout_ms: int = 10000) -> bool:
    """Espera a que exista alguno de los selectores en cualquier frame."""
    end = time.time() + timeout_ms / 1000
    sels = selectors if isinstance(selectors, list) else [selectors]
    while time.time() < end:
        for frame in page.frames:
            for sel in sels:
                try:
                    if frame.query_selector(sel):
                        return True
                except Exception:
                    continue
        time.sleep(0.3)
    logging.warning("[%s] Timeout esperando selectores %s en algún frame", usuario, sels)
    return False


def _get_widget_frame(page):
    """Devuelve el frame principal del widget (bookitit/citaconsular) si existe."""
    for frame in page.frames:
        if "citaconsular" in frame.url or "bookitit" in frame.url:
            return frame
    return page.main_frame


def _wait_fill_in_frame(frame, selectors, value: str, usuario: str, timeout_ms: int = 10000) -> bool:
    """Espera selector en frame específico y lo completa; si falla, fuerza value via JS."""
    end = time.time() + timeout_ms / 1000
    sels = selectors if isinstance(selectors, list) else [selectors]
    while time.time() < end:
        for selector in sels:
            try:
                frame.wait_for_selector(selector, timeout=2000)
                frame.click(selector, timeout=2000)
                frame.fill(selector, value, timeout=5000)
                logging.info("[%s] Fill '%s' en frame %s", usuario, selector, frame.url)
                return True
            except PlaywrightTimeoutError:
                # Intentar forzar con JS si el selector existe pero fill falla
                try:
                    handle = frame.query_selector(selector)
                    if handle:
                        frame.evaluate(
                            "(el, val) => { el.focus(); el.value = val; el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); }",
                            handle,
                            value,
                        )
                        logging.info("[%s] Force-filled '%s' en frame %s", usuario, selector, frame.url)
                        return True
                except Exception:
                    pass
                continue
            except Exception as err:  # noqa: BLE001
                _log_exception(usuario, f"Error llenando {selector} ({frame.url})", err)
                continue
        time.sleep(0.3)
    logging.warning("[%s] No se pudo llenar selectores en frame %s: %s", usuario, frame.url, sels)
    return False


def _formatear_dni(dni: str) -> str:
    """Formatea DNI argentino a XX.XXX.XXX si es posible."""
    digits = re.sub(r"\D", "", dni)
    if len(digits) == 8:
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:]}"
    if len(digits) == 7:
        return f"{digits[:1]}.{digits[1:4]}.{digits[4:]}"
    return dni


def _login_desde_consultar(page, usuario: str, password: str) -> bool:
    """
    Abre 'Cancelar o consultar mis reservas', se loguea y vuelve atrás.
    Devuelve True si logró hacer el ciclo.
    """
    if not _click_first_available_any_frame(
        page, [SELECTORES["consultar_link"]], usuario, timeout=10000
    ):
        logging.warning("[%s] No se pudo abrir 'Cancelar o consultar mis reservas'", usuario)
        return False

    _wait_for_loading_end(page, usuario, timeout_ms=15000)

    dni_fmt = _formatear_dni(usuario)
    if not _fill_first_available_any_frame(page, SELECTORES["consultar_dni"], dni_fmt, usuario):
        return False
    if not _fill_first_available_any_frame(page, SELECTORES["consultar_password"], password, usuario):
        return False

    if not _click_first_available_any_frame(
        page, SELECTORES["consultar_login_btn"], usuario, timeout=8000
    ):
        logging.warning("[%s] No se pudo clickear Acceder en consultar", usuario)
        return False

    _wait_for_loading_end(page, usuario, timeout_ms=15000)

    if not _click_first_available_any_frame(
        page, SELECTORES["consultar_back"], usuario, timeout=8000
    ):
        logging.warning("[%s] No se encontró flecha/volver a pedir cita", usuario)
        return False

    _wait_for_loading_end(page, usuario, timeout_ms=10000)
    return True


# ==============================
# LÓGICA DE TURNOS
# ==============================

def intentar_sacar_turno(page, usuario: str, password: str) -> str:
    """
    Ejecuta todo el flujo de sacar turno para un usuario.
    Devuelve:
        "OK"          -> turno confirmado
        "SIN_TURNOS"  -> no había turnos / se agotaron
        "BLOQUEADO"   -> IP / usuario bloqueado
        "ERROR"       -> cualquier otro error
    """

    page.set_default_timeout(30000)
    page.set_default_navigation_timeout(60000)

    # 1. Ir a página principal
    page.goto(URL_PRINCIPAL, wait_until="load", timeout=60000)

    _safe_click(page, SELECTORES["fecha_y_hora"], usuario)

    # Si aparece popup, aceptarlo
    _safe_click(page, SELECTORES["popup_aceptar"], usuario, timeout=5000, optional=True)

    # La web abre el widget en la misma pestaña o en una nueva; capturamos ambos casos
    work_page = page
    try:
        new_page = page.context.wait_for_event("page", timeout=15000)
        work_page = new_page
        work_page.wait_for_load_state("load")
        logging.info("[%s] Se abrió nueva pestaña para el widget: %s", usuario, work_page.url)
    except PlaywrightTimeoutError:
        work_page.wait_for_load_state("load")
        logging.info("[%s] Sin nueva pestaña; seguimos en la actual: %s", usuario, work_page.url)

    logging.info("[%s] URL tras popup: %s", usuario, work_page.url)
    for idx, frame in enumerate(work_page.frames):
        logging.info("[%s] Frame %s: %s", usuario, idx, frame.url)

    # El botón de continuar suele estar dentro de un iframe de citaconsular
    _click_first_available_any_frame(work_page, SELECTORES["landing_continuar"], usuario, timeout=20000)
    work_page.wait_for_load_state("load")
    _wait_for_loading_end(work_page, usuario, timeout_ms=25000)

    # 2. Login
    # A partir de aquí usamos la página donde quedó el widget
    page = work_page
    widget_frame = _get_widget_frame(page)

    try:
        # Primero intentar abrir el flujo de consulta si está disponible
        _wait_for_any_frame_selector(page, [SELECTORES["consultar_link"]], usuario, timeout_ms=20000)
        _click_first_available_any_frame(page, [SELECTORES["consultar_link"]], usuario, timeout=12000)
        _wait_for_loading_end(page, usuario, timeout_ms=12000)

        if not _wait_fill_in_frame(widget_frame, SELECTORES["login_usuario"], _formatear_dni(usuario), usuario, timeout_ms=12000):
            raise PlaywrightTimeoutError("No se pudo ubicar campo usuario")

        if not _wait_fill_in_frame(widget_frame, SELECTORES["login_password"], password, usuario, timeout_ms=12000):
            raise PlaywrightTimeoutError("No se pudo ubicar campo contraseña")

        _click_first_available_any_frame(page, SELECTORES["login_submit"], usuario, timeout=12000)
    except PlaywrightTimeoutError:
        # Loguear un recorte del HTML para debug
        try:
            for idx, frame in enumerate(page.frames):
                html = frame.content()[:5000]
                logging.warning("[%s] DEBUG frame %s (url %s) snippet: %s", usuario, idx, frame.url, html)
        except Exception as err:  # noqa: BLE001
            _log_exception(usuario, "No se pudo leer HTML para debug", err)
        return "ERROR"

    # 3. Verificar login
    try:
        page.wait_for_selector(SELECTORES["login_error"], timeout=5000)
        return "ERROR"
    except PlaywrightTimeoutError:
        # No vimos el mensaje de error rápido; asumimos login OK
        pass

    # 4. Ir a la pantalla donde está "continuar"
    # Esto depende de cómo es la web; puede que ya estemos ahí,
    # o necesitemos un click intermedio.
    # TODO: si hace falta, agregar pasos para llegar a esa pantalla.
    if not _wait_selector(page, SELECTORES["continuar_turnera"], usuario):
        return "ERROR"

    # 5. Calcular horario objetivo
    proximo_slot = calcular_proximo_horario_turnera()
    click_time = proximo_slot - timedelta(seconds=10)

    logging.info("[%s] Próximo horario turnera: %s", usuario, proximo_slot)
    logging.info("[%s] Click en 'Continuar' a: %s", usuario, click_time)

    # Esperar hasta 10 segundos antes del horario de apertura
    esperar_hasta(click_time)

    # 6. Hacer click en "Continuar" EXACTO
    _safe_click(page, SELECTORES["continuar_turnera"], usuario)

    # 7. Esperar spinner y transición
    # TODO: ajustar selector de spinner si existe; si no, podemos esperar un tiempo fijo y seguir.
    try:
        page.wait_for_selector(SELECTORES["spinner"], timeout=15000)
        page.wait_for_timeout(1000)
        # esperar que desaparezca
        page.wait_for_selector(SELECTORES["spinner"], state="detached", timeout=30000)
    except PlaywrightTimeoutError:
        # Spinner no apareció; seguimos igual, pero lo anotamos
        logging.info("[%s] No se detectó spinner, continuando igual...", usuario)

    # 8. Cartel con letras azules + aceptar
    # TODO: ajustar textos/selector concreto.
    try:
        page.wait_for_selector(SELECTORES["cartel_condiciones"], timeout=20000)
        _safe_click(page, SELECTORES["cartel_aceptar"], usuario, timeout=5000, optional=True)
    except PlaywrightTimeoutError:
        # Puede que no haya cartel; seguimos
        pass

    # 9. Esperar listado de turnos
    # TODO: ajustar selector de tabla/lista de turnos
    if not _wait_selector(page, SELECTORES["tabla_turnos"], usuario, timeout=20000):
        # Mirar si bloqueo u otros errores
        html = page.content()
        if "bloqueado" in html or "demasiados intentos" in html:
            return "BLOQUEADO"
        return "ERROR"

    # 10. Elegir un turno
    # Estrategia simple: elegir el primer botón "Reservar"/"Seleccionar" disponible.
    # TODO: adaptar a clase/nombre real del botón.
    botones_turno = page.query_selector_all(SELECTORES["botones_turno"])
    if not botones_turno:
        return "SIN_TURNOS"

    # Ejemplo estrategia: tomar el último de la lista
    boton_elegido = botones_turno[-1]
    boton_elegido.click()

    # 11. Confirmar la reserva
    # TODO: ajustar selector de botón de confirmación
    try:
        page.wait_for_selector(SELECTORES["confirmar"], timeout=10000)
        _safe_click(page, SELECTORES["confirmar"], usuario)
    except PlaywrightTimeoutError:
        # Si no aparece el botón de confirmar, algo raro pasó
        return "ERROR"

    # 12. Detectar pantalla de confirmación (ticket)
    # TODO: ajustar textos/elementos que indiquen éxito real
    try:
        page.wait_for_selector(SELECTORES["confirmacion_ok"], timeout=15000)
        return "OK"
    except PlaywrightTimeoutError:
        # Chequear mensajes de error de último segundo
        html = page.content()
        if "ya no está disponible" in html:
            return "SIN_TURNOS"
        return "ERROR"


# ==============================
# FLUJO PRINCIPAL
# ==============================

def main():
    logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)

    if not EXCEL_PATH.exists():
        logging.error("No se encontró el Excel en %s", EXCEL_PATH)
        return

    # Cargar Excel
    try:
        df = pd.read_excel(EXCEL_PATH, engine="openpyxl").fillna("")
    except Exception as err:  # noqa: BLE001
        logging.exception("No se pudo cargar el Excel: %s", err)
        return

    # Asegurar que exista la columna de resultado
    if COL_TURNO not in df.columns:
        df[COL_TURNO] = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(
                headless=False
            )

        for idx, row in df.iterrows():
            usuario = str(row.get(COL_USUARIO, "")).strip()
            password = str(row.get(COL_PASSWORD, "")).strip()
            turno_conseguido = str(row.get(COL_TURNO, "")).strip()

            if not usuario or not password:
                logging.warning("[FILA %s] Usuario/Contraseña vacíos, saltando...", idx)
                continue

            if turno_conseguido.upper() == "SI":
                logging.info("[%s] Ya tiene turno (Turno Conseguido = SI), saltando...", usuario)
                continue

            logging.info("=== Intentando sacar turno para usuario: %s ===", usuario)

            page = browser.new_page()

            try:
                resultado = intentar_sacar_turno(page, usuario, password)
            except Exception as err:  # noqa: BLE001
                _log_exception(usuario, "EXCEPCIÓN no controlada", err)
                resultado = "ERROR"
            finally:
                page.close()

            logging.info("[%s] Resultado: %s", usuario, resultado)

            if resultado == "OK":
                df.loc[idx, COL_TURNO] = "SI"
            # Opcional: marcar otros estados
            # elif resultado == "SIN_TURNOS":
            #     df.loc[idx, COL_TURNO] = "SIN_TURNOS"
            # elif resultado == "BLOQUEADO":
            #     df.loc[idx, COL_TURNO] = "BLOQUEADO"
            # else:
            #     df.loc[idx, COL_TURNO] = "ERROR"

            # Guardar Excel tras cada intento por seguridad
            try:
                df.to_excel(EXCEL_PATH, index=False)
            except Exception as err:  # noqa: BLE001
                logging.exception("No se pudo guardar el Excel: %s", err)
                # Si falla guardado, seguimos con siguiente usuario para no frenar el proceso

        browser.close()

    logging.info("Proceso terminado. Excel actualizado.")


if __name__ == "__main__":
    main()
