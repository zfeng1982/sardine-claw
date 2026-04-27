import os
import re
import json
import asyncio
import subprocess
import shlex
import tempfile
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
        MAX_CHARS = 4000
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
            print(f"==== cmd:{cmd}")
            print(f"==== skill_dir:{skill_dir}")
            returncode, output = await asyncio.to_thread(self.command_executor.run_with_code, cmd, cwd=skill_dir)
            return (returncode == 0), output
        except Exception as e:
            return False, f"命令执行异常: {str(e)}"

    async def _postprocess_output(self, skill_name: str, output: str, skill_dir: str) -> str:
        """
        让 LLM 阅读技能文档和 scripts/ 内容，自主生成 Bash 脚本处理后处理。
        返回处理后的输出；如果不需要处理，返回原输出。
        """
        skill_doc = self._get_skill_doc(skill_name)
        if not skill_doc:
            return output

        scripts_content = self._get_scripts_content(skill_dir)
        prompt = f"""你是一个智能助手。以下是技能的文档和 scripts/ 目录下的脚本内容，以及执行命令后得到的原始输出。

## 技能文档
{skill_doc}

## scripts/ 目录文件内容
{scripts_content}

## 原始输出（前 800 字符）
{output[:800]}

**任务**：
判断是否需要对原始输出进行后处理（例如解密、解码、格式转换、数据清洗等）。
如果需要，请编写一个 **Bash 脚本**，该脚本能够从标准输入读取原始输出，并将处理后的结果输出到标准输出。

你可以：
- 直接调用 `scripts/` 下的现有脚本（具体命令需从脚本内容推断）。
- 根据脚本中的函数实现，动态生成一段新代码（Python、Node.js、Shell 等），然后执行它来处理数据。
- 组合多个命令，必要时创建临时文件（确保执行后清理）。

**要求**：
- 如果不需要任何处理，只输出 `NOPROCESS`。
- 否则，输出一个**完整的、可执行的 Bash 脚本**（可以包含多行）。不要添加任何额外解释。
- 脚本必须能正确处理 stdin 输入，并输出结果到 stdout。
- 脚本应假设当前工作目录为技能根目录 `{skill_dir}`。

**输出格式**：
- 不需要处理：`NOPROCESS`
- 需要处理：直接输出 Bash 脚本内容
"""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=800
            )
            answer = response.choices[0].message.content.strip()
            if answer == "NOPROCESS":
                return output

            # 将 LLM 输出的脚本保存为临时文件并执行
            with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
                f.write("#!/bin/bash\n")
                f.write(answer)
                script_path = f.name
            os.chmod(script_path, 0o700)

            proc = await asyncio.create_subprocess_exec(
                script_path,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=skill_dir
            )
            stdout, stderr = await proc.communicate(input=output.encode('utf-8'))
            if proc.returncode == 0:
                processed = stdout.decode('utf-8')
                print("后处理成功")
                return processed
            else:
                print(f"后处理失败: {stderr.decode()}")
                return output
        except Exception as e:
            print(f"后处理异常: {e}")
            return output
        finally:
            try:
                os.unlink(script_path)
            except:
                pass

    async def _validate_result_with_llm(self, skill_name: str, task_description: str, command: str, output: str, skill_dir: str) -> Tuple[bool, Optional[str]]:
        """
        让 LLM 参考技能文档和 scripts 内容，判断输出是否达成了任务目标。
        返回 (是否成功, 如果是失败可选的修正命令)
        """
        skill_doc = self._get_skill_doc(skill_name)
        scripts_content = self._get_scripts_content(skill_dir)
        output_preview = output[:1000] if len(output) > 1000 else output
        prompt = f"""你是一个严格的结果验证专家。以下是技能相关信息、执行的命令和输出，请判断是否达成了任务目标。

技能名称：{skill_name}
技能文档：
{skill_doc}

scripts/ 目录下的脚本内容（供参考，可能包含解密/处理逻辑）：
{scripts_content}

任务描述：{task_description}
执行的命令：{command}
命令输出（前1000字符）：
{output_preview}

判断标准（按优先级）：
1. **可读性**：输出是否是人类可读的明文，而不是乱码、Base64 长串、明显加密的数据？如果是加密或乱码，认定为失败。
2. **格式符合性**：输出格式是否符合技能文档中描述的预期格式（例如 JSON、纯文本表格等）？如果不符合，认定为失败。
3. **内容完整性**：输出是否包含了任务描述中要求的关键信息？例如查询天气应有温度、天气状况；查询热点应有标题和热度；搜索图片应有图片链接等。关键信息缺失则失败。
4. **错误状态**：如果命令执行失败（返回错误信息、返回码非0），认定为失败。
5. **后处理需求**：如果输出看起来需要进一步处理（例如文档中明确提到“需要对字段解密”，且脚本中提供了解密函数），则认定为失败，并应建议执行解密/处理命令。

请严格按照以下格式输出：
- 如果成功：只输出 "SUCCESS"
- 如果失败：输出 "FAILED: 原因" （简要说明原因），然后另起一行，如果可能，给出修正建议的命令，格式为：
  Action: execute_command
  Action Input: {{"command": "修正后的完整命令"}}

示例：
成功：SUCCESS
失败：FAILED: 输出为加密乱码，需要解密。
Action: execute_command
Action Input: {{"command": "python3 scripts/tool.py xor_decrypt"}}
失败：FAILED: 返回空结果，可能参数错误。
Action: execute_command
Action Input: {{"command": "curl 'http://119.29.63.139/xhs/get_hot_topic?page=1'"}}

只输出上述格式，不要添加额外解释。
"""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
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
                # 尝试提取修正命令
                match = re.search(r'Action:\s*execute_command\s+Action Input:\s*({.*?})', answer, re.IGNORECASE | re.DOTALL)
                if match:
                    try:
                        cmd_json = json.loads(match.group(1))
                        new_cmd = cmd_json.get("command")
                        return False, new_cmd
                    except:
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
            yield f"❌ 步骤 {step_index+1} 失败：未找到技能 '{skill_name}' 的文档或目录\n"
            raw_output_holder[0] = ""
            return

        react_prompt = ClawConst.STEP_REACT_PROMPT.format(
            skill_name=skill_name,
            skill_doc=skill_doc,
            task_description=f"任务: {task_description}\n初始命令: {initial_command}",
            max_steps=ClawConst.ACT_MAX_STEPS
        )
        messages = [
            {"role": "system", "content": react_prompt},
            {"role": "user", "content": f"请执行任务并遵循 ReAct 格式。任务目标：{task_description}\n初始命令：{initial_command}"}
        ]

        current_command = initial_command
        for attempt in range(ClawConst.ACT_MAX_STEPS):
            yield f"🔄 尝试 {attempt+1}/{ClawConst.ACT_MAX_STEPS}: 执行命令 `{current_command}`\n"
            success, obs = await self._execute_command(skill_name, current_command)
            raw_output_holder[0] = obs

            processed_obs=obs
            # # 后处理（如果需要）
            # processed_obs = await self._postprocess_output(skill_name, obs, skill_dir)
            # if processed_obs != obs:
            #     yield f"🔧 后处理完成\n"

            yield f"📋 观察结果:\n```\n{processed_obs}\n```\n"
            yield f"🤔 正在验证结果是否符合预期...\n"

            is_good, new_cmd = await self._validate_result_with_llm(skill_name, task_description, current_command, processed_obs, skill_dir)
            if is_good:
                yield f"✅ 步骤 {step_index+1} 执行成功（LLM 确认结果有效）\n\n"
                raw_output_holder[0] = processed_obs  # 使用处理后的输出作为最终结果
                return

            if attempt < ClawConst.ACT_MAX_STEPS - 1:
                if new_cmd:
                    current_command = new_cmd
                    yield f"💡 LLM 建议修正命令: {new_cmd}\n"
                else:
                    yield f"⚠️ 结果未达标，请求 LLM 生成修正命令...\n"
                    messages.append({"role": "assistant", "content": f"Action: execute_command\nAction Input: {json.dumps({'command': current_command})}"})
                    messages.append({"role": "user", "content": f"Observation: {processed_obs}\n上述结果不符合任务目标，请给出修正后的命令或输出 Final Answer 终止任务。"})
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
                            yield f"⚠️ 无法解析新命令，将重试原命令\n"
                    except Exception as e:
                        yield f"❌ LLM 调用失败: {str(e)}\n"
            else:
                yield f"❌ 步骤 {step_index+1} 在 {ClawConst.ACT_MAX_STEPS} 次尝试后仍未达成目标，放弃。\n"
                return

        yield f"❌ 步骤 {step_index+1} 最终失败\n"

    def _parse_command_from_llm(self, text: str) -> Optional[str]:
        """从 LLM 输出中提取命令字符串"""
        # 尝试 JSON 格式
        match = re.search(r'Action:\s*execute_command', text, re.IGNORECASE)
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
        lines = text.splitlines()
        for line in lines:
            line = line.strip()
            if line.lower().startswith("execute_command"):
                parts = line.split(maxsplit=1)
                if len(parts) > 1:
                    return parts[1]
            elif line.lower().startswith("action input:"):
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

            if result.returncode == 0:
                output = out.strip() or "命令执行成功（无输出）"
                return result.returncode, output
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