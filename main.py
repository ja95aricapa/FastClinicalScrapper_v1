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
    """Carga las variables de entorno desde el archivo .env."""
    load_dotenv()
    return (
        os.getenv("FASTCLINICA_URL"),
        os.getenv("FASTCLINICA_USER"),
        os.getenv("FASTCLINICA_PASS"),
    )


def init_driver():
    """Inicializa el WebDriver de Selenium."""
    opts = Options()
    # Descomenta la siguiente línea para ejecutar en modo headless (sin interfaz gráfica)
    # opts.add_argument("--headless=new") 
    opts.add_argument("--no-sandbox")
    #opts.add_argument("--headless=new")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1200") # Un tamaño de ventana más grande puede ayudar
    
    # Selenium 4+ puede gestionar el chromedriver automáticamente
    # No es necesario especificar la ruta si chromedriver está en el PATH o si usas selenium-manager
    service = Service() 
    return webdriver.Chrome(service=service, options=opts)


def login(driver, url, user, password):
    """Realiza el login en la plataforma."""
    driver.get(f"{url}/login")
    wait = WebDriverWait(driver, 15)
    print("Página de login cargada. Ingresando credenciales...")

    email_field = wait.until(EC.presence_of_element_located((By.ID, "email")))
    email_field.send_keys(user)
    driver.find_element(By.ID, "password").send_keys(password)

    submit_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']")))
    submit_button.click()

    wait.until(EC.presence_of_element_located((By.XPATH, "//h1[contains(text(), 'Escritorio')]")))
    print("Login exitoso. Redirigido al Escritorio.")


def ir_a_encuentros(driver, url):
    """Navega a la página de Encuentros."""
    encuentros_url = f"{url}/encounters"
    print(f"Navegando a la página de Encuentros: {encuentros_url}")
    driver.get(encuentros_url)
    
    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.XPATH, "//h1[contains(text(), 'Encuentros')]")))
    print("Página de Encuentros cargada correctamente.")


# --- FUNCIÓN DE BÚSQUEDA CORREGIDA ---
def buscar_paciente(driver, cedula):
    """
    Busca un paciente por cédula en la barra de búsqueda GLOBAL y hace clic en el resultado.
    """
    wait = WebDriverWait(driver, 15)
    print(f"Buscando al paciente con cédula: {cedula}...")

    # 1. Localiza el campo de búsqueda GLOBAL en la barra de navegación superior.
    #    Este es el input que se muestra en tu imagen.
    search_input = wait.until(EC.presence_of_element_located((
        By.XPATH, 
        "//input[@id='globalSearchInput']"
    )))

    # 2. Escribe la cédula en el campo
    search_input.clear()
    search_input.send_keys(cedula)
    print(f"Cédula '{cedula}' ingresada en el campo de búsqueda global.")
    
    # Pequeña pausa para permitir que se ejecute la búsqueda (debounce)
    time.sleep(1)

    # 3. Espera a que aparezca el resultado de la búsqueda en el contenedor de resultados.
    #    El selector busca un enlace dentro del contenedor de resultados que contenga la cédula.
    resultado_selector = f"//div[contains(@class, 'filament-global-search-results-container')]//a[contains(., 'CC-{cedula}')]"
    
    print("Esperando resultado de la búsqueda...")
    resultado_link = wait.until(EC.element_to_be_clickable((By.XPATH, resultado_selector)))
    print("Resultado de búsqueda encontrado y clickeable.")

    # 4. Haz clic en el resultado para ir a la página del paciente
    resultado_link.click()
    
    # 5. Espera a que la página de edición del paciente cargue.
    #    Usamos como referencia la presencia del botón/pestaña "Historia Clínica".
    wait.until(EC.presence_of_element_located((By.XPATH, "//button[contains(., 'Historia Clínica')] | //a[contains(., 'Historia Clínica')]")))
    print(f"Página del paciente con cédula {cedula} cargada.")


def capturar_html_pestanas(driver):
    """Navega por las pestañas del paciente y captura su contenido HTML."""
    wait = WebDriverWait(driver, 15)
    
    # Asegúrate de que los selectores de pestañas sean correctos. Pueden ser <a> o <button>.
    historia_tab_selector = "//button[contains(., 'Historia Clínica')] | //a[contains(., 'Historia Clínica')]"
    plan_tab_selector = "//button[contains(., 'Plan de Manejo')] | //a[contains(., 'Plan de Manejo')]"

    print("Cambiando a la pestaña 'Historia Clínica'...")
    historia_tab = wait.until(EC.element_to_be_clickable((By.XPATH, historia_tab_selector)))
    historia_tab.click()
    time.sleep(2) # Espera explícita para asegurar que el contenido dinámico cargue
    html_historia = driver.page_source

    print("Cambiando a la pestaña 'Plan de Manejo'...")
    plan_tab = wait.until(EC.element_to_be_clickable((By.XPATH, plan_tab_selector)))
    plan_tab.click()
    time.sleep(2) # Espera explícita para asegurar que el contenido dinámico cargue
    html_plan = driver.page_source
    
    print("HTML de pestañas 'Historia Clínica' y 'Plan de Manejo' capturado.")
    return html_historia, html_plan


def extraer_datos(html_historia, html_plan, cedula):
    """Extrae datos específicos del HTML capturado."""
    datos = {
        "RAW_HTML_HISTORIA": "...", # Opcional: No guardar todo el HTML si es muy grande
        "RAW_HTML_PLAN": "...",     # Opcional
        "CEDULA": cedula,
        "NOMBRE_PACIENTE": "No encontrado",
        "FECHA_DIAGNOSTICO": "No encontrado"
    }

    # El siguiente código de extracción es un EJEMPLO.
    # Necesitarás ajustar los selectores CSS/BS4 para que coincidan con la estructura REAL
    # de la página de la historia clínica.
    soup_h = BeautifulSoup(html_historia, "html.parser")
    
    # Ejemplo para el nombre (ajustar selector si es necesario)
    nombre_el = soup_h.find('h1') # A menudo el nombre está en el título principal
    if nombre_el:
        datos["NOMBRE_PACIENTE"] = nombre_el.get_text(strip=True)

    # Ejemplo para la fecha (muy dependiente de la estructura)
    # Este es un ejemplo genérico, probablemente necesites uno más específico.
    fecha_diag_el = soup_h.find(lambda tag: "Fecha de la prueba presuntiva" in tag.text and tag.name == 'dt')
    if fecha_diag_el:
        dd_el = fecha_diag_el.find_next_sibling('dd')
        if dd_el:
            datos["FECHA_DIAGNOSTICO"] = dd_el.get_text(strip=True)
    
    print(f"Datos extraídos para el paciente {cedula}: {datos['NOMBRE_PACIENTE']}")
    return datos


def main():
    FASTCLINICA_URL, USER, PASS = get_env_vars()
    if not all([FASTCLINICA_URL, USER, PASS]):
        print("Error: Asegúrate de que las variables de entorno FASTCLINICA_URL, USER y PASS están definidas en el archivo .env")
        return

    cedulas = ["1107088958"] # Puedes añadir más cédulas aquí
    pacientes = []

    driver = init_driver()
    print("Iniciando scraper...")
    try:
        login(driver, FASTCLINICA_URL, USER, PASS)
        
        for i, cedula in enumerate(cedulas):
            print(f"\n--- Procesando cédula: {cedula} ({i+1}/{len(cedulas)}) ---")
            
            # Siempre empezamos desde la página de encuentros para una búsqueda limpia
            ir_a_encuentros(driver, FASTCLINICA_URL)
            
            buscar_paciente(driver, cedula)
            
            html_historia, html_plan = capturar_html_pestanas(driver)
            datos = extraer_datos(html_historia, html_plan, cedula)
            pacientes.append(datos)
            
    except Exception as e:
        print(f"\n!!! Error durante la ejecución: {e} !!!")
        # Guarda una captura de pantalla y el HTML para depuración
        timestamp = int(time.time())
        screenshot_path = f"error_screenshot_{timestamp}.png"
        html_path = f"error_page_{timestamp}.html"
        driver.save_screenshot(screenshot_path)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"Screenshot guardado en: {screenshot_path}")
        print(f"HTML de la página guardado en: {html_path}")

    finally:
        driver.quit()
        print("\nDriver cerrado.")

    print("\n--- Resultados Finales ---")
    for paciente in pacientes:
        print(paciente)


if __name__ == "__main__":
    main()