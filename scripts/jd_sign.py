"""JD bean sign-in, adapted from tech-shrimp/GithubActionSample Part3.

Copyright (c) 2024 TechShrimp技术爬爬虾. See licenses/GithubActionSample-MIT.txt.
The request URL and user agent follow the upstream example.
"""

import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

URL = 'https://api.m.jd.com/client.action?functionId=signBeanAct&body=%7B%22fp%22%3A%22-1%22%2C%22shshshfp%22%3A%22-1%22%2C%22shshshfpa%22%3A%22-1%22%2C%22referUrl%22%3A%22-1%22%2C%22userAgent%22%3A%22-1%22%2C%22jda%22%3A%22-1%22%2C%22rnVersion%22%3A%223.9%22%7D&appid=ld&client=apple&clientVersion=10.0.4&networkType=wifi&osVersion=14.8.1&uuid=3acd1f6361f86fc0a1bc23971b2e7bbe6197afb6&openudid=3acd1f6361f86fc0a1bc23971b2e7bbe6197afb6&jsonp=jsonp_1645885800574_58482'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward the account cookie to a redirect target.
        return None


def parse_response(text):
    text = text.strip()
    if text.startswith("jsonp_"):
        match = re.fullmatch(r"jsonp_\w+\((.*)\);?", text, re.S)
        if not match:
            raise ValueError("Invalid JSONP")
        text = match.group(1)
    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError("Expected an object")
    return result


def classify(result):
    if str(result.get("code")) == "3":
        return False, "京东返回未登录或登录已失效，请更新 JD_COOKIE。"
    if str(result.get("code")) != "0":
        return False, "京东接口拒绝请求，签到未确认；请检查 Cookie 或上游接口兼容性。"
    data = result.get("data")
    if not isinstance(data, dict):
        return False, "京东未返回有效签到结果。"
    if str(data.get("status")) == "1":
        return True, "京东京豆签到成功。"
    if str(data.get("status")) == "2":
        return True, "京东京豆今日已签到。"
    return False, "京东返回未识别的签到状态，不能确认签到成功。"


def report(message, success):
    print(message)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as output:
            output.write("### 京东京豆签到\n\n" + message + "\n")
    return 0 if success else 1


def main():
    cookie = os.environ.get("JD_COOKIE", "").strip()
    if not cookie or "\r" in cookie or "\n" in cookie:
        return report("JD_COOKIE 缺失或格式无效，请在仓库 Actions Secrets 中配置。", False)
    request = Request(URL, data=b"", method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Cache-Control": "no-cache",
        "User-Agent": "okhttp/3.12.1;jdmall;android;version/10.3.4;build/92451;",
        "Accept": "*/*",
        "Cookie": cookie,
    })
    try:
        with build_opener(NoRedirect).open(request, timeout=30) as response:
            result = parse_response(response.read().decode("utf-8"))
    except HTTPError as error:
        return report(f"京东接口返回 HTTP {error.code}，签到未确认。", False)
    except (URLError, TimeoutError, OSError, ValueError):
        # Never print raw responses, exception details, cookies or account data.
        return report("网络请求失败或京东响应格式不兼容，签到未确认。", False)
    success, message = classify(result)
    return report(message, success)


if __name__ == "__main__":
    sys.exit(main())
