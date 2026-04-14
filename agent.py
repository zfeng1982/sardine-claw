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
    """实现ReAct机制的Agent，支持指定技能包加载"""

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

    async def _select_skill(self, user_input: str) -> Optional[Dict[str, Any]]:
        if not self.skills:
            return None
        skills_desc = "\n".join([f"- {s['name']}: {s['description']}" for s in self.skills])

        select_prompt = ClawConst.SKILL_SELECT_PROMPT.format(user_input=user_input, skills_desc=skills_desc)

        try:
            print("_select_skill request llm")
            response = await self.client.chat.completions.create(
                model=self.model, messages=[{"role": "user", "content": select_prompt}],
                temperature=ClawConst.MODEL_TEMPERATURE, max_tokens=ClawConst.MODEL_MAX_TOKENS
            )
            # 累加 token 用量（非流式调用）
            if response.usage:
                self.total_prompt_tokens += response.usage.prompt_tokens
                self.total_completion_tokens += response.usage.completion_tokens
                self.total_tokens += response.usage.total_tokens

            chosen = response.choices[0].message.content.strip()
            # print(f"{__file__}||response:{response}")
            print(f"_select_skill response chose:{chosen}")
            if not chosen or chosen == '' or chosen.lower() == "none":
                return None
            for s in self.skills:
                if chosen.lower() in s['name'].lower():
                    return s
            return None
        except Exception as e:
            print(f"技能选择错误: {e}")
            return None

    def _build_system_prompt_with_skill(self, skill: Dict[str, Any]) -> str:
        """构建包含完整技能文档的系统提示，并强制规定输出格式"""
        skill_doc = skill['full_content']
        return ClawConst.SKILL_DOC_PROMPT.format(skill_name=skill['name'], skill_doc=skill_doc)

    async def _call_llm_stream(self, messages: List[ChatCompletionMessageParam]) -> AsyncGenerator[str, None]:
        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=ClawConst.MODEL_TEMPERATURE,
                max_tokens=ClawConst.MODEL_MAX_TOKENS,
                stream=True,
                stream_options={"include_usage": True}  # 强制返回 usage
            )
            usage = None
            async for chunk in stream:
                # 处理 usage 块（没有 choices）
                if chunk.usage:
                    usage = chunk.usage
                    continue  # 这个 chunk 没有内容，跳过
                # 处理正常内容块
                if chunk.choices and len(chunk.choices) > 0 and chunk.choices[0].delta.content:
                    delta = chunk.choices[0].delta.content
                    delta = delta.replace('\\n', '\n').replace('<br>', '\n').replace('\\r\\n', '\n')
                    yield delta
            # 保存本次调用的 token 用量
            if usage:
                self._last_prompt_tokens = usage.prompt_tokens
                self._last_completion_tokens = usage.completion_tokens
                self._last_total_tokens = usage.total_tokens
            else:
                # 降级：如果仍然没有 usage（某些兼容 API 可能不支持），设为 0
                self._last_prompt_tokens = self._last_completion_tokens = self._last_total_tokens = 0
        except Exception as e:
            yield f"LLM调用错误: {str(e)}"
            self._last_prompt_tokens = self._last_completion_tokens = self._last_total_tokens = 0

    async def _parse_action(self, llm_output: str) -> Optional[tuple]:
        action_match = re.search(r'Action:\s*(\w+)', llm_output)
        if not action_match:
            return None
        idx = llm_output.find("Action Input:")
        if idx == -1:
            return None
        start = llm_output.find('{', idx)
        if start == -1:
            return None
        action_input = None
        for end in range(len(llm_output), start, -1):
            try:
                action_input = json.loads(llm_output[start:end])
                break
            except:
                continue
        if action_input is None:
            return None
        return action_match.group(1), action_input

    async def _execute_action(self, action: str, action_input: Any, skill_dir: str) -> str:
        if action == "execute_command":
            cmd = action_input.get("command", "") if isinstance(action_input, dict) else str(action_input)
            cmd = cmd.replace("{baseDir}", skill_dir)
            try:
                result = await asyncio.to_thread(self.command_executor.run, cmd, cwd=skill_dir)
                return f"Observation: {result}"
            except Exception as e:
                return f"Observation: 命令执行失败: {str(e)}"
        return f"Observation: 未知动作 '{action}'"

    async def run_stream(self, user_input: str, max_steps: int = 5) -> AsyncGenerator[str, None]:
        if not self.skills:
            yield "抱歉，我还没学习任何技能。"
            return
        selected_skill = await self._select_skill(user_input)
        if not selected_skill:
            yield "抱歉，我还没有对应的技能。"
            return

        system_prompt = self._build_system_prompt_with_skill(selected_skill)
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_input}]
        step = 0
        while step < max_steps:
            step_output = ""
            print(f"step:{step} _call_llm_stream request llm ")
            async for chunk in self._call_llm_stream(messages):
                step_output += chunk
                yield chunk
            # 累加本次流式调用的 token 用量
            self.total_prompt_tokens += self._last_prompt_tokens
            self.total_completion_tokens += self._last_completion_tokens
            self.total_tokens += self._last_total_tokens

            messages.append({"role": "assistant", "content": step_output})
            yield f"{ClawConst.ACT_END}"
            if "\n" not in step_output:
                print("LLM存在结束后没有换行的情况加了一个换行")
                yield f"\n"

            if "Final Answer:" in step_output:
                return

            parsed = await self._parse_action(step_output)
            if parsed:
                print(f"step:{step} _execute_action:{ parsed[1].get("command", "")}....")
                obs = await self._execute_action(parsed[0], parsed[1], selected_skill['skill_dir'])
                print("_execute_action end")
                # yield f"\n\n[系统] {obs}\n\n"
                # print(f"[obs]{obs}")
                messages.append({"role": "user", "content": obs})
            else:
                # yield "\n\n[系统] 未能解析动作，请检查输出格式。\n\n"
                print("[obs]未能解析动作，请检查输出格式。")
                messages.append({"role": "user", "content": "请按照ReAct格式输出。"})

            step += 1


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