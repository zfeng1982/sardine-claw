import os
import re
import json
import asyncio
import subprocess
import shlex
import yaml
from typing import Dict, List, Any, Optional, AsyncGenerator
from openai import AsyncOpenAI, OpenAI
from openai.types.chat import ChatCompletionMessageParam
from const import ClawConst


class ReActAgent:
    """实现 Plan-and-Execute 机制的 Agent，支持多技能协作"""

    def __init__(self, api_key: str, base_url: str, model: str,
                 skills_dir: str = "./skills", skill_names: List[str] = None):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.skills_dir = skills_dir
        self.skill_names = skill_names if skill_names is not None else []
        self.skills = self._load_skills()
        self.command_executor = CommandExecutor()

        # Token 累计（整个对话生命周期）
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        # 上一次 LLM 调用的 token 用量（用于流式）
        self._last_prompt_tokens = 0
        self._last_completion_tokens = 0
        self._last_total_tokens = 0

    def _load_skills(self) -> List[Dict[str, Any]]:
        """从skills目录下加载指定的技能"""
        skills = []
        if not os.path.exists(self.skills_dir):
            os.makedirs(self.skills_dir, exist_ok=True)
            return skills
        if not self.skill_names:
            return skills
        for entry in os.listdir(self.skills_dir):
            if entry not in self.skill_names:
                continue
            skill_dir = os.path.join(self.skills_dir, entry)
            if not os.path.isdir(skill_dir):
                continue
            skill_md_path = os.path.join(skill_dir, "SKILL.md")
            if not os.path.isfile(skill_md_path):
                continue
            with open(skill_md_path, 'r', encoding='utf-8') as f:
                content = f.read()
            yaml_data = {}
            body = content
            if content.startswith('---'):
                parts = content.split('---', 2)
                if len(parts) >= 3:
                    try:
                        yaml_data = yaml.safe_load(parts[1])
                        body = parts[2].strip()
                    except:
                        pass
            skill_name = yaml_data.get('name', entry)
            description = yaml_data.get('description', '') or self._extract_description(body)
            skills.append({
                'name': skill_name,
                'description': description,
                'full_content': body,
                'yaml': yaml_data,
                'skill_dir': skill_dir
            })
        return skills

    def _extract_description(self, text: str) -> str:
        lines = text.splitlines()
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#') and not line.startswith('-'):
                return line
        return ""

    def _build_skills_docs(self) -> str:
        """构建所有技能的文档字符串，用于计划生成"""
        docs = []
        for skill in self.skills:
            docs.append(f"## 技能名称：{skill['name']}\n{skill['full_content']}\n")
        return "\n".join(docs)

    async def _generate_plan(self, user_input: str) -> List[Dict[str, str]]:
        """调用 LLM 生成执行计划，返回步骤列表，每步含 skill 和 command"""
        if not self.skills:
            return []

        skills_docs = self._build_skills_docs()
        prompt = ClawConst.PLAN_GENERATION_PROMPT.format(
            user_input=user_input,
            skills_docs=skills_docs
        )

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=ClawConst.MODEL_TEMPERATURE,
                max_tokens=ClawConst.MODEL_MAX_TOKENS
            )
            # 累加 token
            if response.usage:
                self.total_prompt_tokens += response.usage.prompt_tokens
                self.total_completion_tokens += response.usage.completion_tokens
                self.total_tokens += response.usage.total_tokens

            content = response.choices[0].message.content.strip()
            # 提取 JSON（可能被 markdown 包裹）
            json_match = re.search(r'\{.*\}|\[.*\]', content, re.DOTALL)
            if json_match:
                content = json_match.group(0)
            plan_data = json.loads(content)
            # 支持两种格式：直接列表或 {"plan": [...]}
            if isinstance(plan_data, dict) and "plan" in plan_data:
                plan = plan_data["plan"]
            elif isinstance(plan_data, list):
                plan = plan_data
            else:
                plan = []
            # 校验每个步骤必须包含 skill 和 command
            valid_plan = []
            for step in plan:
                if isinstance(step, dict) and "skill" in step and "command" in step:
                    # 确保技能已加载
                    if any(s['name'] == step['skill'] for s in self.skills):
                        valid_plan.append(step)
                    else:
                        print(f"警告：计划中使用了未加载的技能 '{step['skill']}'，已忽略")
            return valid_plan
        except Exception as e:
            print(f"计划生成失败: {e}")
            return []

    async def _execute_plan(self, plan: List[Dict[str, str]]) -> List[str]:
        """执行计划中的每个步骤，返回结果列表"""
        results = []
        for step in plan:
            skill_name = step['skill']
            command = step['command']
            # 查找技能目录
            skill_dir = None
            for s in self.skills:
                if s['name'] == skill_name:
                    skill_dir = s['skill_dir']
                    break
            if not skill_dir:
                results.append(f"错误：未找到技能 '{skill_name}' 的工作目录")
                continue

            # 替换命令中的占位符（如有）
            cmd = command.replace("{baseDir}", skill_dir)
            try:
                result = await asyncio.to_thread(self.command_executor.run, cmd, cwd=skill_dir)
                results.append(result if result else "命令执行成功（无输出）")
            except Exception as e:
                results.append(f"命令执行失败: {str(e)}")
        return results

    async def _generate_final_answer(self, user_input: str, plan: List[Dict[str, str]],
                                     execution_results: List[str]) -> AsyncGenerator[str, None]:
        """基于用户输入、计划、执行结果，流式生成最终答案"""
        plan_str = json.dumps(plan, ensure_ascii=False, indent=2)
        results_str = "\n".join([f"步骤{i+1}: {r}" for i, r in enumerate(execution_results)])
        prompt = ClawConst.FINAL_ANSWER_PROMPT.format(
            user_input=user_input,
            plan=plan_str,
            execution_results=results_str
        )
        messages = [{"role": "user", "content": prompt}]

        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=ClawConst.MODEL_TEMPERATURE,
                max_tokens=ClawConst.MODEL_MAX_TOKENS,
                stream=True,
                stream_options={"include_usage": True}
            )
            usage = None
            async for chunk in stream:
                if chunk.usage:
                    usage = chunk.usage
                    continue
                if chunk.choices and chunk.choices[0].delta.content:
                    delta = chunk.choices[0].delta.content
                    delta = delta.replace('\\n', '\n').replace('<br>', '\n').replace('\\r\\n', '\n')
                    yield delta
            if usage:
                self._last_prompt_tokens = usage.prompt_tokens
                self._last_completion_tokens = usage.completion_tokens
                self._last_total_tokens = usage.total_tokens
                self.total_prompt_tokens += self._last_prompt_tokens
                self.total_completion_tokens += self._last_completion_tokens
                self.total_tokens += self._last_total_tokens
        except Exception as e:
            yield f"生成最终答案失败: {str(e)}"

    async def run_stream(self, user_input: str) -> AsyncGenerator[str, None]:
        """
        Plan-and-Execute 主流程：
        1. 生成计划
        2. 执行计划中的命令
        3. 基于执行结果生成最终答案（包含对计划符合性的判断）
        """
        if not self.skills:
            yield "抱歉，我还没学习任何技能，无法执行任务。"
            return

        # 1. 生成计划
        yield "📋 **正在分析需求并生成执行计划...**\n\n"
        plan = await self._generate_plan(user_input)
        if not plan:
            yield "未生成有效计划，请检查技能配置或重新描述需求。\n"
            return

        yield f"**执行计划**：\n```json\n{json.dumps(plan, ensure_ascii=False, indent=2)}\n```\n\n"

        # 2. 执行计划 ClawConst.ACT_MAX_STEPS
        yield "⚙️ **开始执行计划...**\n\n"
        execution_results = await self._execute_plan(plan)
        for i, res in enumerate(execution_results):
            yield f"**步骤 {i+1} 执行结果**：\n```\n{res}\n```\n\n"

        # 3. 生成最终答案（包含对计划符合性的判断）
        yield "💬 **最终回答**：\n"
        async for chunk in self._generate_final_answer(user_input, plan, execution_results):
            yield chunk


class CommandExecutor:
    def run(self, command: str, cwd: str = None) -> str:
        try:
            cmd_list = shlex.split(command)
            result = subprocess.run(cmd_list, cwd=cwd, capture_output=True, text=False, timeout=30)

            def decode_bytes(data: bytes) -> str:
                if not data:
                    return ""
                for enc in ['utf-8', 'gbk', 'cp936', 'latin1']:
                    try:
                        return data.decode(enc)
                    except:
                        continue
                return data.decode('utf-8', errors='ignore')

            out = decode_bytes(result.stdout)
            err = decode_bytes(result.stderr)
            return out.strip() or f"命令执行失败:\n{err.strip()}" if result.returncode != 0 else out.strip()
        except subprocess.TimeoutExpired:
            return "命令执行超时"
        except Exception as e:
            return f"执行出错: {str(e)}"