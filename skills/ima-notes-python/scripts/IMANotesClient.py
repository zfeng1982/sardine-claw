import requests
import json
import os
import sys
import argparse
from typing import Optional, Dict, Any, List
from datetime import datetime


class IMANotesClient:
    """
    IMA 笔记 OpenAPI 的 Python 客户端 (使用 requests 库)。
    基于文档: SKILL.md (根文档、笔记模块) 和 api.md。
    """

    BASE_URL = "https://ima.qq.com"
    # 凭证加载优先级: 环境变量 -> 配置文件
    CONFIG_DIR = os.path.expanduser("~/.config/ima")
    CLIENT_ID_ENV = "IMA_OPENAPI_CLIENTID"
    API_KEY_ENV = "IMA_OPENAPI_APIKEY"

    def __init__(self, client_id: Optional[str] = None, api_key: Optional[str] = None):
        """
        初始化客户端，加载凭证。
        参数:
            client_id: 可手动传入 Client ID，否则从环境变量或文件读取。
            api_key: 可手动传入 API Key，否则从环境变量或文件读取。
        """
        self.client_id = client_id
        self.api_key = api_key
        self._load_credentials()
        self._check_credentials()
        self._session = requests.Session()
        # 设置公共请求头
        self._session.headers.update({
            "Content-Type": "application/json",
            "ima-openapi-clientid": self.client_id,
            "ima-openapi-apikey": self.api_key
        })

    def _load_credentials(self):
        """按优先级加载凭证: 构造函数参数 -> 环境变量 -> 配置文件。"""
        # 如果构造函数已提供，则优先使用
        if self.client_id is None:
            self.client_id = os.environ.get(self.CLIENT_ID_ENV)
        if self.api_key is None:
            self.api_key = os.environ.get(self.API_KEY_ENV)

        # 从配置文件读取
        if not self.client_id or not self.api_key:
            try:
                client_id_path = os.path.join(self.CONFIG_DIR, "client_id")
                api_key_path = os.path.join(self.CONFIG_DIR, "api_key")
                if os.path.exists(client_id_path):
                    with open(client_id_path, 'r', encoding='utf-8') as f:
                        self.client_id = self.client_id or f.read().strip()
                if os.path.exists(api_key_path):
                    with open(api_key_path, 'r', encoding='utf-8') as f:
                        self.api_key = self.api_key or f.read().strip()
            except Exception:
                pass  # 文件读取失败，将在检查时报错

    def _check_credentials(self):
        """检查凭证是否有效。"""
        if not self.client_id or not self.api_key:
            raise ValueError(
                f"缺少 IMA 凭证。请按以下方式之一设置：\n"
                f"1. 环境变量: 设置 {self.CLIENT_ID_ENV} 和 {self.API_KEY_ENV}\n"
                f"2. 配置文件: 在 {self.CONFIG_DIR} 目录下创建 client_id 和 api_key 文件\n"
                f"3. 在代码中初始化时传入 client_id 和 api_key 参数。"
            )

    def _ima_api(self, api_path: str, json_body: Dict[str, Any]) -> Dict[str, Any]:
        """
        调用 IMA API 的通用辅助函数。
        所有请求均为 POST 到 BASE_URL + api_path。
        """
        url = f"{self.BASE_URL}/{api_path.lstrip('/')}"
        try:
            # 针对 notes 模块的写入接口，强制确保请求体为合法 UTF-8
            if api_path.startswith("openapi/note/v1") and ("import_doc" in api_path or "append_doc" in api_path):
                json_body = self._ensure_utf8_json(json_body)
            response = self._session.post(url, json=json_body, timeout=30)
            response.raise_for_status()  # 检查 HTTP 状态码
            return response.json()
        except requests.exceptions.RequestException as e:
            if hasattr(e.response, 'text'):
                print(f"响应内容: {e.response.text}")
            raise
        except json.JSONDecodeError as e:
            print(f"API 响应非 JSON 格式: {e}")
            raise

    def _ensure_utf8_json(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        确保写入 notes 的 content 和 title 字段为合法 UTF-8 字符串。
        这是强制要求，防止乱码。
        """

        def ensure_utf8_string(obj):
            if isinstance(obj, str):
                # 清洗非法 UTF-8 字节
                return obj.encode('utf-8', 'ignore').decode('utf-8')
            elif isinstance(obj, dict):
                return {k: ensure_utf8_string(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [ensure_utf8_string(item) for item in obj]
            else:
                return obj

        return ensure_utf8_string(data)

    def _filter_local_images_in_content(self, content: str) -> str:
        """
        过滤 content 中的本地图片路径（ima-skill 文档要求）。
        仅移除以 file://, /, C:\\, D:\\ 等开头的图片引用，保留网络图片。
        """
        import re
        # 匹配 Markdown 图片语法 ![alt](src)
        def replace_local_image(match):
            src = match.group(2)
            if (src.startswith('file://') or
                    (src.startswith('/') and not src.startswith('//')) or  # 本地绝对路径
                    re.match(r'^[A-Za-z]:\\', src) or  # Windows 路径 C:\
                    re.match(r'^[A-Za-z]:/', src)):  # Windows 路径 C:/
                # 返回移除图片后的空字符串，或替换为提示文本
                # 根据文档，这里选择过滤掉
                return ''
            else:
                # 网络图片，保留
                return match.group(0)

        pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
        filtered_content = re.sub(pattern, replace_local_image, content)
        return filtered_content

    def _format_timestamp(self, ts: int) -> str:
        """将毫秒时间戳转换为可读格式"""
        if ts == 0:
            return "N/A"
        return datetime.fromtimestamp(ts / 1000).strftime('%Y-%m-%d %H:%M:%S')

    # --- 笔记 (Notes) 模块 API 封装 ---
    # 对应文档: notes/SKILL.md 和 references/api.md

    def search_note_book(self,
                         query_info: Dict[str, str],
                         search_type: int = 0,
                         sort_type: int = 0,
                         start: int = 0,
                         end: int = 20,
                         query_id: Optional[str] = None) -> Dict[str, Any]:
        """
        搜索笔记。
        触发场景: 用户说「搜索」「找笔记」「查找包含XX的内容」
        请求路径: /openapi/note/v1/search_note_book
        """
        body = {
            "search_type": search_type,  # 0:标题, 1:正文
            "sort_type": sort_type,  # 0:更新时间(默认), 1:创建时间, 2:标题, 3:大小
            "query_info": query_info,  # {"title": "关键词"} 或 {"content": "关键词"}
            "start": start,
            "end": end
        }
        if query_id:
            body["query_id"] = query_id
        return self._ima_api("openapi/note/v1/search_note_book", body)

    def list_note_folder_by_cursor(self, cursor: str = "0", limit: int = 20) -> Dict[str, Any]:
        """
        列出笔记本列表。
        触发场景: 用户说「列出笔记本」「有哪些分类」「查看笔记本目录」
        请求路径: /openapi/note/v1/list_note_folder_by_cursor
        """
        body = {
            "cursor": cursor,  # 首页必须为 "0"
            "limit": limit
        }
        return self._ima_api("openapi/note/v1/list_note_folder_by_cursor", body)

    def list_note_by_folder_id(self,
                               folder_id: Optional[str] = None,
                               cursor: str = "",
                               limit: int = 20) -> Dict[str, Any]:
        """
        按笔记本拉取笔记列表。
        触发场景: 用户说「查看XX笔记本的笔记」「列出这个笔记本里的内容」
        注意: folder_id 为空时，表示"全部笔记"。
        请求路径: /openapi/note/v1/list_note_by_folder_id
        """
        body = {
            "cursor": cursor,  # 首页必须为空字符串 ""
            "limit": limit
        }
        if folder_id:
            body["folder_id"] = folder_id
        return self._ima_api("openapi/note/v1/list_note_by_folder_id", body)

    def import_doc(self,
                   content: str,
                   content_format: int = 1,
                   folder_id: Optional[str] = None) -> Dict[str, Any]:
        """
        从 Markdown 新建笔记。
        触发场景: 用户明确说「新建笔记」「创建笔记」「把这段 Markdown 保存为笔记」
        注意: 写入前会强制进行 UTF-8 编码检查和本地图片过滤。
        请求路径: /openapi/note/v1/import_doc
        """
        # 1. 过滤本地图片
        filtered_content = self._filter_local_images_in_content(content)
        # 2. 准备请求体 (UTF-8 检查在 _ima_api 中统一进行)
        body = {
            "content_format": content_format,  # 目前仅支持 1 (Markdown)
            "content": filtered_content
        }
        if folder_id:
            body["folder_id"] = folder_id
        return self._ima_api("openapi/note/v1/import_doc", body)

    def append_doc(self,
                   doc_id: str,
                   content: str,
                   content_format: int = 1) -> Dict[str, Any]:
        """
        追加内容到已有笔记。
        触发场景: 用户明确说「在这篇笔记末尾追加内容」「把XX添加到笔记里」
        注意: 此为敏感操作，必须明确指定 doc_id。写入前会强制进行 UTF-8 编码检查和本地图片过滤。
        请求路径: /openapi/note/v1/append_doc
        """
        # 1. 过滤本地图片
        filtered_content = self._filter_local_images_in_content(content)
        # 2. 准备请求体
        body = {
            "doc_id": doc_id,
            "content_format": content_format,  # 目前仅支持 1 (Markdown)
            "content": filtered_content
        }
        return self._ima_api("openapi/note/v1/append_doc", body)

    def get_doc_content(self,
                        doc_id: str,
                        target_content_format: int = 0) -> Dict[str, Any]:
        """
        获取笔记纯文本内容。
        触发场景: 用户说「读取笔记内容」「获取这篇笔记的纯文本」
        请求路径: /openapi/note/v1/get_doc_content
        """
        body = {
            "doc_id": doc_id,
            "target_content_format": target_content_format  # 推荐 0 (纯文本)
        }
        return self._ima_api("openapi/note/v1/get_doc_content", body)


def main():
    """命令行主函数"""
    parser = argparse.ArgumentParser(
        description="IMA 笔记 OpenAPI 命令行客户端",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest='command', help='可用命令', required=False)  # 改为 required=False

    # 搜索笔记命令
    search_parser = subparsers.add_parser('search', help='搜索笔记')
    search_parser.add_argument('--type', choices=['title', 'content'], default='title',
                               help='搜索类型: title=标题搜索, content=正文搜索 (默认: title)')
    search_parser.add_argument('--query', required=True, help='搜索关键词')
    search_parser.add_argument('--start', type=int, default=0, help='起始位置 (默认: 0)')
    search_parser.add_argument('--end', type=int, default=20, help='结束位置 (默认: 20)')
    search_parser.add_argument('--sort', choices=['update', 'create', 'title', 'size'],
                               default='update', help='排序方式 (默认: update)')

    # 列出笔记本命令
    folder_parser = subparsers.add_parser('list-folders', help='列出所有笔记本')
    folder_parser.add_argument('--cursor', default='0', help='游标 (默认: "0")')
    folder_parser.add_argument('--limit', type=int, default=20, help='返回数量限制 (默认: 20)')

    # 列出笔记本中的笔记命令
    notes_parser = subparsers.add_parser('list-notes', help='列出笔记本中的笔记')
    notes_parser.add_argument('--folder-id', help='笔记本ID (为空则显示"全部笔记")')
    notes_parser.add_argument('--cursor', default='', help='游标 (默认: "")')
    notes_parser.add_argument('--limit', type=int, default=20, help='返回数量限制 (默认: 20)')

    # 创建笔记命令
    create_parser = subparsers.add_parser('create', help='创建新笔记')
    create_parser.add_argument('--content', help='笔记内容 (Markdown格式)')
    create_parser.add_argument('--file', help='从文件读取笔记内容')
    create_parser.add_argument('--folder-id', help='关联的笔记本ID')
    create_parser.add_argument('--title', help='笔记标题 (将自动添加为一级标题)')

    # 追加内容命令
    append_parser = subparsers.add_parser('append', help='追加内容到已有笔记')
    append_parser.add_argument('--docid', required=True, help='目标笔记的doc_id')
    append_parser.add_argument('--content', help='要追加的内容')
    append_parser.add_argument('--file', help='从文件读取要追加的内容')

    # 获取笔记内容命令
    get_parser = subparsers.add_parser('get', help='获取笔记内容')
    get_parser.add_argument('--docid', required=True, help='笔记的doc_id')
    get_parser.add_argument('--format', type=int, choices=[0, 1, 2], default=0,
                            help='返回格式: 0=纯文本, 1=Markdown, 2=JSON (默认: 0)')

    args = parser.parse_args()

    # 如果没有提供子命令，打印帮助并退出
    if args.command is None:
        parser.print_help()
        return 0

    # 初始化客户端
    try:
        client = IMANotesClient()
    except ValueError as e:
        print(f"错误: {e}")
        print("请先运行 '请设置环境变量IMA_OPENAPI_CLIENTID和IMA_OPENAPI_APIKEY")
        return 1

    try:
        if args.command == 'search':
            # 构建查询信息
            query_info = {}
            if args.type == 'title':
                query_info['title'] = args.query
            else:  # content
                query_info['content'] = args.query

            # 映射排序方式
            sort_map = {'update': 0, 'create': 1, 'title': 2, 'size': 3}
            sort_type = sort_map[args.sort]

            # 搜索类型映射
            search_type = 0 if args.type == 'title' else 1

            result = client.search_note_book(
                query_info=query_info,
                search_type=search_type,
                sort_type=sort_type,
                start=args.start,
                end=args.end
            )

            print(f"搜索到 {result.get('total_hit_num', 0)} 条结果:")
            print("=" * 80)

            for i, doc in enumerate(result.get('docs', [])):
                basic_info = doc.get('doc', {}).get('basic_info', {})
                title = basic_info.get('title', '无标题')
                docid = basic_info.get('docid', '未知')
                folder_name = basic_info.get('folder_name', '未知笔记本')
                modify_time = client._format_timestamp(basic_info.get('modify_time', 0))

                print(f"{i + 1}. {title}")
                print(f"   文档ID: {docid}")
                print(f"   笔记本: {folder_name}")
                print(f"   修改时间: {modify_time}")

                # 显示高亮信息
                if 'highlight_info' in doc and 'doc_title' in doc['highlight_info']:
                    highlight = doc['highlight_info']['doc_title']
                    # 移除HTML标签
                    import re
                    highlight = re.sub(r'<[^>]+>', '', highlight)
                    print(f"   匹配内容: {highlight[:100]}...")

                print()

            if result.get('is_end', True):
                print("已显示所有结果")
            else:
                print("还有更多结果，可以调整 --start 和 --end 参数查看更多")

        elif args.command == 'list-folders':
            result = client.list_note_folder_by_cursor(
                cursor=args.cursor,
                limit=args.limit
            )

            print("笔记本列表:")
            print("=" * 80)

            for i, folder_item in enumerate(result.get('note_book_folders', [])):
                folder = folder_item.get('folder', {}).get('basic_info', {})
                folder_id = folder.get('folder_id', '未知')
                name = folder.get('name', '无名称')
                note_number = folder.get('note_number', 0)
                folder_type = folder.get('folder_type', -1)
                create_time = client._format_timestamp(folder.get('create_time', 0))

                # 映射文件夹类型
                type_map = {0: '用户自建', 1: '全部笔记', 2: '未分类'}
                type_str = type_map.get(folder_type, f'未知({folder_type})')

                print(f"{i + 1}. {name} ({type_str})")
                print(f"   文件夹ID: {folder_id}")
                print(f"   笔记数量: {note_number}")
                print(f"   创建时间: {create_time}")
                print()

            if result.get('is_end', True):
                print("已显示所有笔记本")
            else:
                print(f"还有更多笔记本，使用 --cursor {result.get('next_cursor', '')} 查看下一页")

        elif args.command == 'list-notes':
            result = client.list_note_by_folder_id(
                folder_id=args.folder_id if args.folder_id else None,
                cursor=args.cursor,
                limit=args.limit
            )

            folder_desc = args.folder_id if args.folder_id else "全部笔记"
            print(f"笔记本 '{folder_desc}' 中的笔记:")
            print("=" * 80)

            for i, note_item in enumerate(result.get('note_book_list', [])):
                basic_info = note_item.get('basic_info', {}).get('basic_info', {})
                title = basic_info.get('title', '无标题')
                docid = basic_info.get('docid', '未知')
                summary = basic_info.get('summary', '无摘要')
                modify_time = client._format_timestamp(basic_info.get('modify_time', 0))

                print(f"{i + 1}. {title}")
                print(f"   文档ID: {docid}")
                print(f"   摘要: {summary[:100]}{'...' if len(summary) > 100 else ''}")
                print(f"   修改时间: {modify_time}")
                print()

            if result.get('is_end', True):
                print("已显示所有笔记")
            else:
                print(f"还有更多笔记，使用 --cursor {result.get('next_cursor', '')} 查看下一页")

        elif args.command == 'create':
            # 获取内容
            content = ""

            if args.file:
                try:
                    with open(args.file, 'r', encoding='utf-8') as f:
                        content = f.read()
                except UnicodeDecodeError:
                    # 尝试其他编码
                    try:
                        with open(args.file, 'r', encoding='gbk') as f:
                            content = f.read()
                    except:
                        print(f"错误: 无法读取文件 {args.file}，请确保文件编码为 UTF-8 或 GBK")
                        return 1
                except Exception as e:
                    print(f"错误: 读取文件失败 - {e}")
                    return 1
            elif args.content:
                content = args.content
            else:
                print("错误: 必须提供 --content 或 --file 参数")
                return 1

            # 如果指定了标题，添加到内容开头
            if args.title:
                content = f"# {args.title}\n\n{content}"

            if not content.strip():
                print("错误: 笔记内容不能为空")
                return 1

            result = client.import_doc(
                content=content,
                folder_id=args.folder_id if args.folder_id else None
            )

            doc_id = result.get('doc_id')
            if doc_id:
                print(f"✅ 笔记创建成功!")
                print(f"文档ID: {doc_id}")
                if args.folder_id:
                    print(f"已保存到笔记本: {args.folder_id}")
            else:
                print(f"⚠️ 笔记创建可能失败，响应: {result}")

        elif args.command == 'append':
            # 获取要追加的内容
            append_content = ""

            if args.file:
                try:
                    with open(args.file, 'r', encoding='utf-8') as f:
                        append_content = f.read()
                except UnicodeDecodeError:
                    try:
                        with open(args.file, 'r', encoding='gbk') as f:
                            append_content = f.read()
                    except:
                        print(f"错误: 无法读取文件 {args.file}，请确保文件编码为 UTF-8 或 GBK")
                        return 1
                except Exception as e:
                    print(f"错误: 读取文件失败 - {e}")
                    return 1
            elif args.content:
                append_content = args.content
            else:
                print("错误: 必须提供 --content 或 --file 参数")
                return 1

            if not append_content.strip():
                print("错误: 追加内容不能为空")
                return 1

            # 确保追加内容以换行开头
            if not append_content.startswith('\n'):
                append_content = '\n' + append_content

            result = client.append_doc(
                doc_id=args.docid,
                content=append_content
            )

            returned_docid = result.get('doc_id')
            if returned_docid and returned_docid == args.docid:
                print(f"✅ 内容追加成功!")
                print(f"目标文档ID: {returned_docid}")
            else:
                print(f"⚠️ 内容追加可能失败，响应: {result}")

        elif args.command == 'get':
            result = client.get_doc_content(
                doc_id=args.docid,
                target_content_format=args.format
            )

            content = result["data"].get('content', '')
            if content:
                print(f"笔记内容 (格式: {args.format}):")
                print("=" * 80)
                print(content)
                print("=" * 80)
            else:
                print(f"⚠️ 未获取到内容，响应: {result}")

    except requests.exceptions.RequestException as e:
        print(f"网络或API请求错误: {e}")
        return 1
    except Exception as e:
        print(f"错误: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())