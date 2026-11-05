# -*- coding: utf-8 -*-
"""极简 HTTP 层：只用标准库，带重试与明确的失败类型。

设计原则：拿不到就抛异常，绝不返回空内容冒充成功——这是不变量第 6 条。
"""
import gzip
import time
import urllib.error
import urllib.request
import zlib

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/json,application/pdf;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
    "Accept-Encoding": "gzip, deflate",
}


_CACHE: dict[str, bytes] = {}


class FetchError(RuntimeError):
    """网络或 HTTP 层失败。调用方必须把它当成「没抓到」，不能当成「无变化」。"""

    def __init__(self, url: str, reason: str, status: int | None = None):
        self.url, self.reason, self.status = url, reason, status
        super().__init__(f"{reason} ({status}) {url}" if status else f"{reason} {url}")


def _decode_body(raw: bytes, encoding: str) -> bytes:
    enc = (encoding or "").lower()
    if enc == "gzip":
        return gzip.decompress(raw)
    if enc == "deflate":
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw


def get(url: str, *, timeout: int = 30, retries: int = 3, headers: dict | None = None, cache: bool = False) -> bytes:
    """GET 一个 URL。失败重试 retries 次（指数退避），最终仍失败则抛 FetchError。"""
    if cache and url in _CACHE:
        return _CACHE[url]

    hdrs = dict(DEFAULT_HEADERS)
    if headers:
        hdrs.update(headers)

    last: FetchError | None = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = _decode_body(resp.read(), resp.headers.get("Content-Encoding", ""))
                if not body:
                    raise FetchError(url, "响应为空", resp.status)
                if cache:
                    _CACHE[url] = body
                return body
        except urllib.error.HTTPError as e:
            last = FetchError(url, "HTTP 错误", e.code)
            # 4xx 除 429 外重试没有意义
            if 400 <= e.code < 500 and e.code != 429:
                break
        except urllib.error.URLError as e:
            last = FetchError(url, f"连接失败: {getattr(e, 'reason', e)}")
        except (TimeoutError, OSError) as e:
            last = FetchError(url, f"网络异常: {e}")

        if attempt < retries - 1:
            time.sleep(2 ** attempt)

    raise last or FetchError(url, "未知错误")


def head_status(url: str, *, timeout: int = 20) -> int:
    """只取状态码，用于探测文档是否存在。失败抛 FetchError。"""
    req = urllib.request.Request(url, headers=DEFAULT_HEADERS, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:  # noqa: BLE001
        raise FetchError(url, f"HEAD 失败: {e}")
