---
name: ima-notes-python
displayName: ima-notes-python
version: 1.0.0
description: 通过python 管理IMA笔记相关内容。
author: alphazhu
license: MIT
requires:
  env:
    - IMA_OPENAPI_CLIENTID
    - IMA_OPENAPI_APIKEY
  tools:
    - exec
  commands:
    - python3
---
# IMA 笔记命令行客户端技能

## 简介

本技能封装了 IMA 笔记的 OpenAPI，提供一套简单易用的命令行工具，支持笔记的搜索、管理、创建、追加和内容读取。通过 Python 脚本 `scripts/IMANotesClient.py`，您可以快速与 IMA 笔记交互，实现自动化操作。

## 功能特性

- **搜索笔记**：按标题或正文关键词搜索笔记
- **笔记本管理**：列出所有笔记本、查看笔记本内的笔记列表
- **笔记创建**：从 Markdown 内容新建笔记，支持从文件读取
- **内容追加**：向已有笔记末尾追加内容
- **笔记内容获取**：获取笔记的纯文本、Markdown 或 JSON 格式内容
- **自动处理**：自动过滤本地图片引用、确保 UTF-8 编码，避免 API 调用失败

## 安装与配置

### 依赖

- Python 3.6 及以上
- `requests` 库

安装依赖：
```bash
pip install requests
```

### 获取 API 凭证

使用前需要申请 IMA OpenAPI 的 `client_id` 和 `api_key`。申请后，可通过以下方式之一配置：

1. **环境变量**：
   ```bash
   export IMA_OPENAPI_CLIENTID="your_client_id"
   export IMA_OPENAPI_APIKEY="your_api_key"
   ```
### 验证配置
运行以下命令，若显示帮助信息则说明环境正常：
```bash
python IMANotesClient.py --help
```

## 命令详解

### 全局选项

所有命令均可使用 `-h` 或 `--help` 查看详细帮助。

### 1. 搜索笔记 (`search`)

按标题或正文搜索笔记。

**用法**：
```bash
python IMANotesClient.py search --type {title,content} --query <关键词> [--start <起始位置>] [--end <结束位置>] [--sort {update,create,title,size}]
```

**参数**：
- `--type`：搜索类型，`title`（标题）或 `content`（正文），默认 `title`
- `--query`：搜索关键词（必填）
- `--start`：起始位置，默认 0
- `--end`：结束位置，默认 20
- `--sort`：排序方式，可选 `update`（更新时间）、`create`（创建时间）、`title`（标题）、`size`（大小），默认 `update`

**示例**：
```bash
# 搜索标题包含“周报”的笔记
python IMANotesClient.py search --type title --query 周报

# 搜索正文包含“项目计划”的笔记，按创建时间排序，返回第 0-9 条
python IMANotesClient.py search --type content --query "项目计划" --sort create --end 10
```

**输出**：显示匹配的笔记列表，包含标题、文档 ID、所属笔记本、修改时间及高亮片段。

---

### 2. 列出所有笔记本 (`list-folders`)

获取用户的笔记本列表（包括“全部笔记”和“未分类”等系统笔记本）。

**用法**：
```bash
python IMANotesClient.py list-folders [--cursor <游标>] [--limit <数量>]
```

**参数**：
- `--cursor`：分页游标，首页为 `"0"`，默认 `"0"`
- `--limit`：每页数量，默认 20

**示例**：
```bash
# 列出前 10 个笔记本
python IMANotesClient.py list-folders --limit 10
```

**输出**：笔记本名称、ID、笔记数量、创建时间等信息。

---

### 3. 列出笔记本中的笔记 (`list-notes`)

查看指定笔记本内的笔记列表，不指定 `folder-id` 则显示“全部笔记”。

**用法**：
```bash
python scripts/IMANotesClient.py list-notes [--folder-id <笔记本ID>] [--cursor <游标>] [--limit <数量>]
```

**参数**：
- `--folder-id`：笔记本 ID，不指定则显示全部笔记
- `--cursor`：分页游标，首页为空字符串，默认 `""`
- `--limit`：每页数量，默认 20

**示例**：
```bash
# 列出全部笔记的前 5 条
python scripts/IMANotesClient.py list-notes --limit 5

# 列出指定笔记本中的笔记
python scripts/IMANotesClient.py list-notes --folder-id f123456 --limit 10
```

**输出**：笔记标题、文档 ID、摘要、修改时间。

---

### 4. 创建新笔记 (`create`)

从 Markdown 内容创建新笔记，可指定标题和存放的笔记本。

**用法**：
```bash
python scripts/IMANotesClient.py create [--content <内容>] [--file <文件路径>] [--title <标题>] [--folder-id <笔记本ID>]
```

**参数**：
- `--content`：直接提供笔记内容（Markdown）
- `--file`：从文件读取内容（支持 UTF-8/GBK 编码）
- `--title`：可选，自动添加为一级标题（`# 标题`）
- `--folder-id`：可选，笔记存放的笔记本 ID，不指定则放入“全部笔记”

> **注意**：`--content` 和 `--file` 必须提供一个，且内容不能为空。

**示例**：
```bash
# 创建一篇简单笔记
python scripts/IMANotesClient.py create --content "这是一个测试笔记" --title "测试"

# 从 Markdown 文件创建笔记，保存到特定笔记本
python scripts/IMANotesClient.py create --file ./report.md --title "月度报告" --folder-id f123456
```

**输出**：返回创建成功的文档 ID。

---

### 5. 追加内容到笔记 (`append`)

在已有笔记的末尾追加内容。

**用法**：
```bash
python scripts/IMANotesClient.py append --docid <文档ID> [--content <内容>] [--file <文件路径>]
```

**参数**：
- `--docid`：目标笔记的文档 ID（必填）
- `--content`：要追加的内容（Markdown）
- `--file`：从文件读取要追加的内容

> **注意**：`--content` 和 `--file` 必须提供一个，且内容不能为空。

**示例**：
```bash
# 向笔记追加文本
python scripts/IMANotesClient.py append --docid doc_abc123 --content "\n## 更新记录\n- 修复了bug"

# 从文件追加内容
python scripts/IMANotesClient.py append --docid doc_abc123 --file ./update.md
```

**输出**：确认追加成功，返回文档 ID。

---

### 6. 获取笔记内容 (`get`)

获取指定笔记的内容，支持纯文本、Markdown 或 JSON 格式。

**用法**：
```bash
python scripts/IMANotesClient.py get --docid <文档ID> [--format {0,1,2}]
```

**参数**：
- `--docid`：笔记的文档 ID（必填）
- `--format`：返回格式
  - `0`：纯文本（默认）
  - `1`：Markdown
  - `2`：JSON 结构

**示例**：
```bash
# 获取笔记的纯文本内容
python scripts/IMANotesClient.py get --docid doc_abc123

# 获取 Markdown 格式内容
python scripts/IMANotesClient.py get --docid doc_abc123 --format 1
```

**输出**：笔记内容直接打印到标准输出。

---

## 使用技巧

### 批量操作

可以结合 Shell 脚本实现批量导入、导出等。例如，将多个 Markdown 文件导入 IMA：

```bash
for file in *.md; do
    python scripts/IMANotesClient.py create --file "$file" --title "${file%.md}"
done
```

### 内容预处理

客户端会自动：
- 过滤本地图片引用（如 `file://`、`/`、`C:\` 开头的路径），避免上传失败
- 强制 UTF-8 编码，确保中文等特殊字符正常写入

### 错误处理

- 凭证缺失：会提示配置方式
- 网络错误：显示详细错误信息，可重试
- 文件编码：自动尝试 UTF-8 和 GBK 读取，失败时给出提示

## 常见问题

**Q：为什么创建笔记时提示“内容不能为空”？**  
A：请确保 `--content` 或 `--file` 参数提供了非空白内容，且文件读取成功。

**Q：如何获取笔记本 ID？**  
A：使用 `list-folders` 命令，输出结果中的 `文件夹ID` 即为所需 ID。

**Q：追加内容后如何确保不破坏原有格式？**  
A：建议在追加内容前加上换行符，客户端会自动在内容前添加 `\n`（如果未以 `\n` 开头），避免粘连。

**Q：是否支持图片上传？**  
A：当前接口不支持图片上传，但可以引用网络图片。本地图片引用会被自动过滤。

## 许可证

本工具仅用于学习和自动化 IMA 笔记操作，请遵守 IMA 平台的使用协议。代码采用 MIT 许可证。

---
**版本**：1.0.0  
**更新日期**：2026-04-01  
**维护者**：基于 IMANotesClient.py 生成
```

