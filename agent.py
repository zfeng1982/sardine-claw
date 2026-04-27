import os
import re
import json
import asyncio
import subprocess
import shlex
import yaml
from typing import Dict, List, Any, Optional, AsyncGenerator, Tuple
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from const import ClawConst


class ReActAgent:
    """Plan-and-ReAct 机制：先规划任务拆分，每个技能内部最多 ACT_MAX_STEPS 次尝试"""

    def __init__(self, api_key: str, base_url: str, model: str,
                 skills_dir: str = "./skills", skill_names: List[str] = None):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.skills_dir = skills_dir
        self.skill_names = skill_names if skill_names is not None else []
        self.skills = self._load_skills()
        self.command_executor = CommandExecutor()

        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        self._last_prompt_tokens = 0
        self._last_completion_tokens = 0
        self._last_total_tokens = 0

    def _load_skills(self) -> List[Dict[str, Any]]:
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
        docs = []
        for skill in self.skills:
            docs.append(f"## 技能名称：{skill['name']}\n{skill['full_content']}\n")
        return "\n".join(docs)

    def _get_skill_doc(self, skill_name: str) -> str:
        for s in self.skills:
            if s['name'] == skill_name:
                return s['full_content']
        return ""

    async def _generate_plan(self, user_input: str) -> List[Dict[str, str]]:
        """生成任务拆分计划"""
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
            if response.usage:
                self.total_prompt_tokens += response.usage.prompt_tokens
                self.total_completion_tokens += response.usage.completion_tokens
                self.total_tokens += response.usage.total_tokens

            content = response.choices[0].message.content.strip()
            json_match = re.search(r'\{.*\}|\[.*\]', content, re.DOTALL)
            if json_match:
                content = json_match.group(0)
            plan_data = json.loads(content)
            if isinstance(plan_data, dict) and "plan" in plan_data:
                plan = plan_data["plan"]
            elif isinstance(plan_data, list):
                plan = plan_data
            else:
                plan = []
            valid_plan = []
            for step in plan:
                if isinstance(step, dict) and "skill" in step and "command" in step:
                    if any(s['name'] == step['skill'] for s in self.skills):
                        valid_plan.append(step)
                    else:
                        print(f"警告：未加载技能 '{step['skill']}'，已忽略")
            return valid_plan
        except Exception as e:
            print(f"计划生成失败: {e}")
            return []

    async def _execute_command(self, skill_name: str, command: str) -> Tuple[bool, str]:
        """执行单个命令，返回(是否成功, 输出)"""
        skill_dir = None
        for s in self.skills:
            if s['name'] == skill_name:
                skill_dir = s['skill_dir']
                break
        if not skill_dir:
            return False, f"错误：未找到技能 '{skill_name}' 的工作目录"
        cmd = command.replace("{baseDir}", skill_dir)
        try:
            returncode, output = await asyncio.to_thread(self.command_executor.run_with_code, cmd, cwd=skill_dir)
            return (returncode == 0), output
        except Exception as e:
            return False, f"命令执行异常: {str(e)}"

    async def _execute_step_with_react(self, step: Dict[str, str], step_index: int, total_steps: int,
                                       raw_output_holder: List[str]) -> AsyncGenerator[str, None]:
        """单个技能的内部 ReAct 循环，raw_output_holder 用于保存最后一次原始输出"""
        skill_name = step['skill']
        initial_command = step['command']
        skill_doc = self._get_skill_doc(skill_name)
        if not skill_doc:
            yield f"❌ 步骤 {step_index+1} 失败：未找到技能 '{skill_name}' 的文档\n"
            raw_output_holder[0] = ""
            return

        react_prompt = ClawConst.STEP_REACT_PROMPT.format(
            skill_name=skill_name,
            skill_doc=skill_doc,
            task_description=f"初始命令: {initial_command}",
            max_steps=ClawConst.ACT_MAX_STEPS
        )
        messages = [
            {"role": "system", "content": react_prompt},
            {"role": "user", "content": f"任务目标：{initial_command}\n请开始执行，使用 ReAct 格式输出。"}
        ]

        current_command = initial_command
        for attempt in range(ClawConst.ACT_MAX_STEPS):
            yield f"🔄 尝试 {attempt+1}/{ClawConst.ACT_MAX_STEPS}: 执行命令 `{current_command}`\n"
            success, obs = await self._execute_command(skill_name, current_command)
            raw_output_holder[0] = obs   # 保存原始输出
            yield f"📋 观察结果:\n```\n{obs}\n```\n"

            if success:
                yield f"✅ 步骤 {step_index+1} 执行成功\n\n"
                return

            if attempt < ClawConst.ACT_MAX_STEPS - 1:
                yield f"🤔 命令执行失败，请求 LLM 修正...\n"
                messages.append({"role": "assistant", "content": f"Action: execute_command\nAction Input: {json.dumps({'command': current_command})}"})
                messages.append({"role": "user", "content": f"Observation: {obs}\n失败。请给出修正后的命令或输出 Final Answer。"})

                try:
                    response = await self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=ClawConst.MODEL_TEMPERATURE,
                        max_tokens=ClawConst.MODEL_MAX_TOKENS
                    )
                    if response.usage:
                        self.total_prompt_tokens += response.usage.prompt_tokens
                        self.total_completion_tokens += response.usage.completion_tokens
                        self.total_tokens += response.usage.total_tokens

                    llm_output = response.choices[0].message.content.strip()
                    yield f"💡 LLM 建议:\n{llm_output}\n"
                    new_cmd = self._parse_command_from_llm(llm_output)
                    if new_cmd:
                        current_command = new_cmd
                    else:
                        yield f"⚠️ 无法解析新命令，保留原命令\n"
                except Exception as e:
                    yield f"❌ LLM 调用失败: {str(e)}\n"
            else:
                yield f"❌ 步骤 {step_index+1} 在 {ClawConst.ACT_MAX_STEPS} 次尝试后失败\n"
                return

        yield f"❌ 步骤 {step_index+1} 最终失败\n"

    def _parse_command_from_llm(self, text: str) -> Optional[str]:
        """从 LLM 输出中提取命令字符串"""
        # 尝试 JSON 格式
        match = re.search(r'Action:\s*execute_command', text)
        if match:
            idx = text.find("Action Input:")
            if idx != -1:
                start = text.find('{', idx)
                if start != -1:
                    for end in range(len(text), start, -1):
                        try:
                            data = json.loads(text[start:end])
                            if "command" in data:
                                return data["command"]
                        except:
                            continue
        # 尝试直接解析命令
        lines = text.splitlines()
        for line in lines:
            line = line.strip()
            if line.startswith("execute_command"):
                parts = line.split(maxsplit=1)
                if len(parts) > 1:
                    return parts[1]
            elif line.startswith("Action Input:"):
                parts = line.split(maxsplit=2)
                if len(parts) > 2:
                    return parts[2]
        return None

    async def _generate_final_answer(self, user_input: str, plan: List[Dict[str, str]],
                                     successes: List[bool], raw_outputs: List[str]) -> AsyncGenerator[str, None]:
        """将完整的原始输出交给 LLM，让它自行汇总"""
        plan_str = json.dumps(plan, ensure_ascii=False, indent=2)
        results = []
        for i, (ok, out) in enumerate(zip(successes, raw_outputs)):
            status = "✅ 成功" if ok else "❌ 失败"
            results.append(f"## 步骤 {i+1} ({status})\n{out}")
        full_results = "\n\n".join(results)

        prompt = ClawConst.FINAL_ANSWER_PROMPT.format(
            user_input=user_input,
            plan=plan_str,
            execution_results=full_results
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
                    yield delta.replace('\\n', '\n')
            if usage:
                self.total_prompt_tokens += usage.prompt_tokens
                self.total_completion_tokens += usage.completion_tokens
                self.total_tokens += usage.total_tokens
        except Exception as e:
            yield f"生成最终答案失败: {str(e)}"

    async def run_stream(self, user_input: str, max_steps: int = None) -> AsyncGenerator[str, None]:
        if max_steps is None:
            max_steps = ClawConst.ACT_MAX_STEPS

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

        # 2. 执行每个步骤
        successes = []
        raw_outputs = []
        for idx, step in enumerate(plan):
            yield f"## 步骤 {idx+1}/{len(plan)}: {step['skill']} - {step['command'][:80]}...\n"
            raw_holder = [""]
            step_success = False
            async for chunk in self._execute_step_with_react(step, idx, len(plan), raw_holder):
                if "✅ 步骤" in chunk and "执行成功" in chunk:
                    step_success = True
                yield chunk
            successes.append(step_success)
            raw_outputs.append(raw_holder[0])

        # 3. 最终答案
        yield "\n💬 **最终回答**：\n"
        async for chunk in self._generate_final_answer(user_input, plan, successes, raw_outputs):
            yield chunk


class CommandExecutor:
    def run_with_code(self, command: str, cwd: str = None) -> Tuple[int, str]:
        try:
            cmd_list = shlex.split(command)
            result = subprocess.run(cmd_list, cwd=cwd, capture_output=True, text=False, timeout=30)

            def decode(b: bytes) -> str:
                if not b:
                    return ""
                for enc in ['utf-8', 'gbk', 'cp936', 'latin1']:
                    try:
                        return b.decode(enc)
                    except:
                        continue
                return b.decode('utf-8', errors='ignore')

            out = decode(result.stdout)
            err = decode(result.stderr)
            if result.returncode == 0:
                return result.returncode, out.strip() or "命令执行成功（无输出）"
            else:
                return result.returncode, f"命令执行失败 (返回码 {result.returncode}):\n{err.strip() or out.strip()}"
        except subprocess.TimeoutExpired:
            return -1, "命令执行超时"
        except Exception as e:
            return -1, f"执行出错: {str(e)}"

    def run(self, command: str, cwd: str = None) -> str:
        _, out = self.run_with_code(command, cwd)
        return out