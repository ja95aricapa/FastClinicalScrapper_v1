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
import json # Importar json para una mejor visualización de la salida

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
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1200")
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

def buscar_paciente(driver, cedula):
    """Busca un paciente por cédula en la barra de búsqueda GLOBAL y hace clic en el resultado."""
    wait = WebDriverWait(driver, 15)
    print(f"Buscando al paciente con cédula: {cedula}...")
    search_input = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@id='globalSearchInput']")))
    search_input.clear()
    search_input.send_keys(cedula)
    print(f"Cédula '{cedula}' ingresada en el campo de búsqueda global.")
    time.sleep(1)
    resultado_selector = f"//div[contains(@class, 'filament-global-search-results-container')]//a[contains(., 'CC-{cedula}')]"
    print("Esperando resultado de la búsqueda...")
    resultado_link = wait.until(EC.element_to_be_clickable((By.XPATH, resultado_selector)))
    print("Resultado de búsqueda encontrado y clickeable.")
    resultado_link.click()
    wait.until(EC.presence_of_element_located((By.XPATH, "//button[contains(., 'Historia Clínica')] | //a[contains(., 'Historia Clínica')]")))
    print(f"Página del paciente con cédula {cedula} cargada.")

def capturar_html_pestanas(driver):
    """Navega por las pestañas del paciente y captura su contenido HTML."""
    wait = WebDriverWait(driver, 15)
    historia_tab_selector = "//button[contains(., 'Historia Clínica')] | //a[contains(., 'Historia Clínica')]"
    plan_tab_selector = "//button[contains(., 'Plan de manejo')] | //a[contains(., 'Plan de manejo')]"

    print("Cambiando a la pestaña 'Historia Clínica'...")
    historia_tab = wait.until(EC.element_to_be_clickable((By.XPATH, historia_tab_selector)))
    historia_tab.click()
    time.sleep(2)
    html_historia = driver.page_source

    print("Cambiando a la pestaña 'Plan de Manejo'...")
    plan_tab = wait.until(EC.element_to_be_clickable((By.XPATH, plan_tab_selector)))
    plan_tab.click()
    time.sleep(2)
    html_plan = driver.page_source
    
    print("HTML de pestañas 'Historia Clínica' y 'Plan de Manejo' capturado.")
    return html_historia, html_plan


# --- FUNCIÓN DE EXTRACCIÓN DE DATOS MEJORADA ---
def extraer_datos(html_historia, html_plan, cedula):
    """Extrae datos de las tablas de Historia Clínica y Plan de Manejo."""
    print(f"Iniciando extracción de datos para cédula: {cedula}")

    # --- Extracción de datos generales ---
    soup_general = BeautifulSoup(html_historia, "html.parser")
    nombre_completo = "No encontrado"
    h1_el = soup_general.find('h1', class_='filament-header-heading')
    if h1_el:
        # Limpia el texto para obtener solo el nombre
        nombre_completo = h1_el.get_text(strip=True).replace(f"Editar CC-{cedula}", "").strip()

    datos = {
        "CEDULA": cedula,
        "NOMBRE_PACIENTE": nombre_completo,
        "historia_clinica": [],
        "plan_de_manejo": []
    }

    # --- Extracción de la pestaña "Historia Clínica" ---
    soup_h = BeautifulSoup(html_historia, "html.parser")
    encuentros_header = soup_h.find('h2', class_='filament-tables-header-heading', string=lambda t: 'Encuentros' in t)
    if encuentros_header:
        encuentros_table = encuentros_header.find_parent('div', class_='filament-tables-header').find_next_sibling('div', class_='filament-tables-table-container')
        if encuentros_table:
            filas = encuentros_table.find('tbody').find_all('tr', class_='filament-tables-row')
            print(f"Encontrados {len(filas)} encuentros en Historia Clínica.")
            for fila in filas:
                columnas = fila.find_all('div', class_='filament-tables-text-column')
                if len(columnas) >= 4:
                    encuentro = {
                        "actividad": columnas[0].get_text(strip=True),
                        "sub_actividad": columnas[1].get_text(strip=True),
                        "profesional": columnas[2].get_text(strip=True),
                        "fecha_hora": columnas[3].get_text(strip=True),
                        "nota": columnas[4].get_text(strip=True) if len(columnas) > 4 else ""
                    }
                    datos["historia_clinica"].append(encuentro)

    # --- Extracción de la pestaña "Plan de Manejo" ---
    soup_p = BeautifulSoup(html_plan, "html.parser")
    ordenes_header = soup_p.find('h2', class_='filament-tables-header-heading', string=lambda t: 'Ordenes De Servicio' in t)
    if ordenes_header:
        ordenes_table = ordenes_header.find_parent('div', class_='filament-tables-header').find_next_sibling('div', class_='filament-tables-table-container')
        if ordenes_table:
            filas = ordenes_table.find('tbody').find_all('tr', class_='filament-tables-row')
            print(f"Encontradas {len(filas)} órdenes en Plan de Manejo.")
            for fila in filas:
                columnas = fila.find_all('td', class_='filament-tables-cell')
                if len(columnas) >= 8: # Hay 1 celda de checkbox + 7 de datos + 1 de acciones
                    orden = {
                        "fecha": columnas[1].get_text(strip=True),
                        "codigo": columnas[2].get_text(strip=True),
                        "servicio": columnas[3].get_text(strip=True),
                        "estado": columnas[4].get_text(strip=True),
                        "prestador": columnas[5].get_text(strip=True),
                        "activo_desde": columnas[6].get_text(strip=True),
                        "activo_hasta": columnas[7].get_text(strip=True)
                    }
                    datos["plan_de_manejo"].append(orden)
    
    print(f"Extracción finalizada para el paciente {nombre_completo}.")
    return datos

def main():
    FASTCLINICA_URL, USER, PASS = get_env_vars()
    if not all([FASTCLINICA_URL, USER, PASS]):
        print("Error: Asegúrate de que las variables de entorno FASTCLINICA_URL, USER y PASS están definidas en el archivo .env")
        return

    cedulas = ["1107088958"]
    pacientes = []

    driver = init_driver()
    print("Iniciando scraper...")
    try:
        login(driver, FASTCLINICA_URL, USER, PASS)
        
        for i, cedula in enumerate(cedulas):
            print(f"\n--- Procesando cédula: {cedula} ({i+1}/{len(cedulas)}) ---")
            ir_a_encuentros(driver, FASTCLINICA_URL)
            buscar_paciente(driver, cedula)
            html_historia, html_plan = capturar_html_pestanas(driver)
            datos = extraer_datos(html_historia, html_plan, cedula)
            pacientes.append(datos)
            
    except Exception as e:
        print(f"\n!!! Error durante la ejecución: {e} !!!")
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
    # Usar json.dumps para una salida más legible
    print(json.dumps(pacientes, indent=4, ensure_ascii=False))

if __name__ == "__main__":
    main()