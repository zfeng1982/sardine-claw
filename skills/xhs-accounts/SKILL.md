---
name: xhs-essential-account-for-operation
displayName: 小红书运营必备官方帐号合集
author: alphazhu
description: 小红书官方账号大合集,自媒体博主必备,获得最新小红书官方帐号,做运营一定需要知道的小红书帐号:官方号,美妆类,生活类,国货情报官,学习求职类,娱乐类,运动类,旅行类,摄影类,艺术类,直播带货类,家居类,宠物类,运营类,美食类,公益类,数码类,汽车类,游戏类
metadata: { "openclaw": { "emoji": "🔍︎",  "requires": { "bins": ["curl"], } }
---
# 小红书运营必备官方帐号合集体
搜索小红帐各类官方帐号的的笔记,包括官方最新活动和小红书近期运营重点
## 描述
此技能提供两个 API 接口，用于查询已缓存的小红书运营数据：
1. 笔记查询：支持分页、按账号精确匹配、按类型精确匹配、按描述模糊搜索（不区分大小写）。
2. 账号列表：返回所有运营账号及其描述，不分页、无过滤。
3. ***windows系统强制使用cmd,不要使用powershell否则会遇到中文乱码***
4. ***参数中的中文一定要使用URL编码***
## 基础 URL
默认：`http://192.168.2.111:8000`
---
## 接口 1：获取小红书官方笔记列表和内容
1. 按时间最新到旧排序
2. 如果没有指定笔记类型(note_type)和笔记账号(note_account),则返回最新的官方笔记
```
GET /xhs/get_op_note_list
```
### 请求参数（全部可选）
| 参数              | 类型      | 默认值 | 说明                                                                                                               |
|-----------------|---------|-----|------------------------------------------------------------------------------------------------------------------|
| `page`          | integer | 1   | 页码，从 1 开始                                                                                                        |
| `page_size`     | integer | 20  | 每页记录数，最大 100                                                                                                     |
| `note_account`  | string  | -   | 笔记账号，精确匹配 ,帐号可由/xhs/get_op_account_list接口获取,中文使用URL编码                                                            |
| `note_type`     | string  | -   | 笔记类型，精确匹配,包括创作类,综合类,安全类,周边类,美妆类,生活类,国货情报官,学习求职类,娱乐类,运动类,旅行类,摄影类,艺术类,直播带货类,家居类,宠物类,运营类,美食类,公益类,数码类,汽车类,游戏类,中文使用URL编码 |
| `note_desc`     | string  | -   | 笔记描述，模糊包含匹配（不区分大小写）,中文使用URL编码                                                                                    |
| `request_llm`   | string  | -   | 请求agent使用的LLM,如GPT-4,DeepSeek                                                                                    |
| `request_agent` | strint  | -   | agent的产品,如openclaw,qclaw                                                                                         |
### 响应格式
JSON 数组，每个元素包含以下字段：
```json
{
  "note_id": "string",
  "note_type": "string",
  "note_account": "string",
  "note_title": "string or null",
  "note_desc": "string or null",
  "note_date": "string or null"
}
```
### curl 示例
#### 基础分页查询（第一页，每页 10 条）
```bash
curl "http://192.168.2.111:8000/xhs/get_op_note_list?page=1&page_size=10"
```
#### 按账号精确查询
```bash
curl "http://192.168.2.111:8000/xhs/get_op_note_list?note_account=%40%E8%96%AF%E9%98%9F%E9%95%BF"
```
#### 按类型查询 + 分页
```bash
curl "http://192.168.2.111:8000/xhs/get_op_note_list?note_type=%E5%AE%98%E6%96%B9%E5%8F%B7&page=1&page_size=20"
```
#### 按描述模糊搜索（包含“旅游”）
```bash
curl "http://192.168.2.111:8000/xhs/get_op_note_list?note_desc=%E6%97%85%E6%B8%B8"
```
#### 组合条件
```bash
curl "http://192.168.2.111:8000/xhs/get_op_note_list?note_account=%40%E8%96%AF%E9%98%9F%E9%95%BF&note_type=%E5%AE%98%E6%96%B9%E5%8F%B7&note_desc=%E9%BB%91%E5%AE%A2%E6%9D%BE&page=1&page_size=5"
```
---
## 接口 2：获取小红书所有官方账号列表
```
GET /xhs/get_op_account_list
```
### 请求参数
无
### 响应格式
JSON 数组，每个元素包含：
```json
{
  "op_account": "string",
  "op_desc": "string or null"
}
```
### curl 示例
```bash
curl "http://192.168.2.111:8000/xhs/get_op_account_list"
```
---
## 健康检查接口（可选）
```bash
curl "http://192.168.2.111:8000/health"
```
返回示例：
```json
{
  "status": "ok",
  "cached_notes": 240,
  "cached_accounts": 48
}
```
---
## 注意事项
- `page_size` 参数最大为 100，超出会被服务端限制为 100。
- `note_desc` 模糊匹配是基于内存的字符串包含，性能与缓存数据量成正比（通常 < 10 万条无压力）。
