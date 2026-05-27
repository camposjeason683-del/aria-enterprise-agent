# ARIA-OS: Enterprise Agentic Backend (intelligence-agent)

Este repositorio contiene la lógica central del agente autónomo de **ARIA-OS**, construido utilizando la arquitectura multi-agente de **Google ADK** (Agent Development Kit) y expuesto mediante una API REST en **FastAPI**.

El agente está diseñado para interactuar con bases de datos relacionales en Supabase, procesar inventarios, predecir demanda, calcular reórdenes y comunicarse de forma autónoma utilizando modelos Gemini.

---

## 🚀 Tecnologías Clave

*   **Google ADK (Agent Development Kit)**: Arquitectura avanzada de agentes basada en grafos de decisión, loops y secuencias.
*   **FastAPI**: API Gateway de alto rendimiento para interactuar con el agente y recibir respuestas en tiempo real.
*   **Google GenAI (Gemini 2.5 / Flash / Pro)**: Modelos avanzados de lenguaje natural para razonamiento y planificación de tareas.
*   **Supabase (PostgreSQL)**: Persistencia de datos, caché de WooCommerce, propuestas de compra y políticas RLS.
*   **WeasyPrint**: Generación de reportes ejecutivos en PDF.

---

## 📁 Estructura del Proyecto

*   `src/`: Código fuente principal del agente.
    *   `src/agents/`: Agentes especializados (Coordinador, Planificador de Demanda, Analista de Finanzas, etc.).
    *   `src/tools/`: Herramientas del sistema (base de datos, búsqueda web, análisis y ejecución dinámica).
    *   `src/infra/`: Clientes de base de datos, enrutadores de claves de API y controladores de artefactos.
    *   `src/callbacks/`: Validadores pre-flight e interceptores de seguridad.
*   `skills/`: Habilidades personalizadas dinámicas que los agentes pueden cargar en tiempo de ejecución.
*   `memory/`: Memoria a largo plazo persistente (`MEMORY.md` y `USER.md`).
*   `tests/`: Pruebas de integración y carga.

---

## 🛠️ Configuración y Ejecución

### 1. Clonar el repositorio y configurar el entorno
Asegúrate de tener Python 3.11 o superior instalado.

```bash
# Crear entorno virtual
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate

# Instalar dependencias en modo editable
pip install -e .
```

### 2. Configurar variables de entorno
Crea un archivo `.env` en la raíz del directorio `intelligence-agent` con las siguientes credenciales:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-role-key
GEMINI_API_KEY=AIzaSy...
GEMINI_API_KEY_2=AIzaSy...
GEMINI_API_KEY_3=AIzaSy...
GEMINI_API_KEY_4=AIzaSy...
```

### 3. Iniciar el Servidor de Agentes
Ejecuta el servidor de FastAPI en el puerto 8000:

```bash
python -m uvicorn src.main:app --reload --host 127.0.0.1 --port 8000
```

---

## 🧠 Arquitectura de Seguridad y Robustez

El agente implementa varios mecanismos avanzados para entornos empresariales:

1.  **Rotación Dinámica de API Keys**: Si un modelo falla con un error `403` (suspensión/bloqueo de clave) o `429` (límite de cuota), el enrutador conmuta la llamada a la siguiente clave disponible de forma instantánea y transparente.
2.  **Validación Pre-Flight SQL**: Todas las consultas SQL generadas por el agente de forma dinámica pasan por un validador que intercepta e inyecta reglas obligatorias (por ejemplo, filtros de estados de órdenes válidas) para prevenir alucinaciones o lecturas de datos incorrectos.
3.  **L1 HAM Memory Injection**: Los agentes cargan el contexto del negocio (esquemas y restricciones) al inicio del pipeline para evitar errores en las primeras ejecuciones de tareas complejas.
