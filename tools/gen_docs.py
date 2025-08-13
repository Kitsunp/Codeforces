#!/usr/bin/env python3
"""
Script principal de auto-documentación
Escanea carpetas, encuentra ejemplos, genera .md con Gemini 2.5 Flash
"""

import os
import glob
from google import genai
from pathlib import Path
import sys
import time

# Configuración
PROBLEMAS_ROOT = "Problemas"
MIN_MD_SIZE = 10
EXAMPLES_MIN_SIZE = 50
MAX_EXAMPLES = 5
MAX_RETRIES = 3
BASE_DELAY = 45  # Segundos

def setup_gemini():
    """Configura Gemini API"""
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        print("❌ GEMINI_API_KEY no encontrada")
        sys.exit(1)

    return genai.Client(api_key=api_key)

def find_md_files(folder_path):
    """Encuentra archivos .md en una carpeta"""
    return glob.glob(os.path.join(folder_path, "*.md"))

def has_code_files(folder_path):
    """Verifica si la carpeta tiene archivos de código"""
    cpp_files = glob.glob(os.path.join(folder_path, "*.cpp"))
    py_files = glob.glob(os.path.join(folder_path, "*.py"))
    return len(cpp_files) > 0 or len(py_files) > 0

def get_largest_md_size(md_files):
    """Obtiene el tamaño del archivo .md más grande"""
    if not md_files:
        return 0

    max_size = 0
    for md_file in md_files:
        try:
            size = os.path.getsize(md_file)
            max_size = max(max_size, size)
        except:
            continue
    return max_size

def scan_for_targets():
    """Escanea carpetas y encuentra objetivos para documentar"""
    targets = []

    if not os.path.exists(PROBLEMAS_ROOT):
        print(f"❌ Carpeta {PROBLEMAS_ROOT} no existe")
        return targets

    for item in os.listdir(PROBLEMAS_ROOT):
        folder_path = os.path.join(PROBLEMAS_ROOT, item)

        if not os.path.isdir(folder_path):
            continue

        # Verificar que tenga código
        if not has_code_files(folder_path):
            continue

        # Verificar estado de documentación
        md_files = find_md_files(folder_path)
        largest_md_size = get_largest_md_size(md_files)

        if largest_md_size < MIN_MD_SIZE:
            targets.append(folder_path)
            print(f"🎯 Objetivo: {folder_path}")

    return targets

def collect_examples():
    """Recolecta ejemplos de carpetas ya documentadas"""
    examples = []

    if not os.path.exists(PROBLEMAS_ROOT):
        return examples

    for item in os.listdir(PROBLEMAS_ROOT):
        folder_path = os.path.join(PROBLEMAS_ROOT, item)

        if not os.path.isdir(folder_path):
            continue

        if not has_code_files(folder_path):
            continue

        md_files = find_md_files(folder_path)
        largest_md_size = get_largest_md_size(md_files)

        if largest_md_size >= EXAMPLES_MIN_SIZE:
            examples.append(folder_path)

        if len(examples) >= MAX_EXAMPLES:
            break

    return examples

def read_code_files(folder_path):
    """Lee archivos de código de una carpeta"""
    code_content = []

    # Leer archivos C++
    cpp_files = glob.glob(os.path.join(folder_path, "*.cpp"))
    for cpp_file in cpp_files:
        try:
            with open(cpp_file, 'r', encoding='utf-8') as f:
                content = f.read()
                code_content.append(f"// {os.path.basename(cpp_file)}\n{content}")
        except:
            continue

    # Leer archivos Python
    py_files = glob.glob(os.path.join(folder_path, "*.py"))
    for py_file in py_files:
        try:
            with open(py_file, 'r', encoding='utf-8') as f:
                content = f.read()
                code_content.append(f"# {os.path.basename(py_file)}\n{content}")
        except:
            continue

    return "\n\n".join(code_content)

def read_md_content(folder_path):
    """Lee el contenido del archivo .md más grande"""
    md_files = find_md_files(folder_path)
    if not md_files:
        return ""

    largest_file = max(md_files, key=lambda x: os.path.getsize(x) if os.path.exists(x) else 0)

    try:
        with open(largest_file, 'r', encoding='utf-8') as f:
            return f.read()
    except:
        return ""

def build_prompt(target_folder, examples):
    """Construye el prompt para Gemini"""
    with open('docs/prompt-template.txt', 'r', encoding='utf-8') as f:
        template = f.read()

    # Construir ejemplos
    examples_text = ""
    for i, example_folder in enumerate(examples, 1):
        code = read_code_files(example_folder)
        md_content = read_md_content(example_folder)

        examples_text += f"""
=== EJEMPLO {i} ===
Carpeta: {os.path.basename(example_folder)}
Código:
{code}

Documentación (.md):
{md_content}
"""

    # Código a documentar
    target_code = read_code_files(target_folder)

    prompt = f"""{template}

{examples_text}

=== CÓDIGO A DOCUMENTAR ===
Carpeta: {os.path.basename(target_folder)}
Código:
{target_code}

Instrucciones:
- Genera documentación en Markdown que mantenga el mismo formato, estructura y nivel de detalle que los ejemplos
- No inventes enunciados del problema
- Enfócate en explicar el enfoque/algoritmo visible en el código
- Mantén el tono y estilo de los ejemplos existentes
- Responde ÚNICAMENTE con el contenido del archivo Markdown
"""

    return prompt

def generate_documentation(client, target_folder, examples):
    """Genera documentación usando Gemini con reintentos"""
    print(f"📝 Generando documentación para: {target_folder}")

    for attempt in range(MAX_RETRIES):
        try:
            if attempt > 0:
                # Delay incremental: 45s, 75s, 120s
                delay = BASE_DELAY + (attempt * 30)
                print(f"🔄 Intento {attempt + 1}/{MAX_RETRIES} - Esperando {delay}s antes del reintento...")
                time.sleep(delay)

            prompt = build_prompt(target_folder, examples)

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config={
                    "temperature": 0.2,
                    "max_output_tokens": 1500
                }
            )

            # Verificar que la respuesta no sea None
            if response.text is None:
                print(f"⚠️  Intento {attempt + 1}: Respuesta vacía de la API")
                if attempt == MAX_RETRIES - 1:
                    print(f"❌ Agotados los {MAX_RETRIES} intentos para {target_folder}")
                    return False
                continue

            content = response.text.strip()

            if len(content) < MIN_MD_SIZE:
                print(f"⚠️  Intento {attempt + 1}: Contenido muy corto ({len(content)} chars)")
                if attempt == MAX_RETRIES - 1:
                    print(f"❌ Agotados los {MAX_RETRIES} intentos para {target_folder}")
                    return False
                continue

            # Éxito: escribir archivo
            md_path = os.path.join(target_folder, "README.md")
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(content)

            success_msg = f"✅ Generado: {md_path}"
            if attempt > 0:
                success_msg += f" (exitoso en intento {attempt + 1})"
            print(success_msg)
            return True

        except Exception as e:
            print(f"⚠️  Intento {attempt + 1}: Error - {str(e)}")
            if attempt == MAX_RETRIES - 1:
                print(f"❌ Agotados los {MAX_RETRIES} intentos para {target_folder}")
                return False

    return False

def main():
    """Función principal"""
    print("🚀 Iniciando auto-documentación...")

    # Setup
    client = setup_gemini()

    # Escanear objetivos
    targets = scan_for_targets()
    if not targets:
        print("✨ No hay carpetas que necesiten documentación")
        return

    # Recolectar ejemplos
    examples = collect_examples()
    if not examples:
        print("⚠️  No se encontraron ejemplos para aprender")
        return

    print(f"📚 Usando {len(examples)} ejemplos como referencia")

    # Generar documentación
    success_count = 0
    total_targets = len(targets)

    for i, target in enumerate(targets, 1):
        print(f"\n[{i}/{total_targets}] Procesando: {os.path.basename(target)}")

        if generate_documentation(client, target, examples):
            success_count += 1

        # Esperar 30 segundos antes del siguiente (excepto en el último)
        if i < total_targets:
            print("⏳ Esperando 30s antes del siguiente para evitar rate limits...")
            time.sleep(30)

    print(f"\n🎉 Completado: {success_count}/{total_targets} documentos generados")

if __name__ == "__main__":
    main()