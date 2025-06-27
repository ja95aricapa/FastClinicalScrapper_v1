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
import regex as re
import time
import json
from typing import List, Dict, Any, Tuple, Optional, Union
from concurrent.futures import ThreadPoolExecutor, as_completed
from docxtpl import DocxTemplate
from datetime import date

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

# aws
import boto3
from botocore.client import Config


# ==============================================================================
# 2. CONFIGURACIÓN Y FUNCIONES DE INICIALIZACIÓN
# ==============================================================================


def get_env_vars() -> Tuple[
    Optional[str],
    Optional[str],
    Optional[str],
    Optional[str],
    Optional[str],
    Optional[str],
    Optional[str],
    Optional[str],
]:
    """
    Carga las variables de entorno desde el archivo .env y las retorna.

    Returns:
        Tuple[Optional[str]]: Una tupla conteniendo la URL,
        el usuario, contraseña, etc. Si alguna no está definida, será None.
    """
    print("-> Cargando variables de entorno desde el archivo .env...")
    load_dotenv()
    url = os.getenv("FASTCLINICA_URL")
    user = os.getenv("FASTCLINICA_USER")
    password = os.getenv("FASTCLINICA_PASS")
    model_id = os.getenv("LOCAL_MODEL_ID")
    aws_key_id = os.getenv("AWS_KEY_ID")
    aws_secret_key = os.getenv("AWS_SECRET_KEY")
    aws_region = os.getenv("AWS_REGION")
    aws_bedrock_model_id = os.getenv("AWS_BEDROCK_MODEL_ID")
    return (
        url,
        user,
        password,
        model_id,
        aws_key_id,
        aws_secret_key,
        aws_region,
        aws_bedrock_model_id,
    )


def get_aws_service(
    service_name: str, service_type: str = "client", region: Union[str, None] = None
) -> Union[boto3.client, boto3.resource]:
    """
    Function to get an AWS service client or resource.

    Args:
        service_name (str): Name of the AWS service (e.g., 's3', 'ec2').
        service_type (str, optional): Type of AWS service ('client' or 'resource'). Defaults to 'client'.
        region (Union[str, None], optional): AWS region to use. Defaults to None, which will use 'us-east-1'.

    Raises:
        ValueError: If service_type is not 'client' or 'resource'.

    Returns:
        Union[boto3.client, boto3.resource]: An AWS service client or resource.
    """
    PROFILE_NAME = os.getenv("PROFILE_NAME")
    EXECUTION_ENVIRONMENT = os.getenv("EXECUTION_ENVIRONMENT")
    if service_type not in ["client", "resource"]:
        # Raise an error if the service_type is invalid
        raise ValueError("Invalid service type, must be 'client' or 'resource'.")

    # Create a boto3 session, using the PROFILE_NAME if in local environment
    session = (
        boto3.Session(profile_name=PROFILE_NAME)
        if EXECUTION_ENVIRONMENT == "LOCAL"
        else boto3.Session()
    )
    config = None

    # Configure specific clients with additional parameters
    if service_type == "client":
        if service_name == "s3":
            config = Config(signature_version="s3v4")
        if service_name == "batch":
            config = Config(
                retries={"max_attempts": 10, "mode": "standard"},
                max_pool_connections=50,  # Adjust this value as needed
            )

        # Create and return the service client
        client = session.client(
            service_name,
            region_name=region if region else "us-east-1",
            config=config,
        )
        return client
    elif service_type == "resource":
        # Create and return the service resource
        resource = session.resource(
            service_name,
            region_name=region if region else "us-east-1",
            config=config,
        )
        return resource


def init_driver() -> webdriver.Chrome:
    """
    Inicializa y configura el WebDriver de Selenium para Chrome.

    Returns:
        webdriver.Chrome: La instancia del driver configurada.
    """
    print("-> Inicializando el WebDriver de Selenium...")
    service = ChromeService(executable_path="utils/chromedriver")
    opts = ChromeOptions()
    # Descomentar para ejecutar en modo "headless" (sin interfaz gráfica)
    # opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1200")
    opts.add_argument("--log-level=3")
    opts.add_experimental_option("excludeSwitches", ["enable-logging"])

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
        titulo = header.get_text(strip=True)
        secciones_data[titulo] = {}
        campos = seccion.find_all("div", class_="filament-forms-field-wrapper")
        for campo in campos:
            label_el = campo.find("label")
            valor_el = campo.find("div", class_="filament-forms-placeholder-component")
            if not (label_el and valor_el):
                continue
            label = label_el.get_text(strip=True)
            valor = (
                " ".join(valor_el.get_text(separator=" ", strip=True).split())
                or "No especificado"
            )
            # Normalizar algunos labels comunes
            label_norm = label

            # Ejemplos de normalización:
            if label_norm in ["Fecha de diagnóstico", "Fecha diagnóstico"]:
                label_norm = "Fecha de diagnóstico"
            elif label_norm.lower().startswith("estadio clínico"):
                label_norm = "Estadio Clínico"
            elif "hábitos" in label_norm.lower():
                if "aliment" in label_norm.lower():
                    label_norm = "Hábitos Alimenticios"
                else:
                    label_norm = "Hábitos Toxicológicos"
            secciones_data[titulo][label_norm] = valor
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
        # claves adicionales para la QF:
        "concepto_qf": "",
        "narrativa_intervencion": "",
        "sugerencia_horarios": [],
        "informacion_general": "",
        "tipo_intervencion": "",
        "modalidad_intervencion": "",
    }
    # Extraer del encuentro médico más reciente
    if datos_paciente["historia_clinica"]["medico"]:
        ultimo_med = sorted(
            datos_paciente["historia_clinica"]["medico"],
            key=lambda x: x["fecha_hora_encuentro"],
            reverse=True,
        )[0]
        mod_med = ultimo_med.get("datos_del_modal", {})
        datos_clave.update(
            {
                "paciente_sexo": mod_med.get("Datos Generales", {}).get("Sexo", ""),
                "paciente_edad": mod_med.get("Datos Generales", {}).get("Edad", ""),
                "fecha_diagnostico": mod_med.get("Enfermedad Actual", {}).get(
                    "Fecha de diagnóstico", ""
                ),
                "estadio_clinico": mod_med.get("Enfermedad Actual", {}).get(
                    "Estadio Clínico", ""
                ),
                "antecedentes_patologicos": mod_med.get("Antecedentes Médicos", {}).get(
                    "Patológicos", ""
                ),
                "antecedentes_actuales": mod_med.get("Antecedentes Médicos", {}).get(
                    "Actuales", ""
                ),
                "otros_medicamentos": mod_med.get("Otros Medicamentos", {}).get(
                    "Descripción", "No refiere"
                ),
                "alergias": mod_med.get("Alergias", {}).get(
                    "Descripción", "No refiere"
                ),
                "habitos_alimenticios": mod_med.get("Hábitos Alimenticios", {}).get(
                    "Descripción", "Normales"
                ),
                "habitos_toxicos": mod_med.get("Hábitos Toxicológicos", {}).get(
                    "Descripción", "Niega"
                ),
                "hospitalizaciones_recientes": mod_med.get("Hospitalizaciones", {}).get(
                    "Recientes", "No refiere"
                ),
            }
        )
        # Últimos paraclínicos
        para = mod_med.get("Últimos Paraclínicos", {})
        datos_clave.update(
            {
                "fecha_paraclinico": para.get("Fecha", ""),
                "cv_paraclinico": para.get("CV", ""),
                "cd4_paraclinico": para.get("CD4+", ""),
            }
        )
    # Datos del farmacéutico
    if datos_paciente["historia_clinica"]["quimico_farmaceutico"]:
        ultimo_qf = sorted(
            datos_paciente["historia_clinica"]["quimico_farmaceutico"],
            key=lambda x: x["fecha_hora_encuentro"],
            reverse=True,
        )[0]
        mod_qf = ultimo_qf.get("datos_del_modal", {})
        pf = mod_qf.get("Seguimiento Farmacoterapéutico", {})
        datos_clave.update(
            {
                "lista_medicamentos": [
                    f["medicamento"]
                    for f in datos_paciente["plan_de_manejo"]["formulas_medicas"]
                ],
                "profilaxis_antibiotica": pf.get(
                    "Profilaxis Antibiótica", "No refiere"
                ),
                "metas_terapeuticas": pf.get("Metas Terapéuticas", ""),
                "medicamento_necesario": pf.get("¿Medicamento NECESARIO?", ""),
                "medicamento_efectivo": pf.get("¿Medicamento EFECTIVO?", ""),
                "medicamento_seguro": pf.get("¿Medicamento SEGURO?", ""),
                "interacciones": pf.get("Interacciones", "Ninguna"),
                "genotipo": pf.get("Genotipo", "N/A"),
                # SMAQ
                "fecha_dispensacion": pf.get("Fecha", ""),
                "modalidad_dispensacion": pf.get("Modalidad", ""),
                "adherencia_test": pf.get("Resultado de Adherencia Cualitativo", ""),
                "tolerancia_test": pf.get("Tolerancia", ""),
            }
        )
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
        "Genera un resumen conciso y claro en español, de no más de 1500 caracteres. "
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


### AWS ###
def invocar_bedrock(cliente, modelo_id: str, prompt: str) -> str:
    """
    Invoca un foundation model en Bedrock (Mistral / Mixtral / Titan) y devuelve el texto generado.
    """
    # Construye el payload en el formato que espera Mistral/Mixtral/Titan
    body = {
        "prompt": prompt,
        "max_tokens": 4000,
        "temperature": 0.0,
        "top_p": 1.0,
        "top_k": 50,
    }

    # Llama al InvokeModel con contentType y accept adecuados
    resp = cliente.invoke_model(
        modelId=modelo_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body),
    )

    # Lee y parsea la respuesta JSON
    resp_body = resp["body"].read().decode("utf-8")
    data = json.loads(resp_body)

    # Extrae el texto generado (para Mistral/Mixtral suele venir en results[0].content)
    return data["outputs"][0]["text"]


def resumir_paciente_con_bedrock(
    cliente: Any, datos_paciente: Dict[str, Any], model_id: str, max_chars: int = 2000
) -> Tuple[str, Dict[str, Any]]:
    """
    Prepara los datos, invoca a Bedrock para generar campos narrativos y
    fusiona los datos preparados con la respuesta de la IA en un único diccionario.

    Args:
        cliente (Any): El cliente de Bedrock.
        datos_paciente (Dict[str, Any]): Los datos brutos extraídos del paciente.
        model_id (str): El ID del modelo de Bedrock a usar.
        max_chars (int): Límite de caracteres para los campos de texto.

    Returns:
        Tuple[str, Dict[str, Any]]: Una tupla con la cédula del paciente y un
                                   diccionario que contiene TODOS los campos
                                   (preparados y generados por IA) para actualizar
                                   el registro del paciente.
    """
    cedula = datos_paciente["CEDULA"]
    print(f"    -> Preparando y generando resumen para paciente {cedula}...")

    # 1. Prepara los datos clave a partir de la data extraída
    datos_preparados = preparar_datos_para_resumen(datos_paciente=datos_paciente)
    datos_json = json.dumps(datos_preparados, ensure_ascii=False, indent=2)

    # 2. Construye el prompt para la IA
    prompt = f"""
        Eres un químico farmacéutico asistencial experto. Tu tarea es analizar los datos clínicos de un paciente y generar un objeto JSON con cuatro claves específicas.

        **Instrucciones estrictas:**
        1.  Tu respuesta debe ser **únicamente el objeto JSON**.
        2.  **No incluyas texto explicativo, introducciones, conclusiones ni la palabra "json" o ```markdown```.**
        3.  La salida debe ser un JSON crudo que comience con `{{` y termine con `}}`.
        4.  Usa indentación de 2 espacios para el formato del JSON.
        5.  Si una modalidad es remota o no es presencial, el campo "sugerencia_horarios" debe ser una lista vacía `[]`.

        **Datos Clínicos del Paciente:**
        {datos_json}

        Genera el objeto JSON con las siguientes cuatro claves:
        1. **narrativa_intervencion**:
        String que inicia con "Se realiza revisión del caso...", menciona modalidad (PRESENCIAL/NOTA DE SEGUIMIENTO),
        fecha (YYYY-MM-DD) y nombre del QF (ej: "por QF Nombre Apellido"), contexto (EPP o llamada) y termina con "indicando que:".

        2. **sugerencia_horarios**:
        Lista de objetos {{"hora": "HH:MM AM/PM", "actividad": "...", "aceptacion": "PACIENTE ACEPTA"}}
        solo si la modalidad es PRESENCIAL. Si no, [].

        3. **informacion_general**:
        Párrafo de 2-3 oraciones reforzando adherencia, objetivo del TAR, mecanismo VIH-TAR, hábitos saludables,
        uso de preservativo y derechos/deberes. Sin listas ni fechas.

        4. **concepto_qf**:
        String que inicia con "Acorde a la revisión de la trazabilidad del caso:" y termina con dos líneas:
        "Adherencia: [Adherente (95-100%) / No Adherente]" y "Tolerancia: [Buena / ...]".
        """

    # 3. Invoca el modelo de IA
    campos_generados_por_ia = {}
    try:
        respuesta_texto = invocar_bedrock(
            cliente=cliente, modelo_id=model_id, prompt=prompt
        )

        # Extraer substring JSON entre primer { y último } de forma segura
        json_match = re.search(r"\{.*\}", respuesta_texto, re.DOTALL)
        if not json_match:
            raise ValueError("No se encontró un objeto JSON en la respuesta de la IA.")

        json_fragment = json_match.group(0)
        campos_generados_por_ia = json.loads(json_fragment)

    except (json.JSONDecodeError, ValueError) as e:
        print(f"!!! ERROR al decodificar JSON para la cédula {cedula}: {e} !!!")
        print(f"Respuesta recibida de la IA:\n---\n{respuesta_texto}\n---")
        campos_generados_por_ia = {
            "narrativa_intervencion": "Error en la generación de datos.",
            "sugerencia_horarios": [],
            "informacion_general": "Error en la generación de datos.",
            "concepto_qf": f"Error al parsear la respuesta de la IA. Respuesta completa: {respuesta_texto.strip()[:max_chars]}",
        }

    # 4. Fusionar los datos preparados con los generados por la IA.
    # Los datos de la IA (campos_generados_por_ia) sobreescribirán cualquier clave
    # que pudiera tener el mismo nombre en datos_preparados.
    datos_actualizados = {**datos_preparados, **campos_generados_por_ia}

    # Recortar valores si son muy largos
    for clave, valor in datos_actualizados.items():
        if isinstance(valor, str) and len(valor) > max_chars:
            datos_actualizados[clave] = valor[:max_chars]

    return cedula, datos_actualizados


# ==============================================================================
# 5. FUNCIÓN crear archivo word
# ==============================================================================


def generar_informes_word(pacientes: list, template_path: str, output_dir: str):
    """
    Genera un archivo .docx por paciente a partir de una plantilla y data.
    """
    os.makedirs(output_dir, exist_ok=True)
    for p in pacientes:
        tpl = DocxTemplate(template_path)
        # Construir contexto plano para docxtpl
        contexto = {
            "paciente_nombre": p["NOMBRE_PACIENTE"],
            "tipo_documento_id": "CC",
            "documento_id": p["CEDULA"],
            "fecha_impresion": date.today().strftime("%d/%m/%Y"),
            "paciente_sexo": p.get("paciente_sexo", ""),
            "paciente_edad": p.get("paciente_edad", ""),
            "fecha_diagnostico": p.get("fecha_diagnostico", ""),
            "estadio_clinico": p.get("estadio_clinico", ""),
            "antecedentes_patologicos": p.get("antecedentes_patologicos", ""),
            "antecedentes_actuales": p.get("antecedentes_actuales", ""),
            "otros_medicamentos": p.get("otros_medicamentos", ""),
            "alergias": p.get("alergias", ""),
            "habitos_alimenticios": p.get("habitos_alimenticios", ""),
            "habitos_toxicos": p.get("habitos_toxicos", ""),
            "hospitalizaciones_recientes": p.get("hospitalizaciones_recientes", ""),
            "lista_medicamentos": "\n".join(p.get("lista_medicamentos", [])),
            "profilaxis_antibiotica": p.get("profilaxis_antibiotica", ""),
            "metas_terapeuticas": p.get("metas_terapeuticas", ""),
            "medicamento_necesario": p.get("medicamento_necesario", ""),
            "medicamento_efectivo": p.get("medicamento_efectivo", ""),
            "medicamento_seguro": p.get("medicamento_seguro", ""),
            "interacciones": p.get("interacciones", ""),
            "genotipo": p.get("genotipo", ""),
            "narrativa_intervencion": p.get("narrativa_intervencion", ""),
            "sugerencia_horarios": "\n".join(
                f"{h.get('hora')}: {h.get('aceptacion','')}"
                for h in p.get("sugerencia_horarios", [])
            ),
            "informacion_general": p.get("informacion_general", ""),
            "concepto_qf": p.get("concepto_qf", ""),
            "tipo_intervencion": p.get("tipo_intervencion", ""),
            "modalidad_intervencion": p.get("modalidad_intervencion", ""),
            "fecha_paraclinico": p.get("fecha_paraclinico", ""),
            "cv_paraclinico": p.get("cv_paraclinico", ""),
            "cd4_paraclinico": p.get("cd4_paraclinico", ""),
            "fecha_dispensacion": p.get("fecha_dispensacion", ""),
            "modalidad_dispensacion": p.get("modalidad_dispensacion", ""),
            "adherencia_test": p.get("adherencia_test", ""),
            "tolerancia_test": p.get("tolerancia_test", ""),
        }
        tpl.render(contexto)
        out_path = os.path.join(
            output_dir, f"{p['NOMBRE_PACIENTE']}_{p["CEDULA"]}.docx"
        )
        tpl.save(out_path)
        print(f"Informe generado: {out_path}")


# ==============================================================================
# 6. FUNCIÓN PRINCIPAL DE ORQUESTACIÓN
# ==============================================================================
def main(cedulas_a_procesar: List[str]) -> None:
    """
    Orquesta todo el proceso de extracción y resumen de datos de pacientes.
    """
    start_total_time = time.monotonic()
    print("======================================================")
    print("INICIO DEL PROCESO DE EXTRACCIÓN Y RESUMEN DE PACIENTES")
    print("======================================================")
    (
        FASTCLINICA_URL,
        USER,
        PASS,
        MODEL_ID,
        AWS_KEY_ID,
        AWS_SECRET_KEY,
        AWS_REGION,
        AWS_BEDROCK_MODEL_ID,
    ) = get_env_vars()
    if not all(
        [
            FASTCLINICA_URL,
            USER,
            PASS,
            AWS_BEDROCK_MODEL_ID,
        ]
    ):
        print(
            "\n!!! ERROR CRÍTICO: Asegúrate de que las variables de entorno estén definidas en .env !!!"
        )
        return

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
            try:
                buscar_paciente(driver=driver, cedula=cedula)
                soup_general = BeautifulSoup(driver.page_source, "html.parser")
                h1_el = soup_general.find("h1", class_="filament-header-heading")
                nombre_completo = (
                    h1_el.get_text(strip=True)
                    .replace(f"Editar CC-{cedula}", "")
                    .strip()
                    if h1_el
                    else "No encontrado"
                )
                datos_paciente = {
                    "CEDULA": cedula,
                    "NOMBRE_PACIENTE": nombre_completo,
                    "historia_clinica": {"medico": [], "quimico_farmaceutico": []},
                    "plan_de_manejo": {
                        "ordenes_de_servicio": [],
                        "formulas_medicas": [],
                    },
                }
                datos_paciente = capturar_y_procesar_historia(
                    driver=driver, datos_paciente=datos_paciente
                )
                datos_paciente = procesar_plan_de_manejo(
                    driver=driver, datos_paciente=datos_paciente
                )
                pacientes_extraidos.append(datos_paciente)
                print(f"--- Finalizada la extracción para el paciente {cedula}. ---")

                if i < len(cedulas_a_procesar) - 1:
                    print("\n-> Volviendo al escritorio para reiniciar el estado...")
                    driver.get(f"{FASTCLINICA_URL}")
                    wait = WebDriverWait(driver, 20)
                    wait.until(
                        EC.presence_of_element_located(
                            (By.XPATH, "//h1[contains(text(), 'Escritorio')]")
                        )
                    )
            except Exception as e_paciente:
                print(
                    f"!!! ERROR PROCESANDO PACIENTE {cedula}: {e_paciente}. Saltando al siguiente. !!!"
                )
                driver.get(
                    f"{FASTCLINICA_URL}"
                )  # Volver a la página de inicio para reintentar con el siguiente
                continue

    except Exception as e:
        print(f"\n!!! ERROR CRÍTICO DURANTE EL SCRAPING: {type(e).__name__} - {e} !!!")
        timestamp = int(time.time())
        screenshot_path = f"error_screenshot_{timestamp}.png"
        driver.save_screenshot(screenshot_path)
        print(f"-> Screenshot de emergencia guardado en: {screenshot_path}")
    finally:
        if "driver" in locals() and driver:
            driver.quit()
            print("\n-> WebDriver cerrado de forma segura.")

    end_scraping_time = time.monotonic()
    duration_scraping = end_scraping_time - start_scraping_time
    print(
        f"\n--- FIN FASE 1: Tiempo total de extracción: {duration_scraping:.2f} segundos ---"
    )

    if not pacientes_extraidos:
        print("\nNo se extrajeron datos de ningún paciente. Finalizando proceso.")
        return

    # --- FASE 2: RESUMEN CON IA (SECUENCIAL) ---
    print("\n\n--- FASE 2: RESUMEN CON INTELIGENCIA ARTIFICIAL (SECUENCIAL) ---")
    start_summarization_time = time.monotonic()

    pacientes_por_cedula = {p["CEDULA"]: p for p in pacientes_extraidos}
    bedrock_client = get_aws_service(
        service_name="bedrock-runtime", service_type="client", region="us-east-1"
    )

    for paciente_data in pacientes_extraidos:
        cedula_original = paciente_data["CEDULA"]
        try:
            # La función ahora devuelve todos los campos necesarios (preparados + IA)
            cedula_res, todos_los_campos_actualizados = resumir_paciente_con_bedrock(
                cliente=bedrock_client,
                datos_paciente=paciente_data,
                model_id=AWS_BEDROCK_MODEL_ID,
            )

            # Actualiza el diccionario del paciente con el diccionario fusionado
            paciente_a_actualizar = pacientes_por_cedula[cedula_res]
            paciente_a_actualizar.update(todos_los_campos_actualizados)

            print(f" -> Resumen para {cedula_original} completado y datos fusionados.")

        except Exception as e:
            print(
                f"!!! ERROR en el procesamiento síncrono para la cédula {cedula_original}: {e} !!!"
            )
            # Opcional: añadir un estado de error al paciente
            paciente_a_actualizar = pacientes_por_cedula[cedula_original]
            paciente_a_actualizar["concepto_qf"] = (
                "FALLO TOTAL: Error al generar y fusionar campos con IA."
            )

    end_summarization_time = time.monotonic()
    duration_summarization = end_summarization_time - start_summarization_time
    print(
        f"\n--- FIN FASE 2: Tiempo total de resumen secuencial: {duration_summarization:.2f} segundos ---"
    )

    # --- FASE 3: ALMACENAMIENTO DE RESULTADOS ---
    print("\n\n--- FASE 3: ALMACENAMIENTO DE RESULTADOS ---")
    output_filename = "resultados_pacientes_completos.json"
    os.makedirs("examples", exist_ok=True)
    output_path = os.path.join("examples", output_filename)
    with open(output_path, "w", encoding="utf-8") as f:
        # Guardamos la lista final de diccionarios, que ahora están completos
        json.dump(pacientes_extraidos, f, ensure_ascii=False, indent=4)
    print(f"\nResultados finales guardados en: '{output_path}'")

    # --- FASE 4: GENERACIÓN DE INFORMES EN WORD ---
    print("\n\n--- FASE 4: GENERACIÓN DE INFORMES EN WORD ---")
    template = "utils/plantilla_base_v1.docx"
    salida_docs = "informes_pacientes"
    # La lista 'pacientes_extraidos' ya contiene todos los datos completos.
    generar_informes_word(pacientes_extraidos, template, salida_docs)

    end_total_time = time.monotonic()
    duration_total = end_total_time - start_total_time
    print("\n======================================================")
    print(
        f"PROCESO COMPLETADO. TIEMPO TOTAL DE EJECUCIÓN: {duration_total:.2f} segundos"
    )
    print("======================================================")


# ==============================================================================
# 7. PUNTO DE ENTRADA DEL SCRIPT
# ==============================================================================
if __name__ == "__main__":
    lista_de_cedulas = [
        "1107088958",
        "32271898",
        # "1026553146",
    ]
    main(cedulas_a_procesar=lista_de_cedulas)
