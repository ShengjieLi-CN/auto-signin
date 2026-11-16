import unittest

from scripts.jd_sign import classify, parse_response


class ResponseTests(unittest.TestCase):
    def test_json_and_jsonp(self):
        expected = {"code": "0", "data": {"status": "1"}}
        for body in ('{"code":"0","data":{"status":"1"}}',
                     'jsonp_1645885800574_58482({"code":"0","data":{"status":"1"}});'):
            self.assertEqual(parse_response(body), expected)
            self.assertTrue(classify(parse_response(body))[0])

    def test_already_signed(self):
        self.assertTrue(classify({"code": 0, "data": {"status": 2}})[0])

    def test_login_failure_overrides_status(self):
        self.assertFalse(classify({"code": "3", "data": {"status": "1"}})[0])

    def test_business_error_with_success_transport_code(self):
        success, message = classify({"code": "0", "errorCode": "S109"})
        self.assertFalse(success)
        self.assertIn("S109", message)
        self.assertFalse(classify({"code": "0", "errorCode": "unknown",
                                   "data": {"status": "1"}})[0])

    def test_unknown_results_fail_without_echoing_private_values(self):
        for result in ({}, {"code": 0}, {"code": 0, "data": []},
                       {"code": 0, "data": {"status": "unknown"}},
                       {"code": "private-value", "message": "private-value"}):
            success, message = classify(result)
            self.assertFalse(success)
            self.assertNotIn("private-value", message)

    def test_malformed_results(self):
        for body in ('<html>login</html>', '[]', 'jsonp_bad(broken);'):
            with self.assertRaises(ValueError):
                parse_response(body)


if __name__ == '__main__':
    unittest.main()
