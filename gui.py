import asyncio
import math
import re
import tkinter as tk
from typing import Optional, List, Dict, Any
import flet as ft
from agent import ReActAgent
from msg import add_message, process_bot_message
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

    def build_agent_info(self):
        avatar = ft.CircleAvatar(
            bgcolor= ft.Colors.BLUE,
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
        try:
            #如果还有任务在执行,这时按的是消取任务键
            if self.current_task and not self.current_task.done():
                self.current_task.cancel()
                try:
                    # 阻塞,我先睡了，你帮我盯着这个任务(cancel任务)，它什么时候搞定了你再叫醒我。
                    await self.current_task
                except asyncio.CancelledError:
                    pass
                # 关键：无论如何都返回，不执行后续发送代码
                return

            #用户如果输入的是空直接返回吧
            user_input = self.input_field.value.strip()
            if not user_input:
                return

            #输入框不可用
            self.input_field.disabled = True
            self.send_button.content = ft.Icon(ft.Icons.STOP, color=ft.Colors.WHITE, size=20)
            self.input_field.value = ""

            #清理一下@符号吧,对AI比较友好
            user_input = re.sub(r'@\S+\s?', '', user_input).strip()


            #新增用户发送的消息到消息队列
            add_message(self.messages, "user", user_input, self.page)
            #_run_send方法开始就是AI真正开始运行了
            self.current_task = asyncio.create_task(self._run_send(user_input))

            await self.current_task #在这里卡住，直到任务完成（或取消）
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

    async def _run_send(self, user_input: str):
        if not self.avatar_container:
            self.build_agent_info()

        print(f"发送消息时使用的 Agent 模型: {self.agent.model}")
        input_tokens, output_tokens = await process_bot_message(
            messages_control=self.messages,
            page=self.page,
            agent=self.agent,
            user_input=user_input
        )
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.update_token_display()

    def build(self):
        page = self.page
        page.title = ClawConst.PAGE_STYLE["title"]
        page.theme_mode = ClawConst.PAGE_STYLE["theme_mode"]
        # 设置页面内容的内边距（单位：像素）
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
            width=170,
            height=30,
            border_radius=20,
            bgcolor=ft.Colors.WHITE,
            on_select=self.on_model_select,
            text_style=ft.TextStyle(size=13, color=ft.Colors.BLACK),
        )

        # 使用 Stack 将两个控件分别悬浮在输入框右下角
        input_with_actions = ft.Stack(
            controls=[
                self.input_field,
                # 发送按钮：位于最右下角，距离右边缘 10px，下边缘 12px
                ft.Container(
                    content=self.send_button,
                    bottom=12,
                    right=13,
                ),
                # 模型下拉框：位于发送按钮左侧，距离右边缘 = 按钮宽度(42) + 间距(8) + 原右距(10) = 60px
                ft.Container(
                    content=self.model_dropdown,
                    bottom=27,
                    right=68,
                ),
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