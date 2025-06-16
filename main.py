import os
import time
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup


def get_env_vars():
    load_dotenv()
    return (
        os.getenv("FASTCLINICA_URL"),
        os.getenv("FASTCLINICA_USER"),
        os.getenv("FASTCLINICA_PASS"),
    )


def init_driver():
    # Configura opciones de Chrome para ejecución headless
    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")

    # Define la ruta relativa a tu chromedriver
    driver_path = os.path.join("utils", "chromedriver")

    # Crea el servicio usando la ruta del ejecutable
    service = Service(executable_path=driver_path)

    return webdriver.Chrome(service=service, options=opts)


def login(driver, url, user, password):
    # Abre la página de login
    driver.get(f"{url}/login")

    # Crea un objeto de espera (máximo 10 segundos)
    wait = WebDriverWait(driver, 10)

    # Espera a que el campo de email esté presente y luego envía el usuario
    email_field = wait.until(EC.presence_of_element_located((By.ID, "email")))
    email_field.send_keys(user)

    # Envía la contraseña (no necesita espera si el campo de email ya cargó)
    driver.find_element(By.ID, "password").send_keys(password)

    # Espera a que el botón de submit sea clickeable y luego haz clic
    submit_button = wait.until(
        EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']"))
    )
    submit_button.click()

    # Espera a que la URL cambie o que un elemento de la siguiente página aparezca
    # Por ejemplo, esperamos a que la URL ya no contenga la palabra "login"
    wait.until(EC.url_changes(f"{url}/login"))


def buscar_paciente(driver, url, cedula):
    # Navega a la URL de búsqueda por cédula
    driver.get(f"{url}/pacientes/buscar?cedula={cedula}")
    time.sleep(2)


def capturar_html_pestanas(driver):
    # Selecciona y guarda el HTML completo de dos pestañas
    driver.find_element("xpath", "//a[text()='Historia Clínica']").click()
    time.sleep(1)
    html_historia = driver.page_source

    driver.find_element("xpath", "//a[text()='Plan de Manejo']").click()
    time.sleep(1)
    html_plan = driver.page_source

    return html_historia, html_plan


def extraer_datos(html_historia, html_plan, cedula):
    # Crea el diccionario con:
    # - HTML bruto de cada pestaña
    # - Extracciones de los campos relevantes para los placeholders
    datos = {
        # Claves = placeholders en la plantilla Word
        "RAW_HTML_HISTORIA": html_historia,
        "RAW_HTML_PLAN": html_plan,
        "CEDULA": cedula,
    }

    # Parseo con BeautifulSoup para obtener valores puntuales
    soup_h = BeautifulSoup(html_historia, "html.parser")
    # Ejemplo de extracción puntual:
    nombre_el = soup_h.select_one(".paciente-nombre")
    if nombre_el:
        datos["NOMBRE_PACIENTE"] = nombre_el.get_text(strip=True)

    fecha_diag_el = soup_h.find(
        "td", string=lambda t: t and "Fecha de la prueba presuntiva" in t
    )
    if fecha_diag_el and fecha_diag_el.find_next_sibling("td"):
        datos["FECHA_DIAGNOSTICO"] = fecha_diag_el.find_next_sibling("td").get_text(
            strip=True
        )

    # Aquí se pueden agregar más campos a extraer según los placeholders definidos
    # p.ej. datos["FECHA_INICIO_TAR"], datos["ESTADIO_CLINICO"], etc.

    return datos


def main():
    FASTCLINICA_URL, USER, PASS = get_env_vars()
    # Lista de cédulas a procesar (demo)
    cedulas = ["1107088958"]
    pacientes = []

    driver = init_driver()
    print("Iniciando sesión en Fastclínica...")
    try:
        login(driver, FASTCLINICA_URL, USER, PASS)

        for cedula in cedulas:
            print(f"Procesando cédula: {cedula}")
            buscar_paciente(driver, FASTCLINICA_URL, cedula)
            html_historia, html_plan = capturar_html_pestanas(driver)
            datos = extraer_datos(html_historia, html_plan, cedula)
            pacientes.append(datos)

        print("Proceso completado.")
    except Exception as e:
        print(f"Error durante la ejecución: {e}")
    finally:
        driver.quit()

    # Muestra la lista de diccionarios resultante
    print(pacientes)


if __name__ == "__main__":
    main()
