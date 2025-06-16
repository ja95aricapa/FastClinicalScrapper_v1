import os
import time
import json
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
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
    # Descomenta la siguiente línea para ejecutar en modo headless
    # opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1200")
    service = Service()
    return webdriver.Chrome(service=service, options=opts)

def login(driver, url, user, password):
    """Realiza el login en la plataforma."""
    driver.get(f"{url}/login")
    wait = WebDriverWait(driver, 20)
    print("Página de login cargada. Ingresando credenciales...")
    email_field = wait.until(EC.presence_of_element_located((By.ID, "email")))
    email_field.send_keys(user)
    driver.find_element(By.ID, "password").send_keys(password)
    submit_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']")))
    submit_button.click()
    wait.until(EC.presence_of_element_located((By.XPATH, "//h1[contains(text(), 'Escritorio')]")))
    print("Login exitoso. Redirigido al Escritorio.")

def buscar_paciente(driver, cedula):
    """Busca un paciente por cédula en la barra de búsqueda GLOBAL y hace clic en el resultado."""
    wait = WebDriverWait(driver, 20)
    print(f"Buscando al paciente con cédula: {cedula}...")
    search_input = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@id='globalSearchInput']")))
    search_input.clear()
    search_input.send_keys(cedula)
    print(f"Cédula '{cedula}' ingresada en el campo de búsqueda global.")
    time.sleep(2) # Espera explícita para que aparezcan los resultados
    resultado_selector = f"//div[contains(@class, 'filament-global-search-results-container')]//a[contains(., 'CC-{cedula}')]"
    print("Esperando resultado de la búsqueda...")
    resultado_link = wait.until(EC.element_to_be_clickable((By.XPATH, resultado_selector)))
    print("Resultado de búsqueda encontrado y clickeable.")
    resultado_link.click()
    wait.until(EC.url_contains('/patients/'))
    print(f"Página del paciente con cédula {cedula} cargada.")

def extraer_secciones_modal(modal_html):
    """Función genérica para extraer datos de secciones en un modal de Filament."""
    soup = BeautifulSoup(modal_html, "html.parser")
    secciones_data = {}
    
    # Busca todas las secciones dentro del modal
    secciones = soup.find_all('div', class_='filament-forms-section-component')
    for seccion in secciones:
        header = seccion.find('h3', class_='pointer-events-none')
        if not header:
            continue
            
        titulo_seccion = header.get_text(strip=True)
        secciones_data[titulo_seccion] = {}
        
        # Busca todos los campos (label y valor) dentro de cada sección
        campos = seccion.find_all('div', class_='filament-forms-field-wrapper')
        for campo in campos:
            label_el = campo.find('label')
            valor_el = campo.find('div', class_='filament-forms-placeholder-component')
            
            if label_el and valor_el:
                label = label_el.get_text(strip=True)
                valor = ' '.join(valor_el.get_text(separator=' ', strip=True).split()) # Limpia y une el texto
                secciones_data[titulo_seccion][label] = valor if valor else "No especificado"

    return secciones_data

def capturar_y_procesar_historia(driver, datos_paciente):
    """
    Navega a la pestaña de Historia Clínica, identifica encuentros de interés,
    abre sus modales, extrae los datos y los añade al diccionario del paciente.
    """
    wait = WebDriverWait(driver, 20)
    print("Cambiando a la pestaña 'Historia Clínica'...")
    historia_tab_selector = "//button[contains(., 'Historia Clínica')] | //a[contains(., 'Historia Clínica')]"
    historia_tab = wait.until(EC.element_to_be_clickable((By.XPATH, historia_tab_selector)))
    historia_tab.click()
    
    encuentros_table_container_selector = (By.CSS_SELECTOR, "div.filament-tables-table-container")
    wait.until(EC.presence_of_element_located(encuentros_table_container_selector))
    time.sleep(3)

    filas_selector = (By.CSS_SELECTOR, "div[wire\\:sortable] > div[wire\\:key]")
    
    try:
        filas_encuentros = wait.until(EC.presence_of_all_elements_located(filas_selector))
        print(f"Se encontraron {len(filas_encuentros)} encuentros en total.")
    except TimeoutException:
        print("No se encontraron encuentros en la pestaña de Historia Clínica. Omitiendo.")
        return datos_paciente

    for i in range(len(filas_encuentros)):
        try:
            fila_actual = wait.until(EC.presence_of_all_elements_located(filas_selector))[i]
            
            columnas = fila_actual.find_elements(By.CSS_SELECTOR, "div.filament-tables-text-column")
            if len(columnas) < 4: continue

            sub_actividad = columnas[1].text.strip().upper()
            es_medico = "MEDICO" in sub_actividad
            es_quimico = "FARMACOTERAPÉUTICO" in sub_actividad or "QUIMICO" in sub_actividad

            if es_medico or es_quimico:
                tipo_profesional = "medico" if es_medico else "quimico_farmaceutico"
                print(f"Procesando encuentro de '{tipo_profesional.replace('_', ' ')}': {columnas[1].text.strip()}")

                datos_encuentro = {
                    "actividad_encuentro": columnas[0].text.strip(),
                    "sub_actividad_encuentro": columnas[1].text.strip(),
                    "profesional_encuentro": columnas[2].text.strip(),
                    "fecha_hora_encuentro": columnas[3].text.strip(),
                    "datos_del_modal": {}
                }
                
                vista_button = fila_actual.find_element(By.XPATH, ".//button[contains(., 'Vista')]")
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", vista_button)
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", vista_button)
                
                # ### <<< CAMBIO IMPORTANTE: Selector de modal específico >>>
                # Usamos un XPath que busca el modal correcto basándose en su título.
                modal_especifico_selector = (By.XPATH, "//div[contains(@class, 'filament-modal-window') and .//h2[contains(text(), 'Vista de Encuentro')]]")
                
                # Esperamos a que ese modal específico sea visible
                wait.until(EC.visibility_of_element_located(modal_especifico_selector))
                print("   -> Modal 'Vista de Encuentro' detectado.")

                # También es buena práctica esperar por el contenido interno para asegurar la carga completa
                modal_content_selector = (By.CSS_SELECTOR, "div.filament-forms-section-component")
                wait.until(EC.presence_of_element_located(modal_content_selector))
                print("   -> Contenido del modal cargado. Extrayendo HTML...")
                
                # ### <<< CAMBIO IMPORTANTE: Usamos el selector específico para capturar el elemento >>>
                modal_element = driver.find_element(*modal_especifico_selector)
                
                modal_html = modal_element.get_attribute('innerHTML')
                datos_encuentro["datos_del_modal"] = extraer_secciones_modal(modal_html)
                
                # Asegurarse de que la lista existe antes de añadir
                if tipo_profesional not in datos_paciente["historia_clinica"]:
                    datos_paciente["historia_clinica"][tipo_profesional] = []
                datos_paciente["historia_clinica"][tipo_profesional].append(datos_encuentro)

                cerrar_button = modal_element.find_element(By.XPATH, ".//button[span[contains(text(), 'Cerrar')]]")
                cerrar_button.click()
                wait.until(EC.invisibility_of_element_located(modal_especifico_selector))
                print("   -> Modal cerrado.")
                time.sleep(1)

        except Exception as e:
            print(f"Error procesando una fila de encuentro: {type(e).__name__} - {e}. Omitiendo y continuando...")
            try:
                # Intento de cierre de emergencia si el modal quedó abierto
                emergency_close_buttons = driver.find_elements(By.XPATH, "//button[span[contains(text(), 'Cerrar')]]")
                if emergency_close_buttons:
                    emergency_close_buttons[-1].click()
                    wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, "div.filament-modal-window")))
            except:
                pass 
            continue
    
    return datos_paciente

def procesar_plan_de_manejo(driver, datos_paciente):
    """Captura y procesa los datos de la pestaña 'Plan de Manejo'."""
    wait = WebDriverWait(driver, 20)
    print("Cambiando a la pestaña 'Plan de Manejo'...")
    plan_tab_selector = "//button[contains(., 'Plan de manejo')] | //a[contains(., 'Plan de manejo')]"
    plan_tab = wait.until(EC.element_to_be_clickable((By.XPATH, plan_tab_selector)))
    plan_tab.click()
    time.sleep(3)

    html_plan = driver.page_source
    soup_p = BeautifulSoup(html_plan, "html.parser")
    todos_los_contenedores_de_tablas = soup_p.find_all('div', class_='filament-tables-container')

    for container in todos_los_contenedores_de_tablas:
        header = container.find('h2', class_='filament-tables-header-heading')
        if not header: continue
        
        header_text = header.get_text(strip=True)
        
        if 'Ordenes De Servicio' in header_text:
            tabla = container.find('table', class_='filament-tables-table')
            if tabla and tabla.find('tbody'):
                filas_ordenes = tabla.find('tbody').find_all('tr', class_='filament-tables-row')
                print(f"Encontradas {len(filas_ordenes)} órdenes en Plan de Manejo.")
                for fila in filas_ordenes:
                    columnas = fila.find_all('td', class_='filament-tables-cell')
                    if len(columnas) >= 7:
                        datos_paciente["plan_de_manejo"]["ordenes_de_servicio"].append({
                            "fecha": columnas[0].get_text(strip=True), "codigo": columnas[1].get_text(strip=True),
                            "servicio": columnas[2].get_text(strip=True), "estado": columnas[3].get_text(strip=True),
                            "prestador": columnas[4].get_text(strip=True), "activo_desde": columnas[5].get_text(strip=True),
                            "activo_hasta": columnas[6].get_text(strip=True)
                        })

        elif 'Fórmulas Médicas' in header_text:
            tabla = container.find('table', class_='filament-tables-table')
            if tabla and tabla.find('tbody'):
                filas_formulas = tabla.find('tbody').find_all('tr', class_='filament-tables-row')
                print(f"Encontradas {len(filas_formulas)} entradas de fórmulas médicas.")
                for fila in filas_formulas:
                    columnas_principales = fila.find_all('td', class_='filament-tables-cell')
                    if len(columnas_principales) < 3: continue
                    fecha_formula = columnas_principales[0].get_text(strip=True)
                    estado_formula = columnas_principales[2].get_text(strip=True)
                    celda_medicamentos = columnas_principales[1]
                    tabla_interna = celda_medicamentos.find('table')
                    
                    if tabla_interna and tabla_interna.find('tbody'):
                        filas_medicamentos = tabla_interna.find('tbody').find_all('tr')
                        for med_fila in filas_medicamentos:
                            celdas_med = med_fila.find_all('td')
                            if len(celdas_med) == 2:
                                datos_paciente["plan_de_manejo"]["formulas_medicas"].append({
                                    "fecha": fecha_formula, "medicamento": celdas_med[0].get_text(strip=True),
                                    "cantidad": celdas_med[1].get_text(strip=True), "estado": estado_formula
                                })
    return datos_paciente


def main():
    FASTCLINICA_URL, USER, PASS = get_env_vars()
    if not all([FASTCLINICA_URL, USER, PASS]):
        print("Error: Asegúrate de que las variables de entorno están definidas en .env")
        return

    cedulas = ["1107088958"] # Puedes añadir más cédulas aquí
    pacientes = []

    driver = init_driver()
    print("Iniciando scraper...")
    try:
        login(driver, FASTCLINICA_URL, USER, PASS)
        
        for i, cedula in enumerate(cedulas):
            print(f"\n--- Procesando cédula: {cedula} ({i+1}/{len(cedulas)}) ---")
            buscar_paciente(driver, cedula)
            
            soup_general = BeautifulSoup(driver.page_source, "html.parser")
            nombre_completo = "No encontrado"
            h1_el = soup_general.find('h1', class_='filament-header-heading')
            if h1_el:
                nombre_completo = h1_el.get_text(strip=True).replace(f"Editar CC-{cedula}", "").strip()

            datos_paciente = {
                "CEDULA": cedula, "NOMBRE_PACIENTE": nombre_completo,
                "historia_clinica": {"medico": [], "quimico_farmaceutico": []},
                "plan_de_manejo": {"ordenes_de_servicio": [], "formulas_medicas": []},
            }

            datos_paciente = capturar_y_procesar_historia(driver, datos_paciente)
            datos_paciente = procesar_plan_de_manejo(driver, datos_paciente)
            pacientes.append(datos_paciente)
            
    except Exception as e:
        print(f"\n!!! Error durante la ejecución: {type(e).__name__} - {e} !!!")
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
    with open('examples/resultados_pacientes.json', 'w', encoding='utf-8') as f:
        json.dump(pacientes, f, ensure_ascii=False, indent=4)
    print("Resultados guardados en 'resultados_pacientes.json'")

if __name__ == "__main__":
    main()