import flet as ft

class ClawConst:
    BOT_MAX_COUNT = 5
    ACT_END = "|oneactstepend|"
    ACT_MAX_STEPS = 50                    # 每个技能内部最大尝试次数

    MODEL_MAX_TOKENS = 8000
    MODEL_TEMPERATURE = 0.7

    PAGE_STYLE = {
        'title': "AI Friend",
        'theme_mode': ft.ThemeMode.LIGHT,
        'padding': 2,
        'bgcolor': ft.Colors.GREY_50,
        'width': 880,
        'height': 800,
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

    VALIDATE_RESULT_PROMPT="""
你是一个严格的结果验证专家。以下是技能相关信息、执行的命令和输出，请判断是否达成了任务目标。并给出修正建议的命令判断标准：
1. **可读性**：输出是否是人类可读的明文，而不是乱码、Base64 长串、明显加密的数据？如果是加密或乱码，认定为失败。
2. **格式符合性**：输出格式是否符合技能文档中描述的预期格式（例如 JSON、纯文本表格等）？如果不符合，认定为失败。
3. **内容完整性**：输出是否包含了任务描述中要求的关键信息？例如查询天气应有温度、天气状况；查询热点应有标题和热度；搜索图片应有图片链接等。关键信息缺失则失败。
4. **错误状态**：如果命令执行失败（返回错误信息、返回码非0），认定为失败。
5. **后处理需求**：如果输出看起来需要进一步处理（例如文档中明确提到“需要对字段解密”，且脚本中提供了解密函数），则认定为失败，并应建议执行解密/处理命令。
6. **如果生成的是python -c命令必须按如下原则**
   - 禁止pthon -c中使用def定义方法
   - 禁止使用换行写python代码,应该使用分号代替 若存在 `for`、`if`、`while`、`def`、`with`、`try` 等关键字前面出现了分号,则要Convert the for-loop into a list comprehension one-liner
   - Python代码，确保语法完全正确，不要出现 ^%这类非法运算符组合，并在输出前自行做一次语法检查。
技能名称：{skill_name}
技能文档：
{skill_doc}
scripts/ 目录下的脚本内容（供参考，可能包含解密/处理逻辑）：
{scripts_content}
请严格按照以下格式输出：
- 如果成功：只输出 "SUCCESS"
- 如果失败：输出 "FAILED: 原因" （简要说明原因），然后另起一行，必须给出修正建议的命令，格式为：
  Action: execute_command
  Action Input: {{"command": "修正后的完整命令"}}
下面是ReAct历史执行的命令和返回的结果:"""

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

    SYNTAX_CHECK_PROMPT="""
你是一个专门检查 Windows 命令行语法的助手。用户会提供一个 command 字符串，该字符串将作为 subprocess.run(command, shell=True, ...) 的参数在 Windows 环境中执行。
请分析用户提供的 command 字符串，并严格按照上述规则输出结果。
##要检查的命令:
```bash
{command}
```
##检查规则：
    1. **curl 命令**：
       - 检查 URL 是否用双引号包裹（Windows 下 curl 不识别单引号，必须使用双引号，例如 "http://..."）。
       - 检查选项是否小写（如 -X, -H, -d, -o 等，Windows curl 选项通常不区分大小写，但建议保持小写，避免与文件系统混淆）。
       - 检查请求头格式：-H "Key: Value" 中冒号后是否有空格。
       - 检查文件上传：-F 或 --form 参数中的 @ 路径是否使用反斜杠或双引号包裹。
       - 检查特殊字符（&, ?, 空格）是否在双引号内。
    2. **python3 -c 命令**：
       - 检查 -c 后的代码字符串是否正确转义双引号（外层用双引号包裹，内部双引号需转义为 \"）。
       - 检查内部单引号无需转义，但需确保引号配对。
       - 检查代码中的反斜杠路径（如 C:\\path）——反斜杠需要转义（写为 \\）或使用正斜杠。
       - 检查 Python 代码中的大小写敏感问题（变量名、关键字、函数名等必须大小写正确）。
       - 检查可能被 shell 解释的特殊字符（%VAR%, ^, &, |, <, >），若存在且未被引号包裹，应建议转义或改用列表参数。
       - 禁止pthon -c中使用def定义方法
       - 禁止使用换行写python代码,应该使用分号代替 若存在 `for`、`if`、`while`、`def`、`with`、`try` 等关键字前面出现了分号,则要Convert the for-loop into a list comprehension one-liner
       - Python代码，确保语法完全正确，不要出现 ^%这类非法运算符组合，并在输出前自行做一次语法检查。
       
    3. **通用 Windows shell 问题**：
       - 命令中的环境变量引用应使用 %VAR% 格式，但注意变量名大小写不敏感。
       - 路径分隔符建议使用反斜杠 \\（需在字符串中转义为 \\\\）或正斜杠 /（更安全）。
       - 如果命令包含多个语句（用 & 或 && 连接），检查每个部分的引号和转义是否独立正确。
       - 检查参数中的空格是否被双引号正确分组。
##输出格式：
- 如果验证通过（无任何语法问题）：只输出一行 "SUCCESS"
- 如果验证失败：输出一行 "FAILED: 简要原因"（原因需具体指出问题类型和位置），然后另起一行严格输出以下格式：
  Action: execute_command
  Action Input: {{"command": "修正后的完整命令"}}
  注意：修正后的命令必须是一个有效的字符串，其中的双引号需适当转义（例如内部双引号写为 \"），路径反斜杠写为 \\\\。
    示例：
    输入命令：curl -X GET http://example.com?name=foo&bar
    分析：URL 中包含未引号的 & 符号，会被 shell 解释为后台运行。同时 Windows curl 要求 URL 用双引号包裹。
    输出：
    FAILED: curl 命令的 URL 缺少双引号，且 & 未转义
    Action: execute_command
    Action Input: {{"command": "curl -X GET \\"http://example.com?name=foo&bar\\""}}
    输入命令：python3 -c "print('hello')"
    分析：Windows 下通常使用 python 而非 python3，但若系统有 python3 别名也可。代码内引号无冲突。
    输出：SUCCESS
##历史ReAct检查
- 检查下面的执行历史,不要重复执行已经失败的命令,并参考失败的结果返回对命令进行调整
  以下是你的历史验证通过(SUCCESS)和执行的结果,每一次代码一轮ReAct:"""