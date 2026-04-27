import flet as ft

class ClawConst:
    BOT_MAX_COUNT = 5
    ACT_END = "|oneactstepend|"
    ACT_MAX_STEPS = 5                     # 每个技能内部最大尝试次数

    MODEL_MAX_TOKENS = 8000
    MODEL_TEMPERATURE = 0.7

    PAGE_STYLE = {
        'title': "AI Friend",
        'theme_mode': ft.ThemeMode.LIGHT,
        'padding': 2,
        'bgcolor': ft.Colors.GREY_50,
        'width': 1080,
        'height': 1000,
        'resizable': False,
    }

    MESSAGES_SCROLL_DURATION = 700
    BUBBLE_BOT_THOUGHT_FONT = {
        'selectable': True,
        'size': 14,
        'color': ft.Colors.GREY_400
    }
    BUBBLE_STYLE = {
        'border_radius': ft.BorderRadius.all(15),
        'padding': ft.Padding.symmetric(horizontal=15, vertical=10),
        'shadow': ft.BoxShadow(spread_radius=0.5, blur_radius=2, color=ft.Colors.GREY_200),
        'width': 750,
    }

    # 生成任务计划（一次性拆分）
    PLAN_GENERATION_PROMPT = """你是一个任务规划助手。用户需求：
{user_input}

可用的技能及其完整文档：
{skills_docs}

请根据用户需求生成一个详细的执行计划。计划应该包含一系列步骤，每个步骤指定要使用的技能和要执行的命令（命令必须是完整的 shell 命令，例如对于网络请求使用 curl 或 wget）。
输出格式为JSON，例如：
{{
  "plan": [
    {{"skill": "weather", "command": "curl -s wttr.in/广州?0&lang=zh"}},
    {{"skill": "unsplash-image-search", "command": "python3 scripts/unsplash_search.py --query '广州' --per_page 5"}}
  ]
}}
如果不需要任何命令，可以输出空列表。只输出JSON，不要有其他内容。"""

    # 单技能内部的 ReAct 提示（允许重试）
    STEP_REACT_PROMPT = """你是一个任务执行助手。当前技能：{skill_name}
技能文档：
{skill_doc}

任务描述：{task_description}

你必须按照 ReAct 模式执行。每次响应输出：
Thought: 你的思考。
Action: execute_command
Action Input: {{"command": "具体的 shell 命令"}}

如果任务已经完成或无法继续，输出：
Final Answer: [完成/失败原因]

请注意：命令必须是在技能文档允许的范围内，且必须是可执行的系统命令（如 curl, ls, python 等）。最多可以尝试 {max_steps} 次。
"""

    # 最终答案生成（让 LLM 自己根据完整原始输出汇总）
    FINAL_ANSWER_PROMPT = """根据以下任务计划和执行结果，给用户一个完整的回答。

用户原始需求：{user_input}

任务计划：
{plan}

各步骤执行结果（完整原始输出）：
{execution_results}

请根据上述信息，以自然、友好的方式回答用户最初的问题。你需要：
1. 判断每个步骤的执行结果是否符合计划预期。
2. 如果执行结果中包含数据（如天气信息、图片链接、视频信息、文件列表等），请适当地汇总并呈现给用户。
3. 对于包含图片或视频链接的结果，请以清晰的列表形式提供链接（可使用 Markdown 格式）。
4. 如果某个步骤失败，请说明原因并提出可能的建议。

最终答案："""