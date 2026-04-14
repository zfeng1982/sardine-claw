---
name: unsplash-image-search
displayName: Unsplash 图片搜索
version: 1.0.0
description: 通过 Unsplash API 搜索高质量免费图片，支持分页和数量控制。
author: alphazhu
license: MIT
tags:
  - image
  - search
  - unsplash
  - 图片
  - 配图
requires:
  env:
    - UNSPLASH_ACCESS_KEY
  tools:
    - exec
  commands:
    - python3
---

# Unsplash 图片搜索 Skill
access key请到https://unsplash.com/developers申请
试用版API Key每小时50次请求，正式版每小时 5000 次请求
## 使用场景

当用户需要图片素材时激活本技能。包括但不限于：
- 文章配图、封面设计
- 寻找灵感图片
- 获取高质量免费图片
- 指定数量的图片搜索

## 触发关键词

- "找一张[关键词]的图片"
- "搜索[主题]的照片"
- "帮我配几张[场景]的图"
- "Unsplash 搜索[关键词]"
- "再找一些"（自动翻页）

## 操作步骤
1. 从用户消息中提取搜索关键词
2. 根据上下文确定分页参数：
   - 首次搜索：`--page 1`
   - 用户说"再找一些"：上次页码+1
   - 用户指定数量：设置 `--per_page N`（1-30）
3. 执行搜索命令：
```bash  
   python3 scripts/unsplash_search.py --query "<关键词>" --per_page <数量> --page <页码>
```
## 参数说明

| 参数 | 说明 | 默认值 | 取值范围 |
|------|------|--------|----------|
| `--query` | 搜索关键词（必须） | 无 | 任意字符串 |
| `--per_page` | 每页图片数量 | 10 | 1-30 |
| `--page` | 页码 | 1 | ≥1 |

## 返回数据示例
```bash  
{
  "query": "深圳 海岸线",
  "per_page": 5,
  "page": 1,
  "total": 342,
  "total_pages": 69,
  "images": [
    {
      "id": "abcdef123456",
      "description": "深圳湾日出景色",
      "url": "https://images.unsplash.com/photo-xxx",
      "download": "https://unsplash.com/photos/xxx/download",
      "author": "王小明",
      "author_profile": "https://unsplash.com/@wangxiaoming",
      "color": "#0a3d62"
    }
    // ... 共5张图片
  ]
}
```


## 注意事项
1. **环境变量**：必须设置 `UNSPLASH_ACCESS_KEY`
2. **频率限制**：免费版每小时 50 次请求
3. **版权说明**：使用时建议注明摄影师
4. **分页控制**：最大支持 30 张/页
5. **错误处理**：API 错误会返回 JSON 格式的错误信息

