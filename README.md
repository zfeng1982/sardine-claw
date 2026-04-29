# SardineClaw
## 🎯简介
- 一个全python的AI Agent项目
- GUI使用Flet
- LLM所有能力依赖SKILL技能.不乱跑,不删库,不泄密
## 💡 说明
1. 目前只支持openAPI协议,后面有计划做适配.不做适配的问题是慢,还有像GLM-5-Turbo这种龙虾增强基座模型用不了⚠️ .
2. Flet为原生GUI,比Electron快.但主要还是我不想搞TypeScript😅.
3. 为什么不引入langchain/langgraph?
   -  这两个我个人的理解他们是AI Agent的最佳工程实践.但你要知道他们为什么是最佳,就要知道他们为解决什么问题而存在,最好的办法是没有他们.

## 📂项目目录
sardine-claw/

    ├── skills/                         # 技能/模块目录
    
    ├── agent.py                        # 智能体核心实现
    
    ├── agents_conf.yaml                # 智能体配置文件
    
    ├── AI全流程.jpg                     # AI 流程示意图
    
    ├── const.py                        # 常量定义文件,主要是界面控制和LLM提示词
    
    ├── gui.py                          # 图形界面入口
    
    ├── llm.yaml                        # 大语言模型配置文件
    
    ├── main.py                         # 程序主入口文件
    
    ├── msg.py                          # 消息处理模块
    
    ├── README.md                       # 项目说明文档
    
    └── requirements.txt                # 项目依赖包列表

## 📋 开发计划
1. 支持操作电脑浏览器
2. 支持Appium操作手机
3. 模型适配
4. 增加长期记忆 
   - 压缩上下文
   - Embedding检索
   - IMA云端RAG
5. 安全沙箱
   - Daytona/CubeSandBox

## 😜絮絮叨叨
> - 我是写Java和C++的,请原谅我对python的变量命名还带有驼峰命令的习惯
> - 一个纯兴趣🔥 ,放飞自我的项目.
> - 没有产品❎,没有GM❎,最重要是没有KPI/OKR❎
> - 写Python实在比Java爽多了❗❗ 
> - 🎉 AI让我年轻10岁
