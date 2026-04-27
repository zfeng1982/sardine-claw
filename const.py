import flet as ft

class ClawConst:
    BOT_MAX_COUNT = 5                # bot最大充许数
    ACT_END = "|oneactstepend|"      # 用一分隔标识一次act结束（已不再使用但保留）
    ACT_MAX_STEPS = 5                # 用户最大的ACT交数（已不再使用但保留）

    MODEL_MAX_TOKENS = 8000          # 这个调整一下,防止有些模型没有思考完成就直接打断了finish_reason: 'length'
    MODEL_TEMPERATURE = 0.7

    PAGE_STYLE = {                   # 窗口配置
        'title': "AI Friend",
        'theme_mode': ft.ThemeMode.LIGHT,
        'padding': 2,
        'bgcolor': ft.Colors.GREY_50,
        'width': 880,
        'height': 800,
        'resizable': False,
    }

    MESSAGES_SCROLL_DURATION = 700   # 消息列表滚动时间,越小滚动越快

    BUBBLE_BOT_THOUGHT_FONT = {      # 消息汽泡Thought状态时的字体的配置
        'selectable': True,
        'size': 14,
        'color': ft.Colors.GREY_400
    }

    BUBBLE_STYLE = {                 # 消息汽泡统一样式
        'border_radius': ft.BorderRadius.all(15),
        'padding': ft.Padding.symmetric(horizontal=15, vertical=10),
        'shadow': ft.BoxShadow(spread_radius=0.5, blur_radius=2, color=ft.Colors.GREY_200),
        'width': 750,
    }

    # 计划生成提示模板
    PLAN_GENERATION_PROMPT = """你是一个任务规划助手。用户需求：
{user_input}

可用的技能及其完整文档：
{skills_docs}

请根据用户需求生成一个详细的执行计划。计划应该包含一系列步骤，每个步骤指定要使用的技能和要执行的命令（命令必须基于技能文档中的指导）。
输出格式为JSON，例如：
{{
  "plan": [
    {{"skill": "skill_name1", "command": "具体的命令"}},
    {{"skill": "skill_name2", "command": "具体的命令"}}
  ]
}}
如果不需要任何命令，可以输出空列表。只输出JSON，不要有其他内容。"""

    # 最终答案生成提示模板（包含对计划符合性的判断）
    FINAL_ANSWER_PROMPT = """根据以下任务计划和执行结果，给用户一个完整的回答。
用户原始需求：{user_input}
计划：{plan}
执行结果：{execution_results}
请判断每个步骤的执行结果是否符合计划预期，然后汇总成最终答案回答用户。如果执行结果中有错误或不符合预期，请说明情况。
最终答案："""

    # 以下两个旧模板已不再使用，但保留以免其他代码引用时报错
    SKILL_SELECT_PROMPT = ""  # 已废弃
    SKILL_DOC_PROMPT = ""     # 已废弃