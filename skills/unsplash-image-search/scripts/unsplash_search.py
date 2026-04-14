#!/usr/bin/env python3
"""
Unsplash 图片搜索脚本
支持自定义每页数量(per_page)和页码(page)参数
"""
import argparse
import os
import requests
import json
import sys
def main():
    parser = argparse.ArgumentParser(description='Unsplash Image Search')
    parser.add_argument('--query', type=str, required=True,
                        help='搜索关键词，如 "深圳 海岸线"')
    parser.add_argument('--per_page', type=int, default=1,
                        help='每页返回图片数量，默认1，最大30')
    parser.add_argument('--page', type=int, default=1,
                        help='页码，默认第1页')

    args = parser.parse_args()

    # 1. 读取环境变量
    access_key = os.getenv('UNSPLASH_ACCESS_KEY')
    if not access_key:
        print(json.dumps({"error": "缺少环境变量 UNSPLASH_ACCESS_KEY"}))
        sys.exit(1)

    # 2. 参数验证
    if args.per_page < 1 or args.per_page > 30:
        print(json.dumps({"error": "per_page 参数必须在1-30之间"}))
        sys.exit(1)

    if args.page < 1:
        print(json.dumps({"error": "page 参数必须大于0"}))
        sys.exit(1)

    # 3. 构造 API 请求
    url = "https://api.unsplash.com/search/photos"
    headers = {
        "Authorization": f"Client-ID {access_key}",
        "Accept-Version": "v1"
    }
    params = {
        "query": args.query,
        "per_page": args.per_page,
        "page": args.page
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        # 4. 提取关键信息
        results = []
        for item in data.get('results', []):
            results.append({
                "id": item.get('id'),
                "description": item.get('description') or item.get('alt_description') or '无描述',
                "url": item.get('urls', {}).get('regular'),
                "download": item.get('links', {}).get('download'),
                "author": item.get('user', {}).get('name', '未知作者'),
                "author_profile": item.get('user', {}).get('links', {}).get('html', ''),
                "color": item.get('color', '')
            })

        # 5. 输出结构化 JSON
        output = {
            "query": args.query,
            "per_page": args.per_page,
            "page": args.page,
            "total": data.get('total'),
            "total_pages": data.get('total_pages'),
            "images": results
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except requests.exceptions.RequestException as e:
        print(json.dumps({"error": f"API 请求失败: {str(e)}"}))
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"JSON 解析失败: {str(e)}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()