# -*- coding: utf-8 -*-
"""
Script para extraer y resumir información clínica de pacientes desde la plataforma FastClínica.
Versión optimizada con procesamiento en paralelo para resúmenes y medición de rendimiento.

Arquitectura:
1. Carga de configuración y del modelo de IA.
2. Fase de Extracción (Scraping Secuencial):
   - Inicia un único WebDriver de Selenium.
   - Itera sobre una lista de cédulas de pacientes.
   - Para cada paciente, extrae la información de la historia clínica y el plan de manejo.
   - Almacena los datos brutos.
   - Cierra el WebDriver.
3. Fase de Procesamiento (Resumen en Paralelo):
   - Utiliza un ThreadPoolExecutor para procesar a todos los pacientes simultáneamente.
   - Cada hilo de trabajo pre-procesa, limpia y genera el resumen para un paciente.
   - Añade el resumen a los datos del paciente.
4. Almacenamiento:
   - Guarda los datos completos y enriquecidos en un archivo JSON.
"""

# ==============================================================================
# 1. IMPORTACIONES
# ==============================================================================
import os
import time
import json
from typing import List, Dict, Any, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# Carga de variables de entorno
from dotenv import load_dotenv

# Web Scraping con Selenium
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
)

# Parsing de HTML
from bs4 import BeautifulSoup

# Modelo de IA con Transformers y PyTorch
import torch
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    PreTrainedTokenizer,
    PreTrainedModel,
)

# ==============================================================================
# 2. CONFIGURACIÓN Y FUNCIONES DE INICIALIZACIÓN
# ==============================================================================


def get_env_vars() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Carga las variables de entorno desde el archivo .env y las retorna.

    Returns:
        Tuple[Optional[str], Optional[str], Optional[str]]: Una tupla conteniendo la URL,
        el usuario y la contraseña. Si alguna no está definida, será None.
    """
    print("-> Cargando variables de entorno desde el archivo .env...")
    load_dotenv()
    url = os.getenv("FASTCLINICA_URL")
    user = os.getenv("FASTCLINICA_USER")
    password = os.getenv("FASTCLINICA_PASS")
    return url, user, password


def init_driver() -> webdriver.Chrome:
    """
    Inicializa y configura el WebDriver de Selenium para Chrome.

    Returns:
        webdriver.Chrome: La instancia del driver configurada.
    """
    print("-> Inicializando el WebDriver de Selenium...")
    opts = ChromeOptions()
    # Descomentar para ejecutar en modo "headless" (sin interfaz gráfica)
    # opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1200")
    opts.add_argument("--log-level=3")
    opts.add_experimental_option("excludeSwitches", ["enable-logging"])

    service = ChromeService()
    driver = webdriver.Chrome(service=service, options=opts)
    print("-> WebDriver inicializado correctamente.")
    return driver


def cargar_modelo_ia(model_id: str) -> Tuple[PreTrainedModel, PreTrainedTokenizer]:
    """
    Carga el modelo y el tokenizador de IA desde Hugging Face.

    Args:
        model_id (str): El identificador del modelo en el Hub de Hugging Face.

    Returns:
        Tuple[PreTrainedModel, PreTrainedTokenizer]: Una tupla con el modelo y el tokenizador cargados.
    """
    print(f"-> Cargando modelo de IA: '{model_id}'...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"-> Usando dispositivo: {device.upper()}")

    tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_id, trust_remote_code=True, torch_dtype=torch.bfloat16
    )

    model.eval()
    if device == "cuda":
        model.to(device)

    print("-> Modelo de IA cargado y listo.")
    return model, tokenizer


# ==============================================================================
# 3. FUNCIONES DE EXTRACCIÓN (SCRAPING)
# ==============================================================================


def login(driver: webdriver.Chrome, url: str, user: str, password: str) -> None:
    """
    Realiza el proceso de login en la plataforma FastClínica.

    Args:
        driver (webdriver.Chrome): La instancia del WebDriver.
        url (str): La URL base de la plataforma.
        user (str): El email de usuario.
        password (str): La contraseña.
    """
    print("-> Navegando a la página de login...")
    driver.get(f"{url}/login")
    wait = WebDriverWait(driver, 20)
    print("-> Ingresando credenciales...")
    email_field = wait.until(EC.presence_of_element_located((By.ID, "email")))
    email_field.send_keys(user)
    driver.find_element(by=By.ID, value="password").send_keys(password)
    submit_button = wait.until(
        EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']"))
    )
    submit_button.click()
    wait.until(
        EC.presence_of_element_located(
            (By.XPATH, "//h1[contains(text(), 'Escritorio')]")
        )
    )
    print("-> Login exitoso.")


def buscar_paciente(driver: webdriver.Chrome, cedula: str) -> None:
    """
    Busca un paciente por su cédula usando la barra de búsqueda global.

    Args:
        driver (webdriver.Chrome): La instancia del WebDriver.
        cedula (str): El número de cédula del paciente a buscar.
    """
    wait = WebDriverWait(driver, 20)
    print(f"-> Buscando al paciente con cédula: {cedula}...")
    search_input = wait.until(
        EC.presence_of_element_located((By.XPATH, "//input[@id='globalSearchInput']"))
    )
    search_input.clear()
    search_input.send_keys(cedula)
    # Espera explícita para que la búsqueda asíncrona se complete
    time.sleep(2)
    resultado_selector = f"//div[contains(@class, 'filament-global-search-results-container')]//a[contains(., 'CC-{cedula}')]"
    resultado_link = wait.until(
        EC.element_to_be_clickable((By.XPATH, resultado_selector))
    )
    print("-> Resultado de búsqueda encontrado. Navegando a la página del paciente...")
    resultado_link.click()
    wait.until(EC.url_contains("/patients/"))
    print(f"-> Página del paciente {cedula} cargada correctamente.")


def extraer_secciones_modal(modal_html: str) -> Dict[str, Dict[str, str]]:
    """
    Parsea el HTML de un modal de Filament para extraer datos de sus secciones.

    Args:
        modal_html (str): El contenido HTML del elemento modal.

    Returns:
        Dict[str, Dict[str, str]]: Un diccionario donde cada clave es el título
        de una sección y su valor es otro diccionario con los pares campo-valor.
    """
    soup = BeautifulSoup(modal_html, "html.parser")
    secciones_data = {}
    secciones = soup.find_all("div", class_="filament-forms-section-component")
    for seccion in secciones:
        header = seccion.find("h3", class_="pointer-events-none")
        if not header:
            continue
        titulo_seccion = header.get_text(strip=True)
        secciones_data[titulo_seccion] = {}
        campos = seccion.find_all("div", class_="filament-forms-field-wrapper")
        for campo in campos:
            label_el = campo.find("label")
            valor_el = campo.find("div", class_="filament-forms-placeholder-component")
            if label_el and valor_el:
                label = label_el.get_text(strip=True)
                # Limpia y normaliza espacios en el valor extraído
                valor = " ".join(valor_el.get_text(separator=" ", strip=True).split())
                secciones_data[titulo_seccion][label] = (
                    valor if valor else "No especificado"
                )
    return secciones_data


def capturar_y_procesar_historia(
    driver: webdriver.Chrome, datos_paciente: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Navega a la pestaña 'Historia Clínica', extrae datos de los encuentros médicos
    y de químico farmacéutico, y los añade al diccionario del paciente.
    Ahora maneja de forma segura los encuentros que no tienen un botón 'Vista'.

    Args:
        driver (webdriver.Chrome): La instancia del WebDriver.
        datos_paciente (Dict[str, Any]): El diccionario que acumula los datos del paciente.

    Returns:
        Dict[str, Any]: El diccionario del paciente actualizado con los datos de la historia.
    """
    wait = WebDriverWait(driver, 20)
    print("  -- Accediendo a la pestaña 'Historia Clínica'...")
    historia_tab_selector = "//button[contains(., 'Historia Clínica')] | //a[contains(., 'Historia Clínica')]"
    historia_tab = wait.until(
        EC.element_to_be_clickable((By.XPATH, historia_tab_selector))
    )
    historia_tab.click()

    wait.until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR, "div.filament-tables-table-container")
        )
    )
    time.sleep(3)

    filas_selector = (By.CSS_SELECTOR, "div[wire\\:sortable] > div[wire\\:key]")
    try:
        filas_encuentros = wait.until(
            EC.presence_of_all_elements_located(filas_selector)
        )
        print(f"  -- Se encontraron {len(filas_encuentros)} encuentros en la historia.")
    except TimeoutException:
        print(
            "  -- ADVERTENCIA: No se encontraron encuentros. Omitiendo sección de historia."
        )
        return datos_paciente

    for i in range(len(filas_encuentros)):
        try:
            fila_actual = wait.until(
                EC.presence_of_all_elements_located(filas_selector)
            )[i]

            columnas = fila_actual.find_elements(
                By.CSS_SELECTOR, "div.filament-tables-text-column"
            )
            if len(columnas) < 4:
                continue

            sub_actividad = columnas[1].text.strip().upper()
            es_medico = "MEDICO" in sub_actividad
            es_quimico = (
                "FARMACOTERAPÉUTICO" in sub_actividad or "QUIMICO" in sub_actividad
            )

            if es_medico or es_quimico:
                # ---- MODIFICACIÓN CLAVE ----
                # Usamos find_elements (plural) para verificar la existencia del botón.
                # Esto devuelve una lista. Si la lista está vacía, el botón no existe.
                vista_buttons = fila_actual.find_elements(
                    By.XPATH, ".//button[contains(., 'Vista')]"
                )

                if not vista_buttons:
                    # Si la lista está vacía, el botón 'Vista' no existe. Omitimos este encuentro.
                    print(
                        f"    -> ADVERTENCIA: El encuentro '{columnas[1].text.strip()}' no tiene botón 'Vista'. Omitiendo."
                    )
                    continue  # Pasa al siguiente encuentro en el bucle 'for'

                # Si llegamos aquí, el botón sí existe y podemos continuar.
                vista_button = vista_buttons[
                    0
                ]  # Tomamos el primer (y único) botón de la lista

                tipo_profesional = "medico" if es_medico else "quimico_farmaceutico"
                print(
                    f"    -> Procesando encuentro de '{tipo_profesional.replace('_', ' ')}'..."
                )

                driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});", vista_button
                )
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", vista_button)

                modal_selector = (
                    By.XPATH,
                    "//div[contains(@class, 'filament-modal-window') and .//h2[contains(text(), 'Vista de Encuentro')]]",
                )
                modal_element = wait.until(
                    EC.visibility_of_element_located(modal_selector)
                )

                modal_html = modal_element.get_attribute("innerHTML")
                datos_del_modal = extraer_secciones_modal(modal_html=modal_html)

                datos_encuentro = {
                    "actividad_encuentro": columnas[0].text.strip(),
                    "sub_actividad_encuentro": columnas[1].text.strip(),
                    "profesional_encuentro": columnas[2].text.strip(),
                    "fecha_hora_encuentro": columnas[3].text.strip(),
                    "datos_del_modal": datos_del_modal,
                }

                datos_paciente["historia_clinica"][tipo_profesional].append(
                    datos_encuentro
                )

                cerrar_button = modal_element.find_element(
                    By.XPATH, ".//button[span[contains(text(), 'Cerrar')]]"
                )
                cerrar_button.click()
                wait.until(EC.invisibility_of_element_located(modal_selector))
                time.sleep(1)

        except Exception as e:
            print(
                f"    -> ERROR al procesar una fila de encuentro: {type(e).__name__}. Continuando..."
            )
            try:
                emergency_close = driver.find_element(
                    By.XPATH, "//button[span[contains(text(), 'Cerrar')]]"
                )
                if emergency_close.is_displayed():
                    emergency_close.click()
            except:
                pass
            continue

    return datos_paciente


def procesar_plan_de_manejo(
    driver: webdriver.Chrome, datos_paciente: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Navega a la pestaña 'Plan de Manejo', extrae órdenes y fórmulas, y los
    añade al diccionario del paciente.
    Ahora usa un clic de JavaScript para evitar errores de intercepción.

    Args:
        driver (webdriver.Chrome): La instancia del WebDriver.
        datos_paciente (Dict[str, Any]): El diccionario que acumula los datos del paciente.

    Returns:
        Dict[str, Any]: El diccionario del paciente actualizado con el plan de manejo.
    """
    wait = WebDriverWait(driver, 20)
    print("  -- Accediendo a la pestaña 'Plan de Manejo'...")
    plan_tab_selector = (
        "//button[contains(., 'Plan de manejo')] | //a[contains(., 'Plan de manejo')]"
    )
    plan_tab = wait.until(EC.element_to_be_clickable((By.XPATH, plan_tab_selector)))

    # ---- MODIFICACIÓN CLAVE ----
    # En lugar de plan_tab.click(), usamos un clic de JavaScript.
    # Esto evita el error "ElementClickInterceptedException" si otro elemento
    # (como un encabezado fijo) está cubriendo el botón.
    driver.execute_script("arguments[0].click();", plan_tab)

    time.sleep(3)
    soup_p = BeautifulSoup(driver.page_source, "html.parser")
    contenedores = soup_p.find_all("div", class_="filament-tables-container")
    for container in contenedores:
        header_text = container.find(
            "h2", class_="filament-tables-header-heading"
        ).get_text(strip=True)
        tabla = container.find("table", class_="filament-tables-table")
        if not (tabla and tabla.find("tbody")):
            continue
        tbody = tabla.find("tbody")
        if "Ordenes De Servicio" in header_text:
            filas = tbody.find_all("tr", class_="filament-tables-row")
            print(f"  -- Encontradas {len(filas)} órdenes de servicio.")
            for fila in filas:
                cols = fila.find_all("td", class_="filament-tables-cell")
                if len(cols) >= 7:
                    datos_paciente["plan_de_manejo"]["ordenes_de_servicio"].append(
                        {
                            "fecha": cols[0].get_text(strip=True),
                            "codigo": cols[1].get_text(strip=True),
                            "servicio": cols[2].get_text(strip=True),
                            "estado": cols[3].get_text(strip=True),
                            "prestador": cols[4].get_text(strip=True),
                            "activo_desde": cols[5].get_text(strip=True),
                            "activo_hasta": cols[6].get_text(strip=True),
                        }
                    )
        elif "Fórmulas Médicas" in header_text:
            filas = tbody.find_all("tr", class_="filament-tables-row")
            print(f"  -- Encontradas {len(filas)} fórmulas médicas.")
            for fila in filas:
                cols = fila.find_all("td", class_="filament-tables-cell")
                if len(cols) < 3:
                    continue
                tabla_meds = cols[1].find("table")
                if not (tabla_meds and tabla_meds.find("tbody")):
                    continue
                for med_fila in tabla_meds.find("tbody").find_all("tr"):
                    celdas_med = med_fila.find_all("td")
                    if len(celdas_med) == 2:
                        datos_paciente["plan_de_manejo"]["formulas_medicas"].append(
                            {
                                "fecha": cols[0].get_text(strip=True),
                                "medicamento": celdas_med[0].get_text(strip=True),
                                "cantidad": celdas_med[1].get_text(strip=True),
                                "estado": cols[2].get_text(strip=True),
                            }
                        )
    return datos_paciente


# ==============================================================================
# 4. FUNCIONES DE PROCESAMIENTO CON IA
# ==============================================================================


def preparar_datos_para_resumen(datos_paciente: Dict[str, Any]) -> Dict[str, Any]:
    """
    Crea un diccionario simplificado con los datos más relevantes y limpios
    para enviar al LLM, evitando sobrecargar el prompt con información redundante.

    Args:
        datos_paciente (Dict[str, Any]): El diccionario completo con los datos extraídos.

    Returns:
        Dict[str, Any]: Un diccionario limpio y conciso, optimizado para el modelo de IA.
    """
    datos_clave = {
        "nombre_paciente": datos_paciente.get("NOMBRE_PACIENTE"),
        "diagnostico_principal": None,
        "datos_relevantes_ultima_consulta_medica": {},
        "concepto_clave_farmaceutico": {},
        "tratamiento_actual_formulado": [],
    }
    # Extraer del encuentro médico más reciente
    if datos_paciente["historia_clinica"]["medico"]:
        ultimo_med = sorted(
            datos_paciente["historia_clinica"]["medico"],
            key=lambda x: x["fecha_hora_encuentro"],
            reverse=True,
        )[0]
        modal = ultimo_med.get("datos_del_modal", {})
        datos_clave["diagnostico_principal"] = modal.get(
            "Antecedentes Médicos", {}
        ).get("Patológicos")
        datos_clave["datos_relevantes_ultima_consulta_medica"] = {
            "fecha": ultimo_med.get("fecha_hora_encuentro"),
            "resumen_medico_del_dia": modal.get("Resumen e Intervenciones", {}).get(
                "Acciones"
            ),
            "enfermedad_actual_y_labs": modal.get("Enfermedad Actual", {}).get(
                "Enfermedad Actual"
            ),
        }
    # Extraer y limpiar el concepto del químico farmacéutico más reciente
    if datos_paciente["historia_clinica"]["quimico_farmaceutico"]:
        ultimo_qf = sorted(
            datos_paciente["historia_clinica"]["quimico_farmaceutico"],
            key=lambda x: x["fecha_hora_encuentro"],
            reverse=True,
        )[0]
        modal_qf = ultimo_qf.get("datos_del_modal", {})
        concepto_completo = modal_qf.get("Seguimiento Farmacoterapéutico", {}).get(
            "Descripción de la intervención", ""
        )
        concepto_final = (
            concepto_completo.split("CONCEPTO QF:")[-1].strip()
            if "CONCEPTO QF:" in concepto_completo
            else ""
        )
        datos_clave["concepto_clave_farmaceutico"] = {
            "fecha": ultimo_qf.get("fecha_hora_encuentro"),
            "adherencia": modal_qf.get("Test SMAQ", {}).get(
                "Resultado de Adherencia Cualitativo"
            ),
            "resumen_farmaceutico": concepto_final,
        }
    # Extraer tratamiento actual
    if datos_paciente["plan_de_manejo"]["formulas_medicas"]:
        medicamentos = [
            f["medicamento"]
            for f in datos_paciente["plan_de_manejo"]["formulas_medicas"]
            if "PRESERVATIVO" not in f["medicamento"]
        ]
        # Los 3 últimos únicos
        datos_clave["tratamiento_actual_formulado"] = list(dict.fromkeys(medicamentos))[
            :3
        ]
    return datos_clave


def resumir_paciente(
    model: PreTrainedModel,
    tokenizer: PreTrainedTokenizer,
    datos_paciente: Dict[str, Any],
    max_chars: int = 500,
) -> Tuple[str, str]:
    """
    Genera un resumen clínico para un solo paciente. Esta función está diseñada
    para ser ejecutada en un hilo separado.

    Args:
        model (PreTrainedModel): El modelo de IA cargado.
        tokenizer (PreTrainedTokenizer): El tokenizador correspondiente.
        datos_paciente (Dict[str, Any]): El diccionario completo con los datos del paciente.
        max_chars (int): El número máximo de caracteres para el resumen final.

    Returns:
        Tuple[str, str]: Una tupla con la cédula del paciente y el resumen generado.
    """
    cedula = datos_paciente["CEDULA"]
    print(f"  -> [Hilo Inicia] Procesando resumen para paciente {cedula}...")

    # Iniciar cronómetro para este paciente específico
    start_time_paciente = time.monotonic()

    datos_clave = preparar_datos_para_resumen(datos_paciente=datos_paciente)
    datos_json = json.dumps(datos_clave, ensure_ascii=False, indent=2)
    prompt = (
        "### Instrucción:\n"
        "Eres un asistente médico experto. Analiza los siguientes datos clínicos clave de un paciente. "
        "Genera un resumen conciso y claro en español, de no más de 500 caracteres. "
        "Enfócate en el diagnóstico principal, el tratamiento actual, los resultados recientes más importantes (como Carga Viral y CD4 si los encuentras) y la adherencia del paciente.\n\n"
        "### Datos Clave del Paciente:\n"
        f"{datos_json}\n\n"
        "### Resumen Médico Conciso:"
    )
    inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=3072)
    if torch.cuda.is_available():
        inputs = {k: v.to("cuda") for k, v in inputs.items()}
    prompt_len = inputs["input_ids"].shape[1]
    out = model.generate(
        **inputs,
        max_new_tokens=200,
        do_sample=False,
        num_beams=4,
        early_stopping=True,
        eos_token_id=tokenizer.eos_token_id,
        pad_token_id=tokenizer.pad_token_id,
    )
    generated_ids = out[0][prompt_len:]
    resumen = tokenizer.decode(generated_ids, skip_special_tokens=True).strip()

    # Detener cronómetro y reportar
    end_time_paciente = time.monotonic()
    duration_paciente = end_time_paciente - start_time_paciente
    print(
        f"  -> [Hilo Finaliza] Resumen para {cedula} generado en {duration_paciente:.2f} segundos."
    )

    return cedula, resumen[:max_chars]


# ==============================================================================
# 5. FUNCIÓN PRINCIPAL DE ORQUESTACIÓN
# ==============================================================================


def main(cedulas_a_procesar: List[str]) -> None:
    """
    Orquesta todo el proceso de extracción y resumen de datos de pacientes.

    Args:
        cedulas_a_procesar (List[str]): Una lista de las cédulas a procesar.
    """
    start_total_time = time.monotonic()
    print("======================================================")
    print("INICIO DEL PROCESO DE EXTRACCIÓN Y RESUMEN DE PACIENTES")
    print("======================================================")
    FASTCLINICA_URL, USER, PASS = get_env_vars()
    if not all([FASTCLINICA_URL, USER, PASS]):
        print(
            "\n!!! ERROR CRÍTICO: Asegúrate de que las variables de entorno estén definidas en .env !!!"
        )
        return

    modelo_ia, tokenizador_ia = cargar_modelo_ia(
        model_id="deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B"
    )

    # --- FASE 1: EXTRACCIÓN DE DATOS (SECUENCIAL) ---
    print("\n--- FASE 1: EXTRACCIÓN DE DATOS ---")
    start_scraping_time = time.monotonic()
    driver = init_driver()
    pacientes_extraidos = []
    try:
        login(driver=driver, url=FASTCLINICA_URL, user=USER, password=PASS)
        for i, cedula in enumerate(cedulas_a_procesar):
            print(
                f"\n--- Procesando paciente {i+1}/{len(cedulas_a_procesar)} (Cédula: {cedula}) ---"
            )
            buscar_paciente(driver=driver, cedula=cedula)
            # Extraer nombre completo del paciente
            soup_general = BeautifulSoup(driver.page_source, "html.parser")
            h1_el = soup_general.find("h1", class_="filament-header-heading")
            nombre_completo = (
                h1_el.get_text(strip=True).replace(f"Editar CC-{cedula}", "").strip()
                if h1_el
                else "No encontrado"
            )
            # Inicializar estructura de datos para este paciente
            datos_paciente = {
                "CEDULA": cedula,
                "NOMBRE_PACIENTE": nombre_completo,
                "historia_clinica": {"medico": [], "quimico_farmaceutico": []},
                "plan_de_manejo": {"ordenes_de_servicio": [], "formulas_medicas": []},
            }
            datos_paciente = capturar_y_procesar_historia(
                driver=driver, datos_paciente=datos_paciente
            )
            datos_paciente = procesar_plan_de_manejo(
                driver=driver, datos_paciente=datos_paciente
            )
            pacientes_extraidos.append(datos_paciente)
            print(f"--- Finalizada la extracción para el paciente {cedula}. ---")

            # Si no es el último paciente de la lista, vuelve al escritorio para reiniciar el estado.
            # Esto previene errores de estado viciado en aplicaciones SPA.
            if i < len(cedulas_a_procesar) - 1:
                print(
                    "\n-> Volviendo al escritorio para reiniciar el estado antes del siguiente paciente..."
                )
                driver.get(f"{FASTCLINICA_URL}")
                # Esperamos a que el encabezado del escritorio esté visible para confirmar la navegación.
                wait = WebDriverWait(driver, 20)
                wait.until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//h1[contains(text(), 'Escritorio')]")
                    )
                )
                print("-> Estado reiniciado en el escritorio.")

    except Exception as e:
        print(f"\n!!! ERROR CRÍTICO DURANTE EL SCRAPING: {type(e).__name__} - {e} !!!")
        timestamp = int(time.time())
        screenshot_path = f"error_screenshot_{timestamp}.png"
        driver.save_screenshot(screenshot_path)
        print(f"-> Screenshot de emergencia guardado en: {screenshot_path}")
    finally:
        # Asegurarse de que el driver se cierra siempre al final de la extracción
        if "driver" in locals() and driver:
            driver.quit()
            print("\n-> WebDriver cerrado de forma segura.")

    end_scraping_time = time.monotonic()
    duration_scraping = end_scraping_time - start_scraping_time
    print(
        f"\n--- FIN FASE 1: Tiempo total de extracción: {duration_scraping:.2f} segundos ---"
    )

    # --- FASE 2: RESUMEN CON IA (EN PARALELO) ---
    if not pacientes_extraidos:
        print("\nNo se extrajeron datos de ningún paciente. Finalizando proceso.")
        return

    print("\n\n--- FASE 2: RESUMEN CON INTELIGENCIA ARTIFICIAL (EN PARALELO) ---")
    start_summarization_time = time.monotonic()

    # Crear un mapa para poder actualizar los diccionarios originales
    pacientes_por_cedula = {p["CEDULA"]: p for p in pacientes_extraidos}

    with ThreadPoolExecutor(max_workers=4) as executor:  # Puedes ajustar max_workers
        # Enviar todas las tareas al pool de hilos
        future_to_cedula = {
            executor.submit(
                resumir_paciente, modelo_ia, tokenizador_ia, paciente_data
            ): paciente_data["CEDULA"]
            for paciente_data in pacientes_extraidos
        }

        # Procesar los resultados a medida que se completan
        for future in as_completed(future_to_cedula):
            cedula_original = future_to_cedula[future]
            try:
                # El resultado es una tupla (cedula, resumen)
                cedula_res, resumen_ia = future.result()
                # Actualizar el diccionario del paciente con el resumen
                pacientes_por_cedula[cedula_res]["resumen_rapido"] = resumen_ia
            except Exception as e:
                print(f"!!! ERROR en el hilo para la cédula {cedula_original}: {e} !!!")
                pacientes_por_cedula[cedula_original][
                    "resumen_rapido"
                ] = "Error al generar resumen en paralelo."

    end_summarization_time = time.monotonic()
    duration_summarization = end_summarization_time - start_summarization_time
    print(
        f"\n--- FIN FASE 2: Tiempo total de resumen en paralelo: {duration_summarization:.2f} segundos ---"
    )

    # --- FASE 3: ALMACENAMIENTO DE RESULTADOS ---
    print("\n\n--- FASE 3: ALMACENAMIENTO DE RESULTADOS ---")
    output_filename = "resultados_pacientes_completos.json"
    os.makedirs("examples", exist_ok=True)
    output_path = os.path.join("examples", output_filename)
    with open(output_path, "w", encoding="utf-8") as f:
        # Usamos los valores del diccionario actualizado, que es la lista original de diccionarios
        json.dump(list(pacientes_por_cedula.values()), f, ensure_ascii=False, indent=4)
    print(f"\nResultados finales guardados en: '{output_path}'")

    end_total_time = time.monotonic()
    duration_total = end_total_time - start_total_time
    print("======================================================")
    print(
        f"PROCESO COMPLETADO. TIEMPO TOTAL DE EJECUCIÓN: {duration_total:.2f} segundos"
    )
    print("======================================================")


# ==============================================================================
# 6. PUNTO DE ENTRADA DEL SCRIPT
# ==============================================================================
if __name__ == "__main__":
    lista_de_cedulas = [
        "1107088958",
        "32271898",
        "1026553146",
        "8168228",
        "1046903180",
    ]
    main(cedulas_a_procesar=lista_de_cedulas)
