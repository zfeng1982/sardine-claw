import asyncio
import math
import re
import tkinter as tk
from typing import Optional, List, Dict, Any
import flet as ft
from agent import ReActAgent
from msg import add_message, get_avatar, parse_text_with_links, process_bot_message, get_color_by_name
from const import ClawConst


class SardineClawGUI:
    def __init__(self, page: ft.Page, agent_name: str, agent_color: str, agent_icon: str,
                 agent: ReActAgent, models: List[Dict], skill_names: List[str], skills_dir: str):
        self.page = page
        self.agent_name = agent_name
        self.agent_color = agent_color
        self.agent_icon = agent_icon
        self.agent = agent
        self.models = models
        self.skill_names = skill_names
        self.skills_dir = skills_dir

        self.input_field = None
        self.send_button = None
        self.model_dropdown = None
        self.messages = None
        self.current_task: Optional[asyncio.Task] = None

        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.token_labels = None

        self.avatar_container: Optional[ft.Container] = None
        self.breathing_task: Optional[asyncio.Task] = None
        self.model_label: Optional[ft.Text] = None

    async def breathe(self, container: ft.Container, base_color: str, period: float = 2.0):
        original_bg = container.bgcolor
        try:
            start_time = asyncio.get_event_loop().time()
            while True:
                now = asyncio.get_event_loop().time()
                elapsed = (now - start_time) % period
                alpha = 0.1 + 0.3 * (0.5 + 0.5 * math.sin(2 * math.pi * elapsed / period))
                color_with_alpha = ft.Colors.with_opacity(alpha, base_color)
                container.bgcolor = color_with_alpha
                self.page.update()
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            container.bgcolor = original_bg
            self.page.update()
            raise

    def build_agent_info(self):
        avatar = ft.CircleAvatar(
            bgcolor=get_color_by_name(self.agent_color),
            content=ft.Icon(ft.Icons.ANDROID if self.agent_icon == "android" else ft.Icons.SMART_TOY,
                            color=ft.Colors.WHITE, size=18),
            radius=20,
        )
        self.avatar_container = ft.Container(content=avatar, border_radius=20)
        name_text = ft.Text(self.agent_name, size=16, weight=ft.FontWeight.BOLD)
        input_label = ft.Text(f"总输入: {self.total_input_tokens}", size=15, color=ft.Colors.BLACK)
        output_label = ft.Text(f"总输出: {self.total_output_tokens}", size=15, color=ft.Colors.BLACK)
        self.token_labels = (input_label, output_label)
        token_row = ft.Row( [input_label, output_label],
            spacing=8,
            alignment=ft.MainAxisAlignment.START,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,)

        self.model_label = ft.Text(f"模型: {self.agent.model}", size=15, color=ft.Colors.BLACK)

        info_row = ft.Row(
            [self.avatar_container, name_text, token_row, self.model_label],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        return ft.Container(content=info_row, padding=ft.Padding.symmetric(horizontal=20, vertical=10))

    def update_token_display(self):
        if self.token_labels:
            input_label, output_label = self.token_labels
            input_label.value = f"总输入: {self.total_input_tokens}"
            output_label.value = f"总输出: {self.total_output_tokens}"
            self.page.update()

    async def switch_model_by_name(self, model_display_name: str):
        print(f"尝试切换模型到: {model_display_name}")
        model_cfg = next((m for m in self.models if m['name'] == model_display_name), None)
        if not model_cfg:
            print(f"未找到模型配置: {model_display_name}")
            add_message(self.messages, "system", f"错误：未找到模型配置 '{model_display_name}'", self.page)
            return False

        try:
            print(f"创建新 Agent: model={model_cfg['model']}")
            new_agent = ReActAgent(
                api_key=model_cfg['api_key'],
                base_url=model_cfg['base_url'],
                model=model_cfg['model'],
                skills_dir=self.skills_dir,
                skill_names=self.skill_names
            )
            self.agent = new_agent
            if self.model_label:
                self.model_label.value = f"模型: {self.agent.model}"
                self.page.update()
            # add_message(self.messages, "system", f"✅ 模型已切换至 {model_display_name} (底层: {self.agent.model})", self.page)
            await self.messages.scroll_to(offset=-1, duration=ClawConst.MESSAGES_SCROLL_DURATION)
            return True
        except Exception as ex:
            error_msg = f"切换模型失败: {str(ex)}"
            print(error_msg)
            add_message(self.messages, "system", f"❌ {error_msg}", self.page)
            return False

    def on_model_select(self, e):
        selected = self.model_dropdown.value
        if not selected:
            return
        print(f"### 下拉框选中模型: {selected}")
        if self.current_task and not self.current_task.done():
            self.current_task.cancel()
            self.current_task = None
            self.send_button.content = ft.Icon(ft.Icons.SEND_ROUNDED, color=ft.Colors.WHITE, size=20)
            self.input_field.disabled = False
            self.page.update()
        asyncio.create_task(self.switch_model_by_name(selected))

    async def send_click(self, e):
        if self.current_task and not self.current_task.done():
            self.current_task.cancel()
            try:
                await self.current_task
            except asyncio.CancelledError:
                pass
            self.current_task = None
            self.send_button.content = ft.Icon(ft.Icons.SEND_ROUNDED, color=ft.Colors.WHITE, size=20)
            self.input_field.disabled = False
            self.page.update()
            return

        user_input = self.input_field.value.strip()
        if not user_input:
            return

        self.input_field.disabled = True
        self.send_button.content = ft.Icon(ft.Icons.STOP, color=ft.Colors.WHITE, size=20)
        self.input_field.value = ""
        self.page.update()

        clean_input = re.sub(r'@\S+\s?', '', user_input).strip()
        if not clean_input:
            clean_input = user_input

        add_message(self.messages, "user", user_input, self.page)

        self.current_task = asyncio.create_task(self._run_send(clean_input))
        try:
            await self.current_task
        except asyncio.CancelledError:
            pass
        finally:
            self.current_task = None
            self.input_field.disabled = False
            self.send_button.content = ft.Icon(ft.Icons.SEND_ROUNDED, color=ft.Colors.WHITE, size=20)
            self.page.update()
            try:
                await self.input_field.focus()
            except:
                pass

    async def _run_send(self, clean_input: str):
        if not self.avatar_container:
            self.build_agent_info()

        print(f"发送消息时使用的 Agent 模型: {self.agent.model}")
        input_tokens, output_tokens = await process_bot_message(
            messages_control=self.messages,
            page=self.page,
            agent=self.agent,
            agent_name=self.agent_name,
            agent_color=self.agent_color,
            clean_input=clean_input,
            breathing_container=self.avatar_container,
            breathe_func=self.breathe,
            get_color_by_name_func=get_color_by_name
        )
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.update_token_display()

    def build(self):
        page = self.page
        page.title = ClawConst.PAGE_STYLE["title"]
        page.theme_mode = ClawConst.PAGE_STYLE["theme_mode"]
        page.padding = ClawConst.PAGE_STYLE["padding"]
        page.bgcolor = ClawConst.PAGE_STYLE["bgcolor"]
        page.window.width = ClawConst.PAGE_STYLE["width"]
        page.window.height = ClawConst.PAGE_STYLE["height"]
        page.window.resizable = ClawConst.PAGE_STYLE["resizable"]
        try:
            root = tk.Tk()
            screen_width = root.winfo_screenwidth()
            screen_height = root.winfo_screenheight()
            root.destroy()
            page.window.left = (screen_width - page.window.width) // 2
            page.window.top = (screen_height - page.window.height) // 2
        except:
            pass

        header = self.build_agent_info()
        self.messages = ft.ListView(expand=True, spacing=12, auto_scroll=True, padding=20)

        # 输入框，底部内边距留出空间给悬浮控件
        self.input_field = ft.TextField(
            hint_text="输入消息...",
            expand=True,
            multiline=True,
            min_lines=5,
            max_lines=5,
            shift_enter=True,
            border_radius=20,
            filled=True,
            fill_color=ft.Colors.WHITE,
            border=ft.InputBorder.OUTLINE,
            border_width=0.5,
            border_color=ft.Colors.GREY_400,
            content_padding=ft.Padding(left=15, right=15, top=10, bottom=60),  # 修正：直接构造 Padding
            on_submit=lambda e: asyncio.create_task(self.send_click(e)),
        )

        # 发送按钮
        self.send_button = ft.Container(
            content=ft.Icon(ft.Icons.SEND_ROUNDED, color=ft.Colors.WHITE, size=20),
            width=42,
            height=42,
            bgcolor=ft.Colors.GREEN_500,
            border_radius=20,
            on_click=lambda e: asyncio.create_task(self.send_click(e)),
            ink=True,
        )

        # 模型下拉框，宽度160，高度40
        model_options = [ft.dropdown.Option(m['name']) for m in self.models]
        self.model_dropdown = ft.Dropdown(
            options=model_options,
            value=self.models[0]['name'] if self.models else None,
            width=200,
            height=40,
            border_radius=20,
            bgcolor=ft.Colors.WHITE,
            on_select=self.on_model_select,
        )

        # 操作行，垂直居中
        input_actions = ft.Row(
            [self.model_dropdown, self.send_button],
            spacing=8,
            alignment=ft.MainAxisAlignment.END,
            vertical_alignment=ft.CrossAxisAlignment.CENTER
        )

        # 使用 Stack 将操作行悬浮在输入框右下角
        input_with_actions = ft.Stack(
            controls=[
                self.input_field,
                ft.Container(content=input_actions, bottom=12, right=10),
            ],
            expand=True,
        )

        chat_content = ft.Column(
            [
                header,
                ft.Container(content=self.messages, expand=True, bgcolor=ft.Colors.GREY_50),
                ft.Container(
                    content=input_with_actions,
                    padding=ft.Padding.only(left=15, right=15, top=10, bottom=15),
                    bgcolor=ft.Colors.WHITE,
                    border=ft.Border(top=ft.BorderSide(1, ft.Colors.GREY_200)),
                ),
            ],
            expand=True,
            spacing=0,
        )

        page.add(ft.Container(content=chat_content, expand=True, bgcolor=ft.Colors.WHITE))