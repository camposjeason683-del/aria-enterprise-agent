"""
ARIA-OS: Document Worker & Engine
Department: Procurement & Operations
Generates PDF files from data and stores them in Supabase.
"""
import re
import zipfile
import io
from typing import AsyncGenerator
from datetime import datetime
from google.adk.agents import BaseAgent
from google.adk.events import Event
from google.genai import types

from src.infra.artifacts import SupabaseArtifactService
from src.infra.logger import log_info, log_error

def parse_inline_markdown(text: str) -> str:
    """Helper to convert inline markdown syntax (bold, italic, code) to HTML."""
    text = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.*?)\*", r"<em>\1</em>", text)
    text = re.sub(r"`(.*?)`", r"<code>\1</code>", text)
    return text

def markdown_to_html(md_text: str) -> str:
    """Converts basic Markdown titles, lists, bold text, and tables into clean HTML."""
    lines = md_text.split("\n")
    html_lines = []
    in_list = False
    in_table = False
    
    for line in lines:
        stripped = line.strip()
        
        # Handle lists
        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            content = stripped[2:]
            content = parse_inline_markdown(content)
            html_lines.append(f"<li>{content}</li>")
            continue
        elif in_list:
            html_lines.append("</ul>")
            in_list = False
            
        # Handle tables
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            # Skip separator line like |---|---|
            if all(all(char in "- :" for char in cell) and len(cell) > 0 for cell in cells):
                continue
            
            if not in_table:
                html_lines.append("<table>")
                in_table = True
                html_lines.append("<thead><tr>")
                for cell in cells:
                    cell_parsed = parse_inline_markdown(cell)
                    html_lines.append(f"<th>{cell_parsed}</th>")
                html_lines.append("</tr></thead><tbody>")
            else:
                html_lines.append("<tr>")
                for cell in cells:
                    cell_parsed = parse_inline_markdown(cell)
                    html_lines.append(f"<td>{cell_parsed}</td>")
                html_lines.append("</tr>")
            continue
        elif in_table:
            html_lines.append("</tbody></table>")
            in_table = False
            
        # Titles
        if stripped.startswith("### "):
            content = parse_inline_markdown(stripped[4:])
            html_lines.append(f"<h3>{content}</h3>")
        elif stripped.startswith("## "):
            content = parse_inline_markdown(stripped[3:])
            html_lines.append(f"<h2>{content}</h2>")
        elif stripped.startswith("# "):
            content = parse_inline_markdown(stripped[2:])
            html_lines.append(f"<h1>{content}</h1>")
        # Empty lines
        elif stripped == "":
            if html_lines and html_lines[-1] != "<br>":
                html_lines.append("<br>")
        else:
            content = parse_inline_markdown(stripped)
            html_lines.append(f"<p>{content}</p>")
            
    if in_list:
        html_lines.append("</ul>")
    if in_table:
        html_lines.append("</tbody></table>")
        
    return "\n".join(html_lines)

class DocumentWorker(BaseAgent):
    """
    Deterministic worker that extracts approved markdown text from the state/events,
    converts it to premium corporate HTML/CSS, and compiles it into a PDF using WeasyPrint.
    If local Windows system libraries (GTK) are missing, it automatically falls back
    to xhtml2pdf (pure Python PDF compiler) to deliver a real, downloadable PDF directly.
    """
    async def _run_async_impl(self, ctx) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        
        report_text = state.get("temp:approved_response") or ""
        
        if not report_text:
            events = ctx.session.events if (hasattr(ctx, "session") and ctx.session) else []
            analysts = ["sales_analyst", "finance_analyst", "inventory_analyst", "demand_planner", "procurement_analyst", "strategic_advisor"]
            for ev in reversed(events):
                if ev.author in analysts and ev.content and ev.content.parts:
                    text_parts = [p.text for p in ev.content.parts if p.text]
                    if text_parts:
                        report_text = "\n".join(text_parts)
                        break
                        
        if not report_text:
            report_text = "# Reporte General\nNo se encontraron datos de análisis detallado en la sesión."
            
        report_type = state.get("temp:report_type", "general")
        
        # Convert Markdown body to HTML
        report_body_html = markdown_to_html(report_text)
        current_date_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        
        # Build premium corporate HTML structure
        html_content = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>Reporte Corporativo ARIA-OS</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@400;600;700&display=swap');
        
        @page {{
            size: A4;
            margin: 20mm;
            @bottom-right {{
                content: "Página " counter(page) " de " counter(pages);
                font-family: 'Inter', sans-serif;
                font-size: 8pt;
                color: #64748B;
            }}
            @bottom-left {{
                content: "ARIA-OS • Confidencial";
                font-family: 'Inter', sans-serif;
                font-size: 8pt;
                color: #64748B;
            }}
        }}
        
        body {{
            font-family: 'Inter', sans-serif;
            color: #1E293B;
            line-height: 1.6;
            font-size: 10.5pt;
            margin: 0;
            padding: 0;
            background: #FFFFFF;
        }}
        
        .report-header {{
            border-bottom: 2px solid #E2E8F0;
            padding-bottom: 15px;
            margin-bottom: 30px;
            display: block;
            min-height: 50px;
        }}
        
        .logo-area {{
            font-family: 'Outfit', sans-serif;
            font-size: 20pt;
            font-weight: 700;
            color: #0F172A;
            float: left;
        }}
        
        .logo-area span {{
            color: #0284C7;
        }}
        
        .meta-area {{
            float: right;
            text-align: right;
            font-size: 9pt;
            color: #64748B;
            line-height: 1.4;
        }}
        
        .clearfix {{
            clear: both;
        }}
        
        h1 {{
            font-family: 'Outfit', sans-serif;
            font-size: 20pt;
            color: #0F172A;
            margin-top: 10px;
            margin-bottom: 15px;
            font-weight: 700;
            letter-spacing: -0.02em;
        }}
        
        h2 {{
            font-family: 'Outfit', sans-serif;
            font-size: 14pt;
            color: #1E293B;
            border-left: 4px solid #0284C7;
            padding-left: 12px;
            margin-top: 25px;
            margin-bottom: 15px;
            font-weight: 600;
        }}
        
        h3 {{
            font-family: 'Outfit', sans-serif;
            font-size: 11.5pt;
            color: #334155;
            margin-top: 20px;
            margin-bottom: 10px;
            font-weight: 600;
        }}
        
        p {{
            margin-top: 0;
            margin-bottom: 12px;
            text-align: justify;
        }}
        
        ul {{
            margin-top: 0;
            margin-bottom: 15px;
            padding-left: 20px;
        }}
        
        li {{
            margin-bottom: 6px;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
            margin-bottom: 20px;
            font-size: 9pt;
        }}
        
        th {{
            background-color: #0F172A;
            color: #FFFFFF;
            font-family: 'Outfit', sans-serif;
            font-weight: 600;
            text-align: left;
            padding: 8px 10px;
            border: 1px solid #0F172A;
        }}
        
        td {{
            padding: 8px 10px;
            border-bottom: 1px solid #E2E8F0;
            color: #334155;
        }}
        
        tr:nth-child(even) td {{
            background-color: #F8FAFC;
        }}
        
        code {{
            font-family: 'Courier New', monospace;
            background-color: #F1F5F9;
            padding: 2px 5px;
            border-radius: 4px;
            font-size: 8.5pt;
            color: #0F172A;
        }}
    </style>
</head>
<body>
    <div class="report-header">
        <div class="logo-area">ARIA<span>.OS</span></div>
        <div class="meta-area">
            <strong>Generado por:</strong> ARIA Inteligencia<br>
            <strong>Fecha:</strong> {current_date_str}<br>
            <strong>Departamento:</strong> Analítica
        </div>
        <div class="clearfix"></div>
    </div>
    
    <div class="report-content">
        {report_body_html}
    </div>
</body>
</html>
"""
        
        # 3. Compile to PDF (WeasyPrint -> Fallback to xhtml2pdf -> Fallback to ZIP-HTML)
        file_bytes = None
        is_pdf = True
        used_method = "WeasyPrint"
        
        try:
            from weasyprint import HTML
            file_bytes = HTML(string=html_content).write_pdf()
            log_info("WeasyPrint compiled PDF successfully", agent="document_worker")
        except Exception as wp_error:
            log_info(f"WeasyPrint local fallback triggered: {wp_error}. Trying xhtml2pdf.", agent="document_worker")
            
            try:
                from xhtml2pdf import pisa
                # Clean @import Google Fonts from HTML to prevent ReportLab permission/urllib bugs on Windows
                html_for_pisa = re.sub(r"@import url\(['\"].*?['\"]\);", "", html_content)
                # Clean nested page margin boxes (e.g. @bottom-right, @bottom-left) to prevent xhtml2pdf NotImplementedType crash
                html_for_pisa = re.sub(r"@(bottom|top|left|right)-[a-z-]+\s*\{[^}]*\}", "", html_for_pisa)
                
                pdf_buffer = io.BytesIO()
                pisa_status = pisa.CreatePDF(html_for_pisa, dest=pdf_buffer)
                
                if not pisa_status.err:
                    file_bytes = pdf_buffer.getvalue()
                    used_method = "xhtml2pdf"
                    log_info("xhtml2pdf compiled PDF successfully", agent="document_worker")
                else:
                    raise Exception(f"xhtml2pdf error code: {pisa_status.err}")
            except Exception as pisa_error:
                log_error(f"xhtml2pdf compilation failed: {pisa_error}. Falling back to ZIP-HTML.", agent="document_worker")
                
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                    zip_file.writestr(f"reporte_{report_type}.html", html_content)
                    
                file_bytes = zip_buffer.getvalue()
                is_pdf = False
            
        try:
            # 4. Save to Supabase Storage
            artifacts = SupabaseArtifactService()
            import uuid
            unique_id = str(uuid.uuid4())[:8]
            ext = "pdf" if is_pdf else "zip"
            file_name = f"reporte_{report_type}_{unique_id}.{ext}"
            
            await artifacts.save_artifact(file_name, file_bytes)
            url = await artifacts.get_artifact_url(file_name)
            
            if is_pdf:
                doc_type_label = f"PDF (Compilado vía {used_method})"
                message_text = (
                    f"📄 **Reporte de Negocio Generado**\n\n"
                    f"Se ha analizado la información y se ha consolidado en un documento formato **{doc_type_label}**.\n\n"
                    f"🔗 **[Descargar Reporte PDF Directo]({url})**\n\n"
                    f"El reporte cuenta con el diseño corporativo de ARIA-OS e incluye el desglose detallado del análisis."
                )
            else:
                doc_type_label = "Archivo ZIP (Reporte Web Interactivo)"
                message_text = (
                    f"📦 **Reporte de Negocio Generado (ZIP)**\n\n"
                    f"Lamentablemente no pudimos compilar el PDF de forma nativa. He empaquetado el reporte web interactivo en un archivo **ZIP** para evitar que el navegador te muestre el código en bruto.\n\n"
                    f"🔗 **[Descargar Reporte Web (ZIP)]({url})**\n\n"
                    f"**Instrucciones:** Descarga el archivo ZIP, extráelo y haz doble clic sobre el archivo `.html` que contiene para abrir el reporte web de forma hermosa."
                )
            
            # Trigger dynamic skill synthesis in the background
            try:
                import asyncio
                from src.tools.skill_synthesizer import evaluate_and_synthesize_skill
                from src.tools.skills_loader import refresh_dynamic_skills
                from src.agents.sales_analyst import sales_analyst
                from src.agents.finance_analyst import finance_analyst
                from src.agents.inventory_analyst import inventory_analyst
                from src.agents.demand_planner import demand_planner
                from src.agents.procurement_analyst import procurement_analyst
                from src.agents.strategic_advisor import strategic_advisor

                events = ctx.session.events if (hasattr(ctx, "session") and ctx.session) else []

                async def run_synthesis_and_refresh():
                    success = await evaluate_and_synthesize_skill(events)
                    if success:
                        refresh_dynamic_skills([
                            sales_analyst,
                            finance_analyst,
                            inventory_analyst,
                            demand_planner,
                            procurement_analyst,
                            strategic_advisor
                        ])

                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(run_synthesis_and_refresh())
                else:
                    asyncio.run(run_synthesis_and_refresh())
            except Exception as e:
                log_error(f"Document worker: Error launching skill synthesizer background task: {e}")

            yield Event(
                author=self.name,
                content=types.Content(parts=[
                    types.Part(text=message_text)
                ])
            )
            
        except Exception as e:
            log_error(f"Error saving report artifact: {e}", agent="document_worker")
            yield Event(
                author=self.name,
                content=types.Content(parts=[
                    types.Part(text=f"❌ Error generando documento: {str(e)}")
                ])
            )
