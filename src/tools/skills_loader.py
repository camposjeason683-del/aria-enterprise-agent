"""
ARIA-OS: Dynamic Skills Loader
Scans the skills/ directory, reads SKILL.md configuration files,
and dynamically generates Python functions compatible with Google ADK 2.0.
"""
import os
import re
import sys
import yaml
from typing import List, Callable
from src.infra.logger import log_info, log_error

def make_skill_function(name: str, description: str, parameters: dict, script_path: str) -> Callable:
    """
    Generates a Python function dynamically using exec(), complete with type
    annotations and docstring, so that ADK inspect can auto-build the tool schema.
    """
    properties = parameters.get("properties", {})
    required = parameters.get("required", [])
    
    arg_defs = []
    for arg_name, arg_info in properties.items():
        arg_type = "str"
        type_str = arg_info.get("type", "string")
        if type_str == "integer":
            arg_type = "int"
        elif type_str == "number":
            arg_type = "float"
        elif type_str == "boolean":
            arg_type = "bool"
        elif type_str == "array":
            arg_type = "list"
        elif type_str == "object":
            arg_type = "dict"
            
        is_required = arg_name in required
        if is_required:
            arg_defs.append(f"{arg_name}: {arg_type}")
        else:
            arg_defs.append(f"{arg_name}: {arg_type} = None")
            
    signature_args = ", ".join(arg_defs)
    
    docstring_params = []
    for arg_name, arg_info in properties.items():
        docstring_params.append(f"        {arg_name}: {arg_info.get('description', '')}")
    docstring_params_str = "\n".join(docstring_params)
    
    func_code = f"""
def {name}({signature_args}) -> dict:
    \"\"\"
    {description}

    Args:
{docstring_params_str}
    \"\"\"
    import subprocess
    import json
    import sys
    import os
    from src.infra.logger import log_info, log_error

    # Collect parameters
    args_dict = {{
"""
    for arg_name in properties.keys():
        func_code += f"        '{arg_name}': {arg_name},\n"
        
    func_code += f"""    }}
    
    log_info(f"Executing dynamic skill '{name}' with args: {{args_dict}}")
    script_abs_path = {repr(script_path)}
    
    try:
        # Run python script in subprocess, passing inputs as JSON via stdin
        # Ensure PYTHONPATH includes workspace root and skill directory, and pass home path env vars
        workspace_root = os.path.abspath('c:/dashboard/intelligence-agent')
        python_path = os.path.pathsep.join([workspace_root, os.path.dirname(script_abs_path)])
        
        result = subprocess.run(
            [sys.executable, script_abs_path],
            input=json.dumps(args_dict),
            capture_output=True,
            text=True,
            timeout=15,
            env={{
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": python_path,
                "USERPROFILE": os.environ.get("USERPROFILE", ""),
                "HOMEDRIVE": os.environ.get("HOMEDRIVE", ""),
                "HOMEPATH": os.environ.get("HOMEPATH", ""),
            }}
        )
        
        stdout_clean = result.stdout.strip()
        stderr_clean = result.stderr.strip()
        
        if result.returncode == 0:
            try:
                # Try parsing JSON output from stdout
                output_data = json.loads(stdout_clean)
                return {{"success": True, "result": output_data}}
            except json.JSONDecodeError:
                return {{"success": True, "stdout": stdout_clean, "stderr": stderr_clean}}
        else:
            log_error(f"Dynamic skill '{name}' failed with code {{result.returncode}}. Stderr: {{stderr_clean}}")
            return {{
                "success": False,
                "error": f"Execution failed with code {{result.returncode}}",
                "stderr": stderr_clean
            }}
            
    except subprocess.TimeoutExpired:
        log_error(f"Dynamic skill '{name}' execution timed out (limit: 15s)")
        return {{"success": False, "error": "Execution timed out"}}
    except Exception as e:
        log_error(f"Error running dynamic skill '{name}': {{e}}")
        return {{"success": False, "error": str(e)}}
"""

    local_ns = {}
    sys_path = os.path.abspath('c:/dashboard/intelligence-agent')
    if sys_path not in sys.path:
        sys.path.append(sys_path)
        
    exec(func_code, globals(), local_ns)
    tool_func = local_ns[name]
    tool_func.is_dynamic_skill = True
    return tool_func

def load_dynamic_skills(skills_dir: str) -> List[Callable]:
    """
    Scans the skills directory, parses frontmatter metadata,
    and returns a list of dynamic function tools ready for ADK LlmAgent.
    """
    dynamic_tools = []
    
    if not os.path.exists(skills_dir):
        log_info(f"Skills directory '{skills_dir}' does not exist. Dynamic skills will not be loaded.")
        return dynamic_tools
        
    for item in os.listdir(skills_dir):
        skill_path = os.path.join(skills_dir, item)
        if os.path.isdir(skill_path):
            md_file = os.path.join(skill_path, "SKILL.md")
            run_script = os.path.join(skill_path, "run.py")
            
            if os.path.exists(md_file) and os.path.exists(run_script):
                try:
                    with open(md_file, "r", encoding="utf-8") as f:
                        content = f.read()
                        
                    # Extract YAML frontmatter
                    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
                    if not match:
                        log_error(f"Skipping dynamic skill in {skill_path}: No valid YAML frontmatter in SKILL.md")
                        continue
                        
                    yaml_data = yaml.safe_load(match.group(1))
                    name = yaml_data.get("name")
                    description = yaml_data.get("description", "")
                    parameters = yaml_data.get("parameters", {})
                    
                    if not name:
                        log_error(f"Skipping dynamic skill in {skill_path}: 'name' metadata not found")
                        continue
                        
                    # Build Python function wrapper
                    tool_func = make_skill_function(
                        name=name,
                        description=description,
                        parameters=parameters,
                        script_path=os.path.abspath(run_script)
                    )
                    
                    dynamic_tools.append(tool_func)
                    log_info(f"Loaded dynamic skill '{name}' from {skill_path}")
                    
                except Exception as e:
                    log_error(f"Failed to load dynamic skill from {skill_path}: {e}")
    return dynamic_tools

def refresh_dynamic_skills(agents: list, skills_dir: str = "c:/dashboard/intelligence-agent/skills"):
    """
    Reloads all skills from the skills_dir and updates the tools list of each agent
    by removing old dynamic skills and appending the newly loaded ones.
    """
    new_tools = load_dynamic_skills(skills_dir)
    for agent in agents:
        if not hasattr(agent, "tools"):
            continue
        static_tools = [t for t in agent.tools if not getattr(t, "is_dynamic_skill", False)]
        agent.tools = static_tools + new_tools
        log_info(f"Refreshed tools for agent '{agent.name}': Now has {len(agent.tools)} tools ({len(new_tools)} dynamic).")
