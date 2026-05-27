# ARIA-OS: Enterprise Agentic Backend (`intelligence-agent`)

Este repositorio contiene la lógica central del agente autónomo de **ARIA-OS**, construido utilizando la arquitectura multi-agente de **Google ADK** (Agent Development Kit) 2.0 y expuesto mediante una API REST en **FastAPI**.

El agente está diseñado para actuar como un **Director de Operaciones y Abastecimiento (COO) virtual**, integrando bases de datos relacionales en Supabase, procesando inventarios, prediciendo demanda, calculando puntos de reorden, auditando finanzas y generando reportes ejecutivos automatizados en PDF.

---

## 🚀 Tecnologías Clave

*   **Google ADK (Agent Development Kit) 2.0**: Arquitectura avanzada de agentes basada en flujos deterministas mediante grafos de decisión, loops e hilos de ejecución aislados.
*   **FastAPI**: API Gateway de alto rendimiento para interactuar con el agente en tiempo real con soporte multimodal.
*   **Google GenAI (Gemini 3.5 Flash)**: Modelo de última generación optimizado para razonamiento lógico, codificación y llamadas a herramientas (Tool Calling) a gran escala con una ventana de contexto de 1M de tokens.
*   **Supabase (PostgreSQL)**: Persistencia de datos, caché de WooCommerce, propuestas estratégicas, logs de uso y políticas RLS (Row-Level Security) de inquilinos.
*   **WeasyPrint / xhtml2pdf**: Motor de renderizado HTML/CSS a PDF para la generación de reportes ejecutivos con diseño corporativo premium.

---

## 🧠 Arquitectura de Flujo y Ruteo (Kernel Workflow)

ARIA-OS implementa un pipeline de decisión robusto y optimizado en costes estructurado en `src/agents/kernel.py`:

```
                 [ PETICIÓN DE USUARIO ]
                            │
                            ▼
              [_classify_heuristic] (Cero Costo LLM)
                            │
               ┌────────────┴────────────┐
               ▼ (Intención Clara)       ▼ (Vaga / Compleja)
       [Agente Especialista]      [coordinator_llm] (Gemini 3.5 Flash)
               │                         │
               └────────────┬────────────┘
                            │
                            ▼
              [_quality_control_supervisor] (Auditoría)
                            │
               ┌────────────┴────────────┐
               ▼ (Aprobado)              ▼ (Rechazado)
        [APPROVED_NODE]           [Re-ejecución en Analyst]
               │                         │ (Máx 3 intentos)
        ┌──────┴──────────────┐          
        ▼                     ▼          
  [Retornar Respuesta]  [DocumentWorker] ──► [Compilar PDF]
        │
     (Async)
        ▼
[Skill Synthesizer] ──► [Auto-generar Skill en skills/]
```

### 1. Ruteador Heurístico de Cero Costo
Antes de consumir APIs externas, un clasificador de Python puro evalúa las palabras clave de la consulta mediante puntuaciones compuestas y límites de frontera de palabras. Si la intención pertenece claramente a un dominio (ej. Inventario, Ventas, Finanzas), se transfiere el control sin latencia ni costo. Las consultas ambiguas escalan al coordinador general de LLM.

### 2. Supervisor de Control de Calidad (QC)
Toda respuesta de los analistas es auditada por un supervisor impulsado por IA que valida las consultas SQL y el comportamiento lógico del análisis:
*   **Reglas de Base de Datos**: Asegura el uso de la tabla `wc_orders_cache`, identificador de cliente `customer_name` (no `customer_id`), fecha `date_created` (no `created_at`) y el filtrado obligatorio de órdenes inválidas: `status NOT IN ('cancelled', 'failed', 'trash', 'draft')`.
*   **Cálculo de Churn**: Rechaza diferencias simples de clientes totales; exige análisis de cohortes (CTE / JOIN) para determinar la retención real.
*   **Agregación Eficiente**: Garantiza que los cálculos pesados se realicen en Postgres para evitar la pérdida de datos por el límite de truncamiento de 200 filas de la herramienta SQL segura.

### 3. Síntesis y Carga de Habilidades Dinámicas
Al aprobarse una consulta compleja de SQL o Python, el **Skill Synthesizer** evalúa si es una tarea recurrente útil. Si califica, genera en caliente:
*   `SKILL.md`: Documento de diseño con parámetros, descripciones y lecciones de QC aplicadas.
*   `run.py`: Script autocontenido listo para ejecutarse en el sandbox.
El **Skills Loader** escanea este directorio en tiempo de ejecución, compila envoltorios dinámicos en Python usando `exec()` y recarga las herramientas de los agentes en caliente (hot-plugging).

---

## 🛡️ Guardarraíles de Seguridad y Sandboxing

1.  **Validación Pre-Flight SQL**: Todas las consultas directas generadas por los agentes pasan por un parser local antes de llegar a base de datos para inyectar filtros y rechazar columnas obsoletas.
2.  **Prevención de Mutaciones**: Cualquier sentencia SQL que contenga comandos de escritura (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, etc.) es bloqueada a nivel de socket.
3.  **Python Script Sandbox**: La herramienta de ejecución de código ejecuta scripts en un subprocess aislado con límite de tiempo de 10 segundos, variables de entorno restringidas y bloqueo de imports críticos (`os`, `sys`, `socket`, etc.) para evitar lecturas no autorizadas del host.
4.  **Rotación de API Keys**: Si una clave de Gemini es bloqueada o excede su cuota (error 429/403), el sistema rota instantáneamente de forma round-robin a la siguiente key disponible en el pool sin interrumpir la experiencia de usuario.

---

## 📁 Estructura del Proyecto

*   `src/`: Código fuente principal del backend.
    *   `src/agents/`: Definición de agentes especialistas (Ventas, Finanzas, Inventario, Compras, Estrategia, Coordinador, etc.).
    *   `src/tools/`: Herramientas nativas del sistema (Base de datos, matemática financiera, analítica de portafolio BCG, canastas de mercado y sandbox).
    *   `src/infra/`: Clientes externos de Supabase, enrutador de API keys, logger y limitador de tasa de peticiones.
    *   `src/callbacks/`: Interceptores de seguridad (prevención de prompt injections, censura de fugas de llaves privadas y sanitización matemática).
    *   `src/specs/`: Esquemas JSON de base de datos para la validación pre-flight.
*   `skills/`: Directorio de habilidades personalizadas auto-sintetizadas cargables en caliente.
*   `memory/`: Memoria persistente de negocio a largo plazo (L1 HAM):
    *   `memory/MEMORY.md`: Reglas del sistema, esquemas de datos y lecciones metodológicas aprendidas de QC.
    *   `memory/USER.md`: Preferencias del usuario, idioma y estilo de reporte del comprador de la tienda.
*   `tests/`: Pruebas de integración, verificación de herramientas y pruebas de carga.

---

## 🛠️ Configuración y Ejecución Local

### Prerrequisitos
Asegúrate de contar con Python 3.11 o superior instalado en tu sistema.

### 1. Clonar e Instalar dependencias
Instala el paquete en modo desarrollo editable para registrar los paths absolutos en la ruta PYTHONPATH:

```bash
# Crear entorno virtual
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate

# Instalar dependencias en modo editable
pip install -e .
```

### 2. Configurar el Entorno
Crea un archivo `.env` en la raíz del directorio con las siguientes credenciales:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-role-key
GEMINI_API_KEY=AIzaSyA...
GEMINI_API_KEY_2=AIzaSyB...  # Opcional para redundancia
GEMINI_API_KEY_3=AIzaSyC...  # Opcional para redundancia
```

### 3. Iniciar el Servidor de Agentes
Ejecuta el servidor de uvicorn en el puerto `8000`:

```bash
python -m uvicorn src.main:app --reload --host 127.0.0.1 --port 8000
```

El servidor estará disponible para peticiones en `http://127.0.0.1:8000`. Puedes consultar la documentación Swagger interactiva en `/docs`.
