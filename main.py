import os
import re
import yaml
import flet as ft
from agent import ReActAgent
from gui import SardineClawGUI
def load_config(path: str, substitute_env=True):
    """加载 YAML 配置文件，可选地替换 ${ENV_VAR} 环境变量"""
    if not os.path.exists(path):
        raise FileNotFoundError(f"配置文件 {path} 不存在")
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    if substitute_env:
        def replace_env(match):
            var_name = match.group(1)
            return os.getenv(var_name, "")
        content = re.sub(r'\$\{(\w+)\}', replace_env, content)
    return yaml.safe_load(content)

def get_available_skills(skills_dir: str = "./skills"):
    """扫描 skills 目录，返回所有技能名称列表（每个子目录名即技能名）"""
    if not os.path.exists(skills_dir):
        os.makedirs(skills_dir, exist_ok=True)
        return []
    skills = []
    for entry in os.listdir(skills_dir):
        skill_path = os.path.join(skills_dir, entry)
        if os.path.isdir(skill_path) and os.path.isfile(os.path.join(skill_path, "SKILL.md")):
            skills.append(entry)
    return skills

def main(page: ft.Page):
    # 1. 加载 Agent 基础配置（单 Agent 模式，顶层字段）
    agent_cfg = load_config("agents_conf.yaml")
    agent_name = agent_cfg.get('name', 'AI助手')
    agent_color = agent_cfg.get('color', 'blue')
    agent_icon = agent_cfg.get('icon', 'android')
    skills_cfg = agent_cfg.get('skills', '')
    skill_names = [s.strip() for s in skills_cfg.split(';') if s.strip()]

    # 2. 加载模型列表
    models_cfg = load_config("llm.yaml")
    models = models_cfg.get('models', [])
    if not models:
        raise RuntimeError("llm.yaml 中未定义任何模型")

    default_model = models[0]

    # 3. 创建 Agent（初始使用默认模型配置）
    agent = ReActAgent(
        api_key=default_model['api_key'],
        base_url=default_model['base_url'],
        model=default_model['model'],
        skills_dir="./skills",
        skill_names=skill_names
    )

    # 4. 启动 GUI
    app = SardineClawGUI(
        page=page,
        agent_name=agent_name,
        agent_color=agent_color,
        agent_icon=agent_icon,
        agent=agent,
        models=models,
        skill_names=skill_names,
        skills_dir="./skills"
    )
    app.build()

if __name__ == "__main__":
    ft.run(main)