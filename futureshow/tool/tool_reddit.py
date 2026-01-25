import os
import json
import http.client
import urllib.parse
from datetime import datetime
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv
from agents import function_tool

load_dotenv()


def _get_rapidapi_key() -> str:
    key = os.environ.get("RAPIDAPI_KEY")
    if not key:
        raise ValueError("RAPIDAPI_KEY not set in environment (.env)")
    return key

def _collect_text_from_item(item: Dict[str, Any]) -> str:
    """
    从可能的字段里聚合可检索文本，尽量兼容不同返回结构。
    优先字段：title/selftext/body/text/content/description
    """
    text_fields = []
    for k in item.keys():
        lk = k.lower()
        if any(x in lk for x in ["title", "selftext", "body", "text", "content", "description"]):
            v = item.get(k)
            if isinstance(v, str) and v.strip():
                text_fields.append(v)
    return "\n".join(text_fields)


def _iter_candidate_items(data: Any) -> List[Dict[str, Any]]:
    """
    尝试在任意嵌套结构中提取“像帖子”的字典条目，
    规则：字典中包含 title/selftext/body/text/content/description 任一字段
    """
    candidates: List[Dict[str, Any]] = []

    def walk(node: Any):
        if isinstance(node, dict):
            # 判断是否像帖子条目
            keys_lower = [k.lower() for k in node.keys()]
            if any(x in keys_lower for x in ["title", "selftext", "body", "text", "content", "description"]):
                candidates.append(node)
            # 继续遍历子节点
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for it in node:
                walk(it)

    walk(data)
    return candidates


def _filter_items_by_keywords(items: List[Dict[str, Any]], keep_keywords: Optional[List[str]]) -> List[Dict[str, Any]]:
    if not keep_keywords:
        return items
    kws = [k.lower() for k in keep_keywords if isinstance(k, str) and k.strip()]
    if not kws:
        return items
    filtered: List[Dict[str, Any]] = []
    for it in items:
        corpus = _collect_text_from_item(it).lower()
        if any(kw in corpus for kw in kws):
            filtered.append(it)
    return filtered


UNWANTED_IMAGE_HOSTS = {
    "i.redd.it",
    "v.redd.it",
    "preview.redd.it",
    "external-preview.redd.it",
    "i.redditmedia.com",
    "redditmedia.com",
    "i.redditstatic.com",
}


def _normalize_host(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).netloc or "").lower()
    except Exception:
        return ""


def _select_links(r: Dict[str, Any], link_preference: str) -> List[str]:
    pref = (link_preference or "permalink").lower()
    permalink = f"https://www.reddit.com{r.get('permalink')}" if r.get("permalink") else ""
    external = r.get("url") or ""
    # 过滤图床域名外链
    if external and _normalize_host(external) in UNWANTED_IMAGE_HOSTS:
        external = ""

    if pref == "permalink":
        return [permalink] if permalink else ([external] if external else [])
    if pref == "external":
        return [external] if external else ([permalink] if permalink else [])
    if pref == "both":
        links: List[str] = []
        if permalink:
            links.append(permalink)
        if external:
            links.append(external)
        return links
    # 默认回退到 permalink
    return [permalink] if permalink else ([external] if external else [])


@function_tool
def reddit_search(
    query: str,
    filter: str = "posts",
    time_filter: str = "year",
    sort_type: str = "relevance",
    keep_keywords: Optional[List[str]] = None,
    link_preference: str = "permalink",
    snippet_chars: int = 800,
) -> str:
    """
    通过 RapidAPI reddit3 搜索 Reddit 内容，返回整理后的文本结果（不写入文件）。

    Args:
        query: 搜索关键词
        filter: 搜索类型（posts/comments），默认 posts
        time_filter: 时间范围（hour/day/week/month/year/all），默认 year
        sort_type: 排序（relevance/new/top/comments），默认 relevance
        keep_keywords: 需要保留的关键词列表（可选，若为空则不做过滤）
        link_preference: 链接偏好：'permalink' | 'external' | 'both'（默认 'permalink'）
        snippet_chars: Snippet 最大字符数（默认 800）

    Returns:
        文本字符串：包含若干条结果（URL/Title/Subreddit/Author/Score/Comments/Created/Snippet）
    """
    # 构建请求
    api_key = _get_rapidapi_key()
    conn = http.client.HTTPSConnection("reddit3.p.rapidapi.com")
    headers = {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": "reddit3.p.rapidapi.com",
    }
    encoded_query = urllib.parse.quote(query)
    fparam = urllib.parse.quote(filter or "posts")
    tparam = urllib.parse.quote(time_filter or "year")
    sparam = urllib.parse.quote(sort_type or "relevance")
    url = f"/v1/reddit/search?search={encoded_query}&filter={fparam}&timeFilter={tparam}&sortType={sparam}"

    # 发起请求
    conn.request("GET", url, headers=headers)
    res = conn.getresponse()
    raw_text = res.read().decode("utf-8", errors="replace")
    conn.close()

    # 解析 JSON（尽量不因异常而中断）
    parsed: Any
    try:
        parsed = json.loads(raw_text)
    except Exception:
        parsed = {"raw": raw_text}

    # 提取候选条目并过滤
    items = []
    body = parsed.get("body") if isinstance(parsed, dict) else None
    if isinstance(body, list):
        items = body
    else:
        items = _iter_candidate_items(parsed)

    filtered_items = _filter_items_by_keywords(items, keep_keywords)

    # 组装返回文本（最多展示 10 条，避免过长）
    def to_iso(ts: Optional[float]) -> str:
        try:
            if ts is None:
                return ""
            return datetime.utcfromtimestamp(float(ts)).isoformat() + "Z"
        except Exception:
            return ""

    def clean_snippet(text: Optional[str], limit: int = 800) -> str:
        if not isinstance(text, str):
            return ""
        s = " ".join(text.split())
        return s[:limit] + ("..." if len(s) > limit else "")

    results = filtered_items or items
    if not results:
        return f"⚠️ No results for query: {query}"

    blocks: List[str] = []
    for r in results[:10]:
        title = r.get("title") or ""
        subreddit = r.get("subreddit") or r.get("subreddit_name_prefixed") or ""
        author = r.get("author") or ""
        score = r.get("score") if r.get("score") is not None else r.get("ups")
        comments = r.get("num_comments")
        links = _select_links(r, link_preference)
        created = to_iso(r.get("created_utc"))
        snippet = clean_snippet(r.get("selftext") or r.get("body") or r.get("text") or r.get("description"), limit=snippet_chars)

        block = []
        # 链接输出逻辑
        pref = (link_preference or "permalink").lower()
        if pref == "both":
            # 明确区分
            permalink = f"https://www.reddit.com{r.get('permalink')}" if r.get("permalink") else ""
            external = r.get("url") or ""
            if external and _normalize_host(external) in UNWANTED_IMAGE_HOSTS:
                external = ""
            if permalink:
                block.append(f"Permalink: {permalink}")
            if external:
                block.append(f"ExternalURL: {external}")
        else:
            url_line = links[0] if links else ""
            if url_line:
                block.append(f"URL: {url_line}")

        block.extend([
            f"Title: {title}",
            f"Subreddit: {subreddit}",
            f"Author: {author}",
            f"Score: {score}",
            f"Comments: {comments}",
            f"CreatedUTC: {created}",
        ])
        if snippet:
            block.append(f"Snippet: {snippet}")
        blocks.append("\n".join(block))

    header = [
        f"Query: {query}",
        f"Total items: {len(items)}",
        f"Matched items: {len(filtered_items)}" if keep_keywords else None,
    ]
    header = "\n".join([h for h in header if h])
    return header + "\n\n" + "\n\n".join(blocks)


def _iter_comment_items(data: Any) -> List[Dict[str, Any]]:
    comments: List[Dict[str, Any]] = []
    def walk(node: Any):
        if isinstance(node, dict):
            body = node.get("body")
            author = node.get("author")
            # 评论通常有 body + author（帖子自帖为 selftext）
            if isinstance(body, str) and author is not None:
                comments.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for it in node:
                walk(it)
    walk(data)
    return comments


def _walk_all_dicts(node: Any):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk_all_dicts(v)
    elif isinstance(node, list):
        for it in node:
            yield from _walk_all_dicts(it)


def _find_post_object(parsed: Any) -> Optional[Dict[str, Any]]:
    # 1) 典型：body.post
    if isinstance(parsed, dict):
        body = parsed.get("body")
        if isinstance(body, dict):
            p = body.get("post")
            if isinstance(p, dict):
                return p
            # 直接平铺在 body
            if any(k in body for k in ["title", "selftext", "permalink", "subreddit"]):
                return body
        # 顶层 post
        p = parsed.get("post")
        if isinstance(p, dict):
            return p

    # 2) 广泛扫描：优先含 permalink 且 (title 或 subreddit)
    fallback_title = None
    for d in _walk_all_dicts(parsed):
        keys = {k.lower() for k in d.keys()}
        if "permalink" in keys and ("title" in keys or "subreddit" in keys):
            return d
        if fallback_title is None and "title" in keys:
            fallback_title = d
    return fallback_title


def _candidate_post_urls(post_url: str) -> List[str]:
    """
    构造多种候选帖子 URL（不同域名/是否带 slug/是否带结尾斜杠），以兼容 reddit3 的校验。
    """
    try:
        u = urllib.parse.urlparse(post_url)
    except Exception:
        return [post_url]

    # 规范化路径：/r/<sub>/comments/<id>/[slug/]
    parts = [p for p in (u.path or "").split("/") if p]
    base_path = None
    if len(parts) >= 4 and parts[0] == "r" and parts[2] == "comments":
        subreddit = parts[1]
        post_id = parts[3]
        base_path = f"/r/{subreddit}/comments/{post_id}/"

    candidates: List[str] = []
    # 原始
    original = urllib.parse.urlunparse((u.scheme or "https", u.netloc or "www.reddit.com", u.path or "/", "", "", ""))
    candidates.append(original)
    # 去掉结尾斜杠/或补上
    if original.endswith("/"):
        candidates.append(original[:-1])
    else:
        candidates.append(original + "/")
    # 仅使用基础 /comments/<id>/（无 slug）
    if base_path:
        base_www = urllib.parse.urlunparse(("https", "www.reddit.com", base_path, "", "", ""))
        base_no_www = urllib.parse.urlunparse(("https", "reddit.com", base_path, "", "", ""))
        candidates.append(base_www)
        candidates.append(base_no_www)
    # 替换域名为 reddit.com（无 www）
    if u.netloc == "www.reddit.com":
        candidates.append(urllib.parse.urlunparse((u.scheme or "https", "reddit.com", u.path or "/", "", "", "")))
    elif u.netloc == "reddit.com":
        candidates.append(urllib.parse.urlunparse((u.scheme or "https", "www.reddit.com", u.path or "/", "", "", "")))

    # 去重保持顺序
    uniq: List[str] = []
    seen = set()
    for c in candidates:
        if c and c not in seen:
            uniq.append(c)
            seen.add(c)
    return uniq


@function_tool
def reddit_post_details(
    post_url: str,
    include_comments: bool = True,
    max_comments: int = 5,
    link_preference: str = "permalink",
    snippet_chars: int = 1200,
    comment_snippet_chars: int = 600,
) -> str:
    """
    获取单个 Reddit 帖子详情（可选包含热门评论），返回整理后的文本结果（不写入文件）。

    Args:
        post_url: Reddit 帖子完整 URL（例如 https://www.reddit.com/r/.../comments/<id>/<slug>/）
        include_comments: 是否包含评论（默认 True）
        max_comments: 返回的评论最大条数（默认 5）
        link_preference: 链接偏好：'permalink' | 'external' | 'both'（默认 'permalink'）
        snippet_chars: Snippet 最大字符数（默认 800）

    Returns:
        文本字符串：帖子详情 +（可选）前 N 条评论（Author/Score/Created/CommentPermalink/Snippet）
    """
    # 构建请求与候选 URL 尝试
    api_key = _get_rapidapi_key()
    headers = {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": "reddit3.p.rapidapi.com",
    }

    raw_text = ""
    parsed: Any = {}
    api_error_message: Optional[str] = None
    tried_urls = _candidate_post_urls(post_url)
    for candidate in tried_urls:
        try:
            encoded = urllib.parse.quote(candidate, safe="")
            url = f"/v1/reddit/post?url={encoded}"
            conn = http.client.HTTPSConnection("reddit3.p.rapidapi.com")
            conn.request("GET", url, headers=headers)
            res = conn.getresponse()
            raw_text = res.read().decode("utf-8", errors="replace")
            conn.close()
        except Exception:
            raw_text = ""
            parsed = {}
            continue

        # 解析 JSON
        try:
            parsed = json.loads(raw_text)
        except Exception:
            parsed = {"raw": raw_text}

        # 若接口返回 success=false，记录信息继续尝试下一个候选
        if isinstance(parsed, dict) and parsed.get("success") is False:
            api_error_message = str(parsed.get("message") or parsed.get("error") or "invalid url")
            continue

        # 若能找到帖子对象则跳出循环
        if _find_post_object(parsed):
            break

    # 若依然无法解析且有明确 API 错误，直出错误信息
    if (not isinstance(parsed, dict) or not _find_post_object(parsed)) and api_error_message:
        return f"❌ Reddit API error: {api_error_message}"

    # 元信息错误提示（不阻断解析）
    if isinstance(parsed, dict) and isinstance(parsed.get("meta"), dict):
        status = parsed["meta"].get("status")
        if isinstance(status, int) and status != 200:
            message = parsed["meta"].get("message") or parsed["meta"].get("error")
            # 直接返回更清晰的错误
            return f"❌ Reddit API error (status={status}): {message or 'unknown error'}"

    # 提取帖子对象
    post_obj: Optional[Dict[str, Any]] = _find_post_object(parsed)
    if not post_obj:
        candidates = _iter_candidate_items(parsed)
        # 选择包含 title 的第一个作为帖子
        for c in candidates:
            if isinstance(c.get("title"), str):
                post_obj = c
                break

    if not post_obj:
        return f"⚠️ Unable to parse post details for URL: {post_url}"

    # 时间与摘要工具
    def to_iso(ts: Optional[float]) -> str:
        try:
            if ts is None:
                return ""
            return datetime.utcfromtimestamp(float(ts)).isoformat() + "Z"
        except Exception:
            return ""

    def make_snippet(text: Optional[str], limit: int = 800) -> str:
        if not isinstance(text, str):
            return ""
        s = " ".join(text.split())
        return s[:limit] + ("..." if len(s) > limit else "")

    # 帖子主信息
    title = post_obj.get("title") or ""
    subreddit = post_obj.get("subreddit") or post_obj.get("subreddit_name_prefixed") or ""
    author = post_obj.get("author") or ""
    score = post_obj.get("score") if post_obj.get("score") is not None else post_obj.get("ups")
    num_comments = post_obj.get("num_comments")
    created = to_iso(post_obj.get("created_utc") or post_obj.get("created"))
    links = _select_links(post_obj, link_preference)
    self_snippet = make_snippet(post_obj.get("selftext") or post_obj.get("text") or post_obj.get("description"), limit=snippet_chars)

    lines: List[str] = []
    pref = (link_preference or "permalink").lower()
    if pref == "both":
        permalink = f"https://www.reddit.com{post_obj.get('permalink')}" if post_obj.get("permalink") else ""
        external = post_obj.get("url") or ""
        if external and _normalize_host(external) in UNWANTED_IMAGE_HOSTS:
            external = ""
        if permalink:
            lines.append(f"Permalink: {permalink}")
        if external:
            lines.append(f"ExternalURL: {external}")
    else:
        url_line = links[0] if links else ""
        if url_line:
            lines.append(f"URL: {url_line}")

    lines.extend([
        f"Title: {title}",
        f"Subreddit: {subreddit}",
        f"Author: {author}",
        f"Score: {score}",
        f"Comments: {num_comments}",
        f"CreatedUTC: {created}",
    ])
    # 如 meta.totalComments 存在则显示
    try:
        total_comments_meta = parsed.get("meta", {}).get("totalComments") if isinstance(parsed, dict) else None
        if total_comments_meta is not None:
            lines.append(f"TotalComments(meta): {total_comments_meta}")
    except Exception:
        pass
    # 附加更多可用字段（存在即显示）
    def add_if_present(label: str, value: Any):
        if value is None:
            return
        if isinstance(value, (list, dict)) and not value:
            return
        lines.append(f"{label}: {value}")

    add_if_present("Flair", post_obj.get("link_flair_text"))
    if isinstance(post_obj.get("link_flair_richtext"), list):
        rt = " ".join([str(x.get("t")) for x in post_obj.get("link_flair_richtext") if isinstance(x, dict) and x.get("t")])
        add_if_present("FlairRich", rt or None)
    add_if_present("UpvoteRatio", post_obj.get("upvote_ratio"))
    edited = post_obj.get("edited")
    if isinstance(edited, (int, float)):
        add_if_present("EditedUTC", to_iso(edited))
    elif edited:
        add_if_present("Edited", edited)
    add_if_present("Domain", post_obj.get("domain"))
    add_if_present("Over18", post_obj.get("over_18"))
    add_if_present("Spoiler", post_obj.get("spoiler"))
    add_if_present("Stickied", post_obj.get("stickied"))
    add_if_present("Locked", post_obj.get("locked"))
    add_if_present("Archived", post_obj.get("archived"))
    add_if_present("NumCrossposts", post_obj.get("num_crossposts"))
    add_if_present("SubredditSubscribers", post_obj.get("subreddit_subscribers"))
    add_if_present("TotalAwards", post_obj.get("total_awards_received"))
    gild = post_obj.get("gildings")
    if isinstance(gild, dict) and gild:
        parts = [f"{k}:{v}" for k, v in gild.items() if v]
        add_if_present("Gildings", ", ".join(parts) if parts else None)
    add_if_present("IsVideo", post_obj.get("is_video"))
    if isinstance(post_obj.get("gallery_data"), dict):
        items = post_obj["gallery_data"].get("items")
        if isinstance(items, list):
            add_if_present("GalleryCount", len(items))
    if self_snippet:
        lines.append(f"Snippet: {self_snippet}")
    else:
        # 自帖内容为空且为外链贴，额外展示 ExternalURL（即使在 permalink 模式）
        ext = post_obj.get("url_overridden_by_dest") or post_obj.get("url")
        if isinstance(ext, str) and ext and _normalize_host(ext) not in UNWANTED_IMAGE_HOSTS:
            lines.append(f"ExternalURL: {ext}")

    if not include_comments:
        return "\n".join(lines)

    # 提取评论
    raw_comments: List[Dict[str, Any]] = []
    if isinstance(parsed, dict):
        # 优先从 body.comments 读取
        body = parsed.get("body") if isinstance(parsed.get("body"), dict) else None
        if body and isinstance(body.get("comments"), list):
            raw_comments = [c for c in body.get("comments") if isinstance(c, dict)]
        elif body and isinstance(body.get("post_comments"), list):
            # 兼容 reddit3 返回的 post_comments（字段名与结构与 comments 不同）
            raw_comments = [c for c in body.get("post_comments") if isinstance(c, dict)]
        elif isinstance(parsed.get("comments"), list):
            raw_comments = [c for c in parsed.get("comments") if isinstance(c, dict)]
    if not raw_comments:
        raw_comments = _iter_comment_items(parsed)

    if not raw_comments:
        return "\n".join(lines)

    def comment_score(c: Dict[str, Any]) -> int:
        v = c.get("score")
        if v is None:
            v = c.get("ups")
        try:
            return int(v or 0)
        except Exception:
            return 0

    top_comments = sorted(raw_comments, key=comment_score, reverse=True)[: max(0, int(max_comments))]

    blocks: List[str] = []
    for c in top_comments:
        cauthor = c.get("author") or ""
        cscore = c.get("score") if c.get("score") is not None else (c.get("ups") if c.get("ups") is not None else c.get("up_votes"))
        ccreated = to_iso(c.get("created_utc") or c.get("created"))
        cperm = c.get("permalink")
        cbody = make_snippet(c.get("body") or c.get("content"), limit=comment_snippet_chars)
        cdist = c.get("distinguished")
        cstick = c.get("stickied")
        replies = c.get("replies")
        if isinstance(replies, list):
            rcount = len(replies)
        elif isinstance(replies, dict):
            rcount = None
        else:
            rcount = None
        block = [
            f"Author: {cauthor}",
            f"Score: {cscore}",
            f"CreatedUTC: {ccreated}",
        ]
        if isinstance(cperm, str) and cperm:
            block.append(f"CommentPermalink: https://www.reddit.com{cperm}")
        if cdist:
            block.append(f"Distinguished: {cdist}")
        if cstick:
            block.append("Stickied: True")
        if rcount is not None:
            block.append(f"Replies: {rcount}")
        if cbody:
            block.append(f"Snippet: {cbody}")
        blocks.append("\n".join(block))

    return "\n".join(lines) + ("\n\nTop comments:\n" + "\n\n".join(blocks) if blocks else "")


if __name__ == "__main__":
    import asyncio
    from agents.tool_context import ToolContext

    ctx_post = ToolContext(
        context=None,
        tool_name="reddit_post_details",
        tool_call_id="reddit-post-test",
        tool_arguments='{"post_url":"https://www.reddit.com/r/technology/comments/1msj8xh/as_people_ridicule_gpt5_sam_altman_says_openai/","include_comments":true,"max_comments":5, "snippet_chars":1600, "comment_snippet_chars":800}'
    )
    out_post = asyncio.run(
        reddit_post_details.on_invoke_tool(
            ctx_post,
            '{"post_url":"https://www.reddit.com/r/technology/comments/1msj8xh/as_people_ridicule_gpt5_sam_altman_says_openai/","include_comments":true,"max_comments":5, "snippet_chars":1600, "comment_snippet_chars":800}'
        )
    )
    print(out_post)

