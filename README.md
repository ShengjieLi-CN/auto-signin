# 自动签到

使用 GitHub Actions 托管**库街区国服鸣潮**和**塔吉多**日常签到任务，无需常驻电脑。

库街区支持网页与 App Token、多个账号及绑定角色。接口调用方式参考 [leck995/WutheringWavesTool](https://github.com/leck995/WutheringWavesTool) 中的签到及角色查询实现。

## 塔吉多运行方式

- 每天北京时间 **02:00** 签到，支持在 Actions 手动运行或离线验证。
- 初次配置需要添加手机号、密码和用于更新账号 Secret 的仓库专用令牌，详见[塔吉多配置说明](docs/塔吉多签到.md)。

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
