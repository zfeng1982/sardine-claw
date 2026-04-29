import os
import re
import json
import asyncio
import string
import subprocess
import shlex
import tempfile
import time

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
            skill_dir = os.path.join(self.skills_dir, entry).replace('\\', '/')
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

    def _get_scripts_content(self, skill_dir: str) -> str:
        """收集 skills/scripts 目录下文件的内容（限制总长度）"""
        scripts_dir = os.path.join(skill_dir, "scripts")
        pieces = []
        total_len = 0
        MAX_CHARS = 5000
        if os.path.isdir(scripts_dir):
            for filename in sorted(os.listdir(scripts_dir)):
                filepath = os.path.join(scripts_dir, filename)
                if os.path.isfile(filepath):
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            content = f.read()
                        if len(content) > 1500:
                            content = content[:1500] + "\n... (truncated)"
                        block = f"### {filename}\n```\n{content}\n```\n"
                        if total_len + len(block) > MAX_CHARS:
                            pieces.append("### ... (more files omitted due to length)")
                            break
                        pieces.append(block)
                        total_len += len(block)
                    except Exception:
                        continue
        return "\n".join(pieces) if pieces else "（scripts/ 目录为空或不存在）"

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

    def extract_json(self,text:str):
        start = text.find('{')
        if start == -1:
            return None
        count = 0
        in_str = False
        escape = False
        for i, ch in enumerate(text[start:], start):
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
            elif not in_str:
                if ch == '{':
                    count += 1
                elif ch == '}':
                    count -= 1
                    if count == 0:
                        return text[start:i + 1]
        return None
    async def _validate_result_with_llm(self, prompt: str) -> Tuple[bool, Optional[str]]:

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

            answer = response.choices[0].message.content.strip().lower()
            if answer.startswith("success"):
                return True, None
            else:
                json_str  = self.extract_json(answer)
                if json_str :
                    try:
                        cmd_json = json.loads(json_str)
                        new_cmd = cmd_json.get("command")
                        return False, new_cmd
                    except Exception as e:
                        print(f"LLM验证cmd_json失败: {e}")
                        pass
                return False, None
        except Exception as e:
            print(f"LLM 验证失败: {e}")
            return False, None

    def _manual_syntax_check(self,cmd:str):
        # triggers = ("python -c", "python3 -c")
        # if any(t in cmd for t in triggers):
        #     for old, new in {
        #         "false": "False",
        #         "true": "True",
        #         "none": "None",
        #     }.items():
        #         cmd = re.sub(rf"\b{old}\b", new, cmd, flags=re.IGNORECASE)
        # return cmd
        return cmd.replace("false","False").replace("true","True").replace("none","None")


    async def _llm_syntax_check(self,prompt:str):
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个命令行验证与修正专家。严格按照用户提供的规则执行验证。"
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=ClawConst.MODEL_TEMPERATURE,
                max_tokens=ClawConst.MODEL_MAX_TOKENS
            )
            if response.usage:
                self.total_prompt_tokens += response.usage.prompt_tokens
                self.total_completion_tokens += response.usage.completion_tokens
                self.total_tokens += response.usage.total_tokens

            answer = response.choices[0].message.content.strip().lower()
            print(f"answer:{answer}")
            if answer.startswith("success"):
                return True, None
            else:
                json_str = self.extract_json(answer)
                if json_str:
                    try:
                        cmd_json = json.loads(json_str)
                        new_cmd = cmd_json.get("command")
                        return False, new_cmd
                    except Exception as e:
                        print(f"_syntax_check失败: {e}")
                        pass
                return False, None
        except Exception as e:
            print(f"LLM 验证失败: {e}")
            return False, None

    async def _execute_step_with_react(self, step: Dict[str, str], step_index: int, total_steps: int,
                                       raw_output_holder: List[str]) -> AsyncGenerator[str, None]:
        skill_name = step['skill']
        initial_command = step['command']
        task_description = step.get('description', initial_command)
        skill_doc = self._get_skill_doc(skill_name)
        skill_dir = None
        for s in self.skills:
            if s['name'] == skill_name:
                skill_dir = s['skill_dir']
                break
        if not skill_doc or not skill_dir:
            yield f"❌ 步骤 {step_index} 失败：未找到技能 '{skill_name}' 的文档或目录"
            raw_output_holder[0] = ""
            return

        # react_prompt = ClawConst.STEP_REACT_PROMPT.format(
        #     skill_name=skill_name,
        #     skill_doc=skill_doc,
        #     task_description=f"任务: {task_description}\n初始命令: {initial_command}",
        #     max_steps=ClawConst.ACT_MAX_STEPS
        # )
        # messages = [
        #     {"role": "system", "content": react_prompt},
        #     {"role": "user", "content": f"请执行任务并遵循 ReAct 格式。任务目标：{task_description}\n初始命令：{initial_command}"}
        # ]
        skill_doc = self._get_skill_doc(skill_name)
        scripts_content = self._get_scripts_content(skill_dir)

        current_command = initial_command
        exehistory=""
        validateResultprompt = ClawConst.VALIDATE_RESULT_PROMPT.format(skill_name=skill_name, skill_doc=skill_doc,
                                                                       scripts_content=scripts_content)
        for attempt in range(ClawConst.ACT_MAX_STEPS):
            #命令行语法检查提示词
            syntaxCheckPrompt = ClawConst.SYNTAX_CHECK_PROMPT.format(command=current_command)+exehistory
            print(f"===========================================attempt:{attempt}")
            subStep=f"{step_index}-{attempt+1}."
            # print(f"validateResultprompt---:\n{validateResultprompt}")
            print(f"{subStep}syntaxCheckPrompt---:\n{syntaxCheckPrompt}")
            yield f"🤔 {subStep}CLI语法验证中...\n"
            # LLM对命令进行修改
            syntaxPass,new_cmd  =await self._llm_syntax_check(syntaxCheckPrompt)

            if not syntaxPass:
                yield f"❎ {subStep}CLI验证不通过,修正命令\n"
                print(f"{subStep}current_command存在语法错误:{current_command}")
                print(f"             替换成new_cmd:{new_cmd}")
                current_command=new_cmd
            else:
                yield f"✅ {subStep}CLI验证通过\n"
            #手动修改命令
            current_command = self._manual_syntax_check(current_command)
            print(f"🔄 {subStep}尝试:执行命令 `{current_command}`\n")
            yield f"🔄 {subStep}开始执行CLI...\n"
            success, obs = await self._execute_command(skill_name, current_command)
            raw_output_holder[0] = obs

            print(f"📋 {subStep}观察结果:\n```\n{obs}\n```\n")
            yield f"🤔 {subStep}CLI执行完成,LLM正在验证OBS结果是否符合预期...\n"
            exehistory=exehistory+f"\n第{attempt+1}次执行的命令：{current_command}\n命令执行结果：{obs} \n---"
            validateResultprompt=validateResultprompt+f"\n第{attempt+1}次执行的命令：{current_command}\n命令执行结果：{obs} \n---"

            is_good, new_cmd = await self._validate_result_with_llm(validateResultprompt)
            if is_good:
                yield f"✅ 步骤{step_index}执行成功({subStep})\n"
                raw_output_holder[0] = obs  # 使用处理后的输出作为最终结果
                return
            else:
                yield f"❎ {subStep}LLM验证OBS结果不符合预期需要进一步处理\n"
            if attempt < ClawConst.ACT_MAX_STEPS - 1:
                if new_cmd:
                    current_command = new_cmd
                    print(f"💡  {subStep}LLM 建议进一步处理的CLI: {current_command}\n")
                else:
                    print(f"⚠️ {subStep}LLM未给出进一步处理的CLI,再次让LLM验证 new_cmd:{new_cmd}\n")
            else:
                yield f"❌ {subStep}在{ClawConst.ACT_MAX_STEPS} 次尝试后仍未达成目标，放弃。\n"
                return

        yield f"❌ 步骤{step_index}最终失败\n"

    # def _parse_command_from_llm(self, text: str) -> Optional[str]:
    #     """从 LLM 输出中提取命令字符串"""
    #     # 尝试 JSON 格式
    #     match = re.search(r'Action:\s*execute_command', text, re.IGNORECASE)
    #     if match:
    #         idx = text.find("Action Input:")
    #         if idx != -1:
    #             start = text.find('{', idx)
    #             if start != -1:
    #                 for end in range(len(text), start, -1):
    #                     try:
    #                         data = json.loads(text[start:end])
    #                         if "command" in data:
    #                             return data["command"]
    #                     except:
    #                         continue
    #     lines = text.splitlines()
    #     for line in lines:
    #         line = line.strip()
    #         if line.lower().startswith("execute_command"):
    #             parts = line.split(maxsplit=1)
    #             if len(parts) > 1:
    #                 return parts[1]
    #         elif line.lower().startswith("action input:"):
    #             parts = line.split(maxsplit=2)
    #             if len(parts) > 2:
    #                 return parts[2]
    #     return None

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
        yield "📋 正在分析需求并生成执行计划...\n"
        plan = await self._generate_plan(user_input)
        if not plan:
            yield "❌ 未生成有效计划，请检查技能配置或重新描述需求。\n"
            return

        todolist=""
        for idx, step in enumerate(plan):
            todolist=todolist+f"➡️ 步骤{idx+1}.使用技能[{step['skill']}]\n"

        yield f"✅ 执行计划生成完成,需要{len(plan)}步\n{todolist}"
        #停顿一下
        time.sleep(10)
        print(f"执行计划：\n```json\n{json.dumps(plan, ensure_ascii=False, indent=2)}\n```\n")

        # 2. 执行每个步骤
        successes = []
        raw_outputs = []
        for idx, step in enumerate(plan):
            # yield f"步骤{idx+1}/{len(plan)}: 技能[{step['skill']}] 命令[{step['command'][:35]}...]\n"
            raw_holder = [""]
            step_success = False
            async for chunk in self._execute_step_with_react(step, idx+1, len(plan), raw_holder):
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
            # Windows 上推荐使用 shell=True 避免分割问题，但需注意命令注入风险（可接受，因来自 LLM）。
            # 若需保留列表形式，可改为：
            # cmd_list = shlex.split(command, posix=False)  # Windows 模式
            result = subprocess.run(
                command,
                shell=True,  # 让系统解释器处理命令，避免分割错误
                cwd=cwd,
                capture_output=True,
                text=False,
                timeout=30
            )

            def decode(b: bytes) -> str:
                if not b:
                    return ""
                for enc in ['utf-8', 'gbk', 'cp936', 'latin1']:
                    try:
                        return b.decode(enc)
                    except UnicodeDecodeError:
                        continue
                # 最终降级，用替换符代替无法解码的字节
                return b.decode('utf-8', errors='replace')

            out = decode(result.stdout)
            err = decode(result.stderr)
            # print(f"DEBUG: stdout={out[:200]}, stderr={err[:200]}, returncode={result.returncode}")
            if result.returncode == 0:
                out = decode(result.stdout)
                err = decode(result.stderr)
                if out.strip():
                    return result.returncode, out.strip()
                elif err.strip():
                    # 命令认为成功但无输出，且 stderr 有错误信息 —— 可能是静默失败
                    return -1, f"命令无输出，但 stderr 有内容:\n{err.strip()}"
                else:
                    return result.returncode, "命令执行成功（无输出）"
            else:
                # 优先使用 stderr，其次使用 stdout
                error_details = err.strip() or out.strip()
                if not error_details:
                    error_details = f"无任何输出信息。返回码 {result.returncode}"
                return result.returncode, f"命令执行失败 (返回码 {result.returncode}):\n{error_details}"
        except subprocess.TimeoutExpired:
            return -1, "命令执行超时"
        except Exception as e:
            return -1, f"执行出错: {str(e)}"

    def run(self, command: str, cwd: str = None) -> str:
        _, out = self.run_with_code(command, cwd)
        return out