"""Offline regression tests: no credentials or live Kuro requests required."""

import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from scripts import kurobbs_sign as sign


ROLE = {"userId": 123, "roleId": "456"}


def state(flag):
    return {"code": 200, "data": {"isSigIn": flag}}


class CredentialsTest(unittest.TestCase):
    def test_bare_token_and_base64_padding(self):
        for token in ("example-token", "example=="):
            self.assertEqual(sign.parse_credential(token).token, token)

    def test_cookie_decoding_and_device(self):
        account = sign.parse_credential("Cookie: token=example%3D%3D; devcode=device-1; other=x")
        self.assertEqual(account.token, "example==")
        self.assertEqual(account.devcode, "device-1")
        self.assertEqual(sign.parse_credential("token=a; devcode=b", "override").devcode, "override")

    def test_missing_token_and_header_injection_rejected(self):
        for raw in ("", "session=abc", "session=abc; other=def", "token=x\r\nX-Evil: y", "token=x%0Ay"):
            with self.subTest(raw=raw), self.assertRaises(sign.SignError):
                sign.parse_credential(raw)

    def test_multiple_accounts(self):
        accounts = sign.load_accounts({"KUROBBS_ACCOUNTS": json.dumps([
            {"token": "example-a"}, {"cookie": "token=example-b; devcode=b"}
        ])})
        self.assertEqual([a.token for a in accounts], ["example-a", "example-b"])

    def test_invalid_configuration(self):
        invalid = [{}, {"KUROBBS_COOKIE": "a", "KUROBBS_ACCOUNTS": "[]"}]
        invalid.extend({"KUROBBS_ACCOUNTS": value} for value in (
            "[", "{}", "[]", '[{"token":"a","cookie":"token=b"}]',
            '[{"token":1}]', '[null]', json.dumps([{"token": "x"}] * 10),
        ))
        for env in invalid:
            with self.subTest(env=env), self.assertRaises(sign.SignError):
                sign.load_accounts(env)

    def test_account_repr_does_not_include_secret(self):
        self.assertNotIn("secret-token", repr(sign.Account("secret-token")))

    def test_source_configuration(self):
        self.assertEqual(sign.load_accounts({"KUROBBS_COOKIE": "example"})[0].source, "h5")
        account = sign.load_accounts({"KUROBBS_COOKIE": "example", "KUROBBS_SOURCE": "android"})[0]
        self.assertEqual(account.source, "android")
        accounts = sign.load_accounts({"KUROBBS_SOURCE": "android", "KUROBBS_ACCOUNTS": json.dumps([
            {"token": "first", "source": "android"}, {"token": "second"},
        ])})
        self.assertEqual([a.source for a in accounts], ["android", "h5"])
        for source in (None, "ios", "", 1, {}):
            with self.subTest(source=source), self.assertRaises(sign.SignError):
                sign.parse_credential("example", source=source)


class TransportTest(unittest.TestCase):
    def setUp(self):
        self.client = sign.KuroClient(sign.Account("example", "device"))
        self.client.opener = Mock()

    def response(self, payload):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = payload
        return response

    def test_request_matches_java_protocol(self):
        self.client.opener.open.return_value = self.response(b'{"code":200}')
        self.client.request(sign.ROLE_PATH, {"gameId": "3"})
        request = self.client.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.kurobbs.com/gamer/role/list?gameId=3")
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.data, b"")
        self.assertEqual(request.get_header("Source"), "h5")
        self.assertEqual(request.get_header("Token"), "example")
        self.assertEqual(request.get_header("Devcode"), "device")
        self.assertEqual(self.client.opener.open.call_args.kwargs["timeout"], 20)

    @patch.object(sign.time, "sleep")
    def test_bounded_retry_for_read(self, sleep):
        self.client.opener.open.side_effect = [URLError("private context"), self.response(b'{"code":200}')]
        self.assertEqual(self.client.request(sign.INIT_PATH, {})["code"], 200)
        self.assertEqual(self.client.opener.open.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_android_source_sent_on_all_endpoints(self):
        self.client.account = sign.Account("example", "device", "android")
        self.client.opener.open.return_value = self.response(b'{"code":200}')
        for path in (sign.ROLE_PATH, sign.INIT_PATH, sign.SIGN_PATH):
            self.client.request(path, {})
            request = self.client.opener.open.call_args.args[0]
            self.assertEqual(request.get_header("Source"), "android")

    @patch.object(sign.time, "sleep")
    def test_timeout_exhaustion_is_sanitized(self, sleep):
        self.client.opener.open.side_effect = URLError("secret-token")
        with self.assertRaises(sign.SignError) as caught:
            self.client.request(sign.INIT_PATH, {})
        self.assertNotIn("secret-token", str(caught.exception))
        self.assertEqual(self.client.opener.open.call_count, 3)

    def test_mutation_not_retried(self):
        self.client.opener.open.side_effect = TimeoutError("private context")
        with self.assertRaises(sign.SignError):
            self.client.request(sign.SIGN_PATH, {}, retry=False)
        self.assertEqual(self.client.opener.open.call_count, 1)

    def test_http_auth_failure_is_not_retried(self):
        self.client.opener.open.side_effect = HTTPError("private-url", 403, "secret", {}, None)
        with self.assertRaises(sign.SignError):
            self.client.request(sign.ROLE_PATH, {})
        self.assertEqual(self.client.opener.open.call_count, 1)

    def test_bad_response_rejected(self):
        for payload in (b"<html>blocked</html>", b"[]", b"null", b'{"code":"200"}'):
            self.client.opener.open.return_value = self.response(payload)
            with self.subTest(payload=payload), self.assertRaises(sign.SignError):
                self.client.request(sign.INIT_PATH, {})

    def test_redirect_does_not_forward_token(self):
        self.assertIsNone(sign.NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com"))


class SignFlowTest(unittest.TestCase):
    def test_already_signed_skips_mutation(self):
        client = Mock()
        client.request.return_value = state(True)
        self.assertEqual(sign.sign_role(client, ROLE), "今日已签到")
        self.assertEqual(client.request.call_count, 1)

    def test_sign_uses_china_month_and_role_server(self):
        client = Mock()
        client.request.side_effect = [state(False), {"code": 200}, state(True)]
        now = datetime(2026, 12, 31, 16, 1, tzinfo=timezone.utc)
        self.assertEqual(sign.sign_role(client, {**ROLE, "serverId": "server-from-api"}, now), "签到成功")
        call = client.request.call_args_list[1]
        self.assertEqual(call.args[0], sign.SIGN_PATH)
        self.assertEqual(call.args[1]["reqMonth"], "01")
        self.assertEqual(call.args[1]["serverId"], "server-from-api")
        self.assertFalse(call.kwargs["retry"])

    def test_lost_response_or_duplicate_requires_server_confirmation(self):
        for result in (sign.SignError("网络超时"), {"code": 500, "msg": "请勿重复签到"}):
            client = Mock()
            client.request.side_effect = [state(False), result, state(True)]
            self.assertEqual(sign.sign_role(client, ROLE), "已确认今日签到完成")

    def test_false_success_rejected(self):
        for response in ({"code": 500, "msg": "请求成功"}, {"code": 200}):
            client = Mock()
            client.request.side_effect = [state(False), response, state(False)]
            with self.assertRaises(sign.SignError):
                sign.sign_role(client, ROLE)

    def test_expired_login(self):
        with self.assertRaisesRegex(sign.SignError, "登录已过期"):
            sign.require_success({"code": 220, "msg": "secret-token"})

    def test_state_types(self):
        for value in (True, 1, "true", "1"):
            self.assertTrue(sign.signed_today(state(value)))
        for value in (False, 0, "false", "0"):
            self.assertFalse(sign.signed_today(state(value)))
        for value in (None, "unknown", {}, 2):
            with self.assertRaises(sign.SignError):
                sign.signed_today(state(value))

    def test_bad_role_is_rejected(self):
        for role in (None, {}, {**ROLE, "userId": True}, {**ROLE, "roleId": ""}):
            with self.assertRaises(sign.SignError):
                sign.role_params(role)

    def test_one_failed_role_does_not_block_other_roles_or_accounts(self):
        first, second = Mock(), Mock()
        first.request.side_effect = [
            {"code": 200, "data": [ROLE, ROLE]},
            {"code": 500, "msg": "secret-token"}, state(True),
        ]
        second.request.side_effect = [{"code": 200, "data": [ROLE]}, state(True)]
        lines, failed = sign.run([sign.Account("a"), sign.Account("b")], Mock(side_effect=[first, second]))
        self.assertTrue(failed)
        self.assertEqual(len(lines), 3)
        self.assertIn("今日已签到", lines[-1])
        self.assertNotIn("secret-token", "\n".join(lines))

    def test_empty_roles_fail(self):
        client = Mock()
        client.request.return_value = {"code": 200, "data": []}
        lines, failed = sign.run([sign.Account("a")], Mock(return_value=client))
        self.assertTrue(failed)
        self.assertIn("未找到绑定角色", lines[0])

    def test_main_missing_credentials_and_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "summary.md"
            with patch.dict(sign.os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}, clear=True):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(sign.main(), 1)
            self.assertIn("缺少凭据", summary.read_text(encoding="utf-8"))

    def test_main_exit_codes_and_no_raw_exception(self):
        with patch.dict(sign.os.environ, {"KUROBBS_COOKIE": "example"}, clear=True):
            for result, expected in (((["成功"], False), 0), ((["失败"], True), 1)):
                with patch.object(sign, "run", return_value=result), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(sign.main(), expected)
            output = io.StringIO()
            with patch.object(sign, "run", side_effect=RuntimeError("secret-token")):
                with contextlib.redirect_stdout(output):
                    self.assertEqual(sign.main(), 1)
            self.assertNotIn("secret-token", output.getvalue())


if __name__ == "__main__":
    unittest.main()
