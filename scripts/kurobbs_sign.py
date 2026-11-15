#!/usr/bin/env python3
"""Headless sign-in, following SignService and KujiequRoleApi (stdlib only)."""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

BASE_URL = "https://api.kurobbs.com"
SERVER_ID = "76402e5b20be2c39f095a152090afddc"
ROLE_PATH = "/gamer/role/list"
INIT_PATH = "/encourage/signIn/initSignInV2"
SIGN_PATH = "/encourage/signIn/v2"
CHINA = ZoneInfo("Asia/Shanghai")
USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 9; 23116PN5BC Build/PQ3A.190605.02201427; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/124.0.6367.82 "
    "Mobile Safari/537.36 Kuro/2.5.0 KuroGameBox/2.5.0"
)


class SignError(Exception):
    """Only locally constructed, credential-free messages may use this exception."""


@dataclass(frozen=True, repr=False)
class Account:
    token: str
    devcode: str = ""
    source: str = "h5"


def header_value(value: object, field: str, *, optional: bool = False) -> str:
    if not isinstance(value, str):
        raise SignError(f"{field} 必须是字符串")
    value = value.strip()
    if (not value and not optional) or any(ord(c) < 32 or ord(c) > 126 for c in value):
        raise SignError(f"{field} 为空或包含非法请求头字符")
    return value


def parse_credential(value: object, devcode: object = "", source: object = "h5") -> Account:
    if source not in ("h5", "android"):
        raise SignError("source 必须为 h5（网页）或 android（App）")
    raw = header_value(value, "Cookie/Token")
    if raw.lower().startswith("cookie:"):
        raw = raw[7:].strip()
    # A bare token (including trailing base64 '=') is accepted. Cookie input
    # must contain the token field; unrelated browser cookies cannot log in.
    looks_like_cookie = ";" in raw or raw.lower().startswith(("token=", "devcode="))
    if looks_like_cookie:
        jar = SimpleCookie()
        try:
            jar.load(raw)
        except CookieError:
            raise SignError("Cookie 格式无效，请改用请求头中的 token") from None
        if "token" not in jar:
            raise SignError("Cookie 中没有 token，请复制网页 API 请求头中的 token")
        token = unquote(jar["token"].value)
        if not devcode and "devcode" in jar:
            devcode = unquote(jar["devcode"].value)
    else:
        if "=" in raw.rstrip("=") or any(c.isspace() for c in raw):
            raise SignError("未识别到 token，请复制网页 API 请求头中的 token")
        token = raw
    return Account(header_value(token, "token"), header_value(devcode, "devcode", optional=True), source)


def load_accounts(env: dict | os._Environ) -> list[Account]:
    multiple = env.get("KUROBBS_ACCOUNTS", "").strip()
    single = env.get("KUROBBS_COOKIE", "").strip()
    if multiple and single:
        raise SignError("KUROBBS_COOKIE 与 KUROBBS_ACCOUNTS 只能配置一个")
    if multiple:
        try:
            entries = json.loads(multiple)
        except ValueError:
            raise SignError("KUROBBS_ACCOUNTS 必须是有效的 JSON 数组") from None
        if not isinstance(entries, list) or not 1 <= len(entries) <= 9:
            raise SignError("KUROBBS_ACCOUNTS 必须包含 1 至 9 个账号")
        accounts = []
        for entry in entries:
            if not isinstance(entry, dict) or bool(entry.get("token")) == bool(entry.get("cookie")):
                raise SignError("每个账号必须且只能提供 token 或 cookie，并可选填 devcode/source")
            accounts.append(parse_credential(
                entry.get("token") or entry.get("cookie"),
                entry.get("devcode", ""), entry.get("source", "h5"),
            ))
        return accounts
    if single:
        return [parse_credential(single, env.get("KUROBBS_DEVCODE", ""), env.get("KUROBBS_SOURCE", "h5"))]
    raise SignError("缺少凭据：请在 Actions Secrets 设置 KUROBBS_COOKIE 或 KUROBBS_ACCOUNTS")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the custom token header to a redirect destination.
        return None


class KuroClient:
    def __init__(self, account: Account):
        self.account = account
        self.opener = build_opener(NoRedirect())

    def request(self, path: str, params: dict, *, retry: bool = True) -> dict:
        request = Request(
            BASE_URL + path + "?" + urlencode(params),
            data=b"",  # The Java implementation uses POST with query parameters.
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json, text/plain, */*",
                "User-Agent": USER_AGENT,
                "source": self.account.source,
                "token": self.account.token,
                "devcode": self.account.devcode,
                "Origin": "https://web-static.kurobbs.com",
                "x-requested-with": "com.kurogame.kjq",
            },
            method="POST",
        )
        attempts = 3 if retry else 1
        for attempt in range(attempts):
            try:
                with self.opener.open(request, timeout=20) as response:
                    payload = response.read(2_000_001)
                if len(payload) > 2_000_000:
                    raise SignError("接口响应过大")
                result = json.loads(payload)
                if not isinstance(result, dict) or type(result.get("code")) is not int:
                    raise SignError("接口响应结构异常")
                return result
            except HTTPError as exc:
                status = exc.code
                exc.close()
                if status in (401, 403):
                    raise SignError("HTTP 鉴权失败或请求被拦截，请检查网页登录与凭据") from None
                if status != 429 and not 500 <= status <= 599:
                    raise SignError(f"HTTP 请求失败（状态码 {status}）") from None
                error = f"HTTP 请求失败（状态码 {status}）"
            except (URLError, TimeoutError, socket.timeout, OSError):
                error = "网络连接失败或超时"
            except (ValueError, UnicodeError):
                raise SignError("接口未返回有效 JSON，可能受到风控或接口已变更") from None
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
        raise SignError(error)


def require_success(response: dict) -> None:
    code = response.get("code")
    message = response.get("msg", "")
    if code == 220 or (isinstance(message, str) and "登录已过期" in message):
        raise SignError("登录已过期或来源不匹配，请检查 source（h5/android）并更新对应来源的 Token")
    if code != 200 or response.get("success") is False:
        # Do not print server messages: they can contain personal data or tokens.
        suffix = str(code) if type(code) is int else "未知"
        raise SignError(f"业务请求失败（代码 {suffix}），请在网页检查账号状态")


def role_params(role: object) -> dict:
    if not isinstance(role, dict):
        raise SignError("角色信息格式异常")
    result = {"gameId": "3", "serverId": role.get("serverId") or SERVER_ID}
    for key in ("roleId", "userId"):
        value = role.get(key)
        if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).isdigit():
            raise SignError("角色信息缺少有效的 roleId/userId")
        result[key] = str(value)
    if not isinstance(result["serverId"], str):
        raise SignError("角色信息中的 serverId 格式异常")
    return result


def signed_today(response: dict) -> bool:
    require_success(response)
    data = response.get("data")
    if not isinstance(data, dict):
        raise SignError("签到状态响应缺少 data")
    flag = data.get("isSigIn")
    if type(flag) is bool:
        return flag
    if type(flag) is int and flag in (0, 1):
        return bool(flag)
    if flag in ("true", "false", "0", "1"):
        return flag in ("true", "1")
    raise SignError("签到状态响应缺少有效的 isSigIn")


def sign_role(client: KuroClient, role: object, now: datetime | None = None) -> str:
    params = role_params(role)
    if signed_today(client.request(INIT_PATH, params)):
        return "今日已签到"
    month = (now or datetime.now(CHINA)).astimezone(CHINA).strftime("%m")
    try:
        # Do not blindly retry a mutating request after a timeout. Recheck state.
        response = client.request(SIGN_PATH, {**params, "reqMonth": month}, retry=False)
        require_success(response)
    except SignError:
        if signed_today(client.request(INIT_PATH, params)):
            return "已确认今日签到完成"
        raise
    if not signed_today(client.request(INIT_PATH, params)):
        raise SignError("提交后仍未确认签到成功，请稍后重试")
    return "签到成功"


def run(accounts: list[Account], client_factory=KuroClient) -> tuple[list[str], bool]:
    lines = []
    failed = False
    for index, account in enumerate(accounts, 1):
        label = f"账号 {index}"
        try:
            client = client_factory(account)
            response = client.request(ROLE_PATH, {"gameId": "3"})
            require_success(response)
            roles = response.get("data")
            if not isinstance(roles, list) or not roles:
                raise SignError("未找到绑定角色，请先在库街区绑定国服鸣潮角色")
        except SignError as exc:
            failed = True
            lines.append(f"{label}：失败，{exc}")
            continue
        for role_index, role in enumerate(roles, 1):
            try:
                status = sign_role(client, role)
            except SignError as exc:
                failed = True
                status = f"失败，{exc}"
            lines.append(f"{label} / 角色 {role_index}：{status}")
    return lines, failed


def main() -> int:
    try:
        lines, failed = run(load_accounts(os.environ))
    except SignError as exc:
        lines, failed = [f"配置失败：{exc}"], True
    except Exception:
        # Suppress raw tracebacks/response text in public Actions logs.
        lines, failed = ["运行异常，请检查配置及接口兼容性（未输出敏感上下文）"], True
    report = "\n".join([f"库街区签到 · {datetime.now(CHINA):%Y-%m-%d %H:%M:%S}（北京时间）", *lines])
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        Path(summary).write_text(report + "\n", encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
