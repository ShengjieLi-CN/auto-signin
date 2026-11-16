# 自动签到

使用 GitHub Actions 托管日常签到任务，目前支持**库街区国服鸣潮**和**京东京豆签到**，无需常驻电脑。库街区支持网页与 App Token、多个账号及绑定角色。

本项目从 [ShengjieLi-CN/WutheringWavesTool](https://github.com/ShengjieLi-CN/WutheringWavesTool) 独立迁出，仅包含签到脚本、测试、文档和工作流。接口调用方式参考 [leck995/WutheringWavesTool](https://github.com/leck995/WutheringWavesTool) 中的签到及角色查询实现。

## 京东京豆签到（Part3）

改编自 [tech-shrimp/GithubActionSample 的 Part3 签到薅羊毛](https://github.com/tech-shrimp/GithubActionSample#part3-签到薅羊毛)，原作者：**技术爬爬虾**。保留上游请求接口与 User-Agent；许可证见 [MIT 原文](licenses/GithubActionSample-MIT.txt)。

- 在 **Settings → Secrets and variables → Actions** 新增或更新 Secret `JD_COOKIE`，值为京东登录后的完整 Cookie。
- 工作流 **京东签到薅羊毛** 每天北京时间 **08:00** 执行，也可在 Actions 中手动选择 **Run workflow**。
- 脚本：`scripts/jd_sign.py`；工作流：`.github/workflows/daily_sign.yml`。使用 Python 标准库，无第三方依赖。
- 只向京东接口发送 Cookie；日志和运行摘要仅输出固定的结果说明，不打印 Cookie、账号信息或原始响应。
- 网络错误、登录失效和未识别结果会令工作流失败，避免把“程序运行结束”误当作“签到成功”。Cookie 失效后需要重新获取并更新 Secret。上游接口发生变化时也可能需要调整脚本。
- 离线验证：`python3 -m unittest discover -s tests -p 'test_jd_sign.py' -v`。

## 库街区运行方式

- 每天北京时间 **08:17、20:17** 自动执行，支持手动触发。
- 自动查询绑定角色；今日已签到则跳过，提交签到后再次查询确认。
- 支持最多 9 个账号，单个账号或角色失败不影响后续账号处理。
- 请求有超时限制，查询请求有限重试；失败会使工作流报错。
- 日志只显示账号与角色序号，不输出凭据、昵称或角色 ID。

## 配置

在仓库 **Settings → Secrets and variables → Actions** 设置：

| 类型 | 名称 | 内容 |
| --- | --- | --- |
| Secret | `KUROBBS_COOKIE` | 单账号 Token，或包含 `token` 的完整 Cookie |
| Secret | `KUROBBS_DEVCODE` | 对应登录请求的 Did / devcode（可选） |
| Variable | `KUROBBS_SOURCE` | 网页来源用 `h5`（默认）；App 来源用 `android` |
| Secret | `KUROBBS_ACCOUNTS` | 多账号 JSON 数组；使用时不要同时配置 `KUROBBS_COOKIE` |

选择 **Actions → 库街区自动签到 → Run workflow**，不勾选 `verify_only`，即可执行真实签到。勾选该选项只运行离线测试。

Token 必须匹配来源；来源不匹配也可能返回“登录已过期”。Token 真正失效时需要重新登录对应客户端并更新 Secret。

详细步骤见 [配置教程与实现说明](docs/自动签到.md)。

## 本地验证

需要 Python 3.10+ 和系统时区数据，不依赖第三方 Python 包。Actions 使用 Python 3.12。

```bash
python3 -m unittest discover -s tests -p 'test_kurobbs_sign.py' -v
```

本地签到可通过环境变量设置上表中的配置，再运行 `python3 scripts/kurobbs_sign.py`。不要将真实凭据写入代码或提交到仓库。
