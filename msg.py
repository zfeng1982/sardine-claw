import re
import flet as ft
import asyncio
import time
from const import ClawConst
from agent import ReActAgent

def get_color_by_name(color_name: str):
    color_map = {
        "green": ft.Colors.GREEN,
        "blue": ft.Colors.BLUE,
        "purple": ft.Colors.PURPLE,
        "red": ft.Colors.RED,
        "orange": ft.Colors.ORANGE,
        "yellow": ft.Colors.YELLOW,
    }
    return color_map.get(color_name.lower(), ft.Colors.GREY)

def parse_text_with_links(text, page):
    url_pattern = r'https?://[^\s]+'
    spans = []
    last_end = 0
    for match in re.finditer(url_pattern, text):
        start, end = match.span()
        if start > last_end:
            spans.append(ft.TextSpan(text[last_end:start]))
        url = match.group()
        def open_url(e, u=url):
            asyncio.create_task(page.launch_url(u))
        spans.append(ft.TextSpan(
            text=url,
            style=ft.TextStyle(color=ft.Colors.BLUE, decoration=ft.TextDecoration.UNDERLINE),
            on_click=open_url
        ))
        last_end = end
    if last_end < len(text):
        spans.append(ft.TextSpan(text[last_end:]))
    return spans

def get_avatar(role, member_info=None):
    if role == "assistant" and member_info:
        color = get_color_by_name(member_info.get("color", "grey"))
        icon = member_info.get("avatar", ft.Icons.ANDROID)
    else:
        color = ft.Colors.BLUE
        icon = ft.Icons.PERSON
    return ft.CircleAvatar(
        bgcolor=color,
        content=ft.Icon(icon, color=ft.Colors.WHITE, size=18),
        radius=16,
    )

def add_message(messages_control, role: str, content: str, page: ft.Page, member_info=None):
    is_user = role == "user"
    is_system = role == "system"
    if re.search(r'https?://', content):
        spans = parse_text_with_links(content, page)
        text_widget = ft.Text(spans=spans, selectable=True, size=14)
    else:
        text_widget = ft.Text(content, selectable=True, size=14)

    if is_system:
        bubble = ft.Container(
            content=text_widget,
            bgcolor=ft.Colors.GREY_200,
            border_radius=ft.BorderRadius.all(15),
            padding=ft.Padding.symmetric(horizontal=15, vertical=8),
            width=ClawConst.BUBBLE_STYLE['width'],
        )
        row = ft.Row([bubble], alignment=ft.MainAxisAlignment.CENTER)
    else:
        bubble = ft.Container(
            content=text_widget,
            bgcolor=ft.Colors.GREEN_100 if is_user else ft.Colors.WHITE,
            **ClawConst.BUBBLE_STYLE,
        )
        if is_user:
            avatar = get_avatar(role)
            row = ft.Row([bubble, avatar], alignment=ft.MainAxisAlignment.END, vertical_alignment=ft.CrossAxisAlignment.START, spacing=10)
        else:
            avatar = get_avatar(role, member_info)
            row = ft.Row([avatar, bubble], alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.START, spacing=10)
    messages_control.controls.append(ft.Container(content=row))
    page.update()

async def process_bot_message(messages_control: ft.ListView,
                              page: ft.Page,
                              agent: ReActAgent,
                              agent_name: str,
                              agent_color: str,
                              clean_input: str,
                              breathing_container: ft.Container,
                              breathe_func,
                              get_color_by_name_func) -> tuple:
    start_time = time.time()
    message_content = ft.Text("正在思考...", **ClawConst.BUBBLE_BOT_THOUGHT_FONT)
    model_info = ft.Text(f"{agent_name} · 模型: {agent.model}", size=11, color=ft.Colors.GREY_500, selectable=True)
    bubble_column = ft.Column([message_content, model_info], spacing=4, horizontal_alignment=ft.CrossAxisAlignment.START)
    assistant_bubble = ft.Container(content=bubble_column, bgcolor=ft.Colors.WHITE, **ClawConst.BUBBLE_STYLE)
    robot_avatar = get_avatar("assistant", {"color": agent_color, "avatar": ft.Icons.ANDROID})
    message_row = ft.Container(content=ft.Row([robot_avatar, assistant_bubble], alignment=ft.MainAxisAlignment.START, spacing=10))
    messages_control.controls.append(message_row)
    page.update()

    breathing_task = asyncio.create_task(
        breathe_func(breathing_container, get_color_by_name_func(agent_color), period=2.0)
    )

    full_response = ""
    try:
        is_first_chunk = True
        async for chunk in agent.run_stream(clean_input, ClawConst.ACT_MAX_STEPS):
            full_response += chunk.replace(ClawConst.ACT_END, "")
            if is_first_chunk:
                message_content.value = chunk
                is_first_chunk = False
            else:
                message_content.value = full_response

            if re.search(r'https?://', full_response):
                spans = parse_text_with_links(full_response, page)
                new_content = ft.Text(spans=spans, **ClawConst.BUBBLE_BOT_THOUGHT_FONT)
                bubble_column.controls[0] = new_content
                message_content = new_content

            if any(chunk.endswith(c) for c in ('.', '!', '?', '\n', '\t', ',')):
                await messages_control.scroll_to(offset=-1, duration=ClawConst.MESSAGES_SCROLL_DURATION)
                page.update()

            if ClawConst.ACT_END in chunk and "Final Answer:" not in full_response:
                await asyncio.sleep(2)
                assistant_bubble.opacity = 0
                full_response = ""
                message_content.value = "指令执行中..."
                assistant_bubble.opacity = 1
                page.update()
    except asyncio.CancelledError:
        message_content.value = "已取消"
        message_content.color = ft.Colors.GREY_500
        model_info.value += " (已取消)"
        page.update()
    except Exception as ex:
        message_content.value = f"Error: {str(ex)}"
        message_content.color = ft.Colors.RED
        page.update()
    finally:
        breathing_task.cancel()
        await messages_control.scroll_to(offset=-1, duration=ClawConst.MESSAGES_SCROLL_DURATION)
        message_content.color = ft.Colors.BLACK
        page.update()

    input_tokens = agent.total_prompt_tokens
    output_tokens = agent.total_completion_tokens
    if input_tokens == 0 and output_tokens == 0:
        input_tokens = max(1, len(clean_input) // 2)
        output_tokens = max(1, len(full_response) // 2)
    model_info.value += f" · Token: {input_tokens+output_tokens}"
    elapsed = time.time() - start_time
    model_info.value += f" · 耗时: {elapsed:.2f}s"
    return input_tokens, output_tokens