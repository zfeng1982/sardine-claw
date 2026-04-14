
import flet as ft
class ClawConst:
    BOT_MAX_COUNT =5                #bot最大充许数
    ACT_END = "|oneactstepend|"     #用一分隔标识一次act结束
    ACT_MAX_STEPS = 5               #用户最大的ACT交数

    MODEL_MAX_TOKENS=8000           #这个调整一下,防止有些模型没有思考完成就直接打断了finish_reason: 'length'
    MODEL_TEMPERATURE=0.7


    PAGE_STYLE ={                   #窗口配置
        'title': "AI 助手团队",
        'theme_mode': ft.ThemeMode.LIGHT,
        'padding': 0,
        'bgcolor': ft.Colors.GREY_50,
        'width': 880,
        'height': 800,
        'resizable': False,
    }

    MESSAGES_SCROLL_DURATION = 700                       # 消息列表滚动时间,越小滚动越快

    BUBBLE_BOT_THOUGHT_FONT = {                          #消息汽泡Thought状态时的字体的配置
        'selectable': True,
        'size': 14,
        'color': ft.Colors.GREY_400
    }

    BUBBLE_STYLE = {                                         #消息汽泡统一样式
        'border_radius':ft.BorderRadius.all(15),
        'padding':ft.Padding.symmetric(horizontal=15, vertical=10),
        'shadow':ft.BoxShadow(spread_radius=0.5, blur_radius=2, color=ft.Colors.GREY_200),
        'width':750,
    }

    SKILL_SELECT_PROMPT = """你是一个技能路由助手。用户输入如下：
                            {user_input}
                            可用的技能列表：
                            {skills_desc}
                            请根据用户输入选择最匹配的一个技能。如果没有任何技能适合，则输出none。
                            你的输出必须只包含技能名称或 none。
                            """

    SKILL_DOC_PROMPT = """你是一个能够使用工具的智能助手。当前已激活以下技能：
            技能名称：{skill_name}
            技能文档：
            {skill_doc}
            请严格按照技能文档中的操作步骤来完成任务。你可以使用以下方式执行操作：
            - 如果文档中描述了命令行操作，你应该输出：
              Action: execute_command
              Action Input: {{"command": "具体的命令字符串"}}
            - 如果文档中有其他操作指引，请遵循文档说明。
            你必须遵循ReAct模式，每次响应包含 Thought, Action, Action Input，或者 Final Answer。
            注意：一次只输出一个Action，等待结果后再继续。
            如果你认为任务结束或者查到可用的信息请一定要输出 Final Answer: [答案内容]
            """


