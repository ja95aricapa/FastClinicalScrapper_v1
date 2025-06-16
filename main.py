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
    opts.add_argument("--headless=new") # El modo headless nuevo es más estable
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage") # Necesario en muchos entornos Linux/Docker

    # Define la ruta relativa a tu chromedriver
    driver_path = os.path.join("utils", "chromedriver")

    # Crea el servicio usando la ruta del ejecutable
    service = Service(executable_path=driver_path)

    return webdriver.Chrome(service=service, options=opts)


def login(driver, url, user, password):
    # Abre la página de login
    driver.get(f"{url}/login")
    wait = WebDriverWait(driver, 10)
    print("Página de login cargada. Ingresando credenciales...")

    # Ingresar credenciales
    email_field = wait.until(EC.presence_of_element_located((By.ID, "email")))
    email_field.send_keys(user)
    driver.find_element(By.ID, "password").send_keys(password)

    # Hacer clic en el botón de login
    submit_button = wait.until(
        EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']"))
    )
    submit_button.click()

    # Espera a que cargue el dashboard (Escritorio) después del login
    wait.until(EC.presence_of_element_located((By.XPATH, "//h1[contains(text(), 'Escritorio')]")))
    print("Login exitoso. Redirigido al Escritorio.")


# --- NUEVA FUNCIÓN ---
def ir_a_encuentros(driver, url):
    """Navega directamente a la página de Encuentros."""
    encuentros_url = f"{url}/encounters"
    print(f"Navegando a la página de Encuentros: {encuentros_url}")
    driver.get(encuentros_url)
    
    # Espera a que un elemento distintivo de la página de Encuentros cargue
    # Por ejemplo, el título de la página. Ajusta si es necesario.
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.XPATH, "//h1[contains(text(), 'Encuentros')]"))
    )
    print("Página de Encuentros cargada correctamente.")
    

def buscar_paciente(driver, url, cedula):
    # Ya estamos en la sección de 'encuentros', ahora buscamos directamente al paciente
    # NOTA: La URL de búsqueda de paciente puede ser diferente desde 'encuentros'
    # Por ahora, mantendremos la URL original de búsqueda que tenías.
    # Si la búsqueda se hace desde un campo en la página de encuentros, este código debe cambiar.
    
    paciente_url = f"{url}/pacientes/buscar?cedula={cedula}"
    print(f"Buscando paciente en: {paciente_url}")
    driver.get(paciente_url)
    
    # Espera a que cargue la página del paciente (ej. la pestaña 'Historia Clínica')
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.XPATH, "//a[text()='Historia Clínica']"))
    )
    print(f"Página del paciente con cédula {cedula} cargada.")


def capturar_html_pestanas(driver):
    wait = WebDriverWait(driver, 10)
    
    # Clic en 'Historia Clínica'
    historia_tab = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[text()='Historia Clínica']")))
    historia_tab.click()
    time.sleep(1) # Pequeña pausa para que el JS renderice el contenido
    html_historia = driver.page_source

    # Clic en 'Plan de Manejo'
    plan_tab = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[text()='Plan de Manejo']")))
    plan_tab.click()
    time.sleep(1) # Pequeña pausa para que el JS renderice el contenido
    html_plan = driver.page_source
    
    print("HTML de pestañas 'Historia Clínica' y 'Plan de Manejo' capturado.")
    return html_historia, html_plan


def extraer_datos(html_historia, html_plan, cedula):
    datos = {
        "RAW_HTML_HISTORIA": html_historia,
        "RAW_HTML_PLAN": html_plan,
        "CEDULA": cedula,
    }

    soup_h = BeautifulSoup(html_historia, "html.parser")
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
    
    print(f"Datos extraídos para el paciente {cedula}.")
    return datos


def main():
    FASTCLINICA_URL, USER, PASS = get_env_vars()
    cedulas = ["1107088958"]
    pacientes = []

    driver = init_driver()
    print("Iniciando scraper...")
    try:
        # 1. Iniciar sesión
        login(driver, FASTCLINICA_URL, USER, PASS)

        # 2. Ir a la página de encuentros (NUEVO PASO)
        ir_a_encuentros(driver, FASTCLINICA_URL)

        # 3. Procesar cada cédula
        for cedula in cedulas:
            print(f"--- Procesando cédula: {cedula} ---")
            buscar_paciente(driver, FASTCLINICA_URL, cedula)
            html_historia, html_plan = capturar_html_pestanas(driver)
            datos = extraer_datos(html_historia, html_plan, cedula)
            pacientes.append(datos)

        print("--- Proceso completado exitosamente. ---")
    except Exception as e:
        print(f"\n!!! Error durante la ejecución: {e} !!!")
        # Guardar un screenshot para depuración
        screenshot_path = f"error_screenshot_{int(time.time())}.png"
        driver.save_screenshot(screenshot_path)
        print(f"Screenshot guardado en: {screenshot_path}")
    finally:
        driver.quit()
        print("Driver cerrado.")

    # Muestra la lista de diccionarios resultante
    print("\n--- Resultados Finales ---")
    print(pacientes)


if __name__ == "__main__":
    main()