"""Delete custom API credentials without touching real Windows credentials."""

import json
import unittest
from unittest.mock import patch

from gui.credential_store import (
    CUSTOM_API_ACCOUNT, CUSTOM_API_INDEX, PROVIDER_ORDER_ACCOUNT, SERVICE_NAME,
    CredentialStoreError, WindowsCredentialStore,
)
from tests.test_gui_api_keys import FakeCredentialBackend


class DeleteCustomAPIStoreTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeCredentialBackend()
        self.store = WindowsCredentialStore(self.backend)
        self.first = "custom_" + "a" * 32
        self.second = "custom_" + "b" * 32
        self.values = dict(name="自定义接口", url="https://example.test/v1", model="my-model")
        self.store.save_api_keys({"gemini": "builtin-placeholder"})
        self.store.save_custom_api(self.values, "legacy-placeholder", "custom")
        self.store.save_custom_api(self.values, "first-placeholder", self.first)
        self.store.save_custom_api(self.values, "second-placeholder", self.second)
        self.store.save_provider_order([self.second, "gemini", self.first, "custom", "deepseek", "siliconflow"])

    def test_delete_profile_removes_endpoint_key_index_and_raw_order_entry(self):
        self.store.delete_custom_api(self.first)
        self.assertNotIn((SERVICE_NAME, self.first), self.backend.passwords)
        self.assertEqual(json.loads(self.backend.passwords[(SERVICE_NAME, CUSTOM_API_INDEX)]), [self.second])
        self.assertEqual(self.backend.passwords[(SERVICE_NAME, PROVIDER_ORDER_ACCOUNT)].split(","),
                         [self.second, "gemini", "custom", "deepseek", "siliconflow"])
        self.assertEqual(list(self.store.load_custom_apis()), ["custom", self.second])
        self.assertEqual(self.store.load_api_keys(), {
            self.second: "second-placeholder", "gemini": "builtin-placeholder", "custom": "legacy-placeholder",
        })

    def test_delete_legacy_profile_does_not_reappear_on_reload(self):
        self.store.delete_custom_api()
        reopened = WindowsCredentialStore(self.backend)
        self.assertEqual(reopened.load_custom_api(), {})
        self.assertNotIn("custom", reopened.load_custom_apis())
        self.assertNotIn("custom", reopened.load_api_keys())
        self.assertNotIn((SERVICE_NAME, CUSTOM_API_ACCOUNT), self.backend.passwords)
        self.assertNotIn("custom", self.backend.passwords[(SERVICE_NAME, PROVIDER_ORDER_ACCOUNT)].split(","))
        self.assertEqual(set(reopened.load_custom_apis()), {self.first, self.second})

    def test_missing_profile_is_idempotent_and_stale_metadata_is_cleaned(self):
        missing = "custom_" + "c" * 32
        before = dict(self.backend.passwords)
        self.store.delete_custom_api(missing)
        self.store.delete_custom_api(missing)
        self.assertEqual(self.backend.passwords, before)
        self.backend.set_password(SERVICE_NAME, CUSTOM_API_INDEX, json.dumps([self.first, missing, self.second]))
        self.backend.set_password(SERVICE_NAME, PROVIDER_ORDER_ACCOUNT, f"{missing},{self.second},gemini,{self.first}")
        self.store.delete_custom_api(missing)
        self.assertEqual(json.loads(self.backend.passwords[(SERVICE_NAME, CUSTOM_API_INDEX)]), [self.first, self.second])
        self.assertEqual(self.backend.passwords[(SERVICE_NAME, PROVIDER_ORDER_ACCOUNT)], f"{self.second},gemini,{self.first}")

    def test_builtin_and_invalid_ids_are_rejected_without_mutation(self):
        before = dict(self.backend.passwords)
        for profile in ("gemini", "deepseek", "siliconflow", "custom_bad", "", None):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                self.store.delete_custom_api(profile)
        self.assertEqual(self.backend.passwords, before)

    def test_metadata_update_failure_rolls_back_and_keeps_secret(self):
        original = self.backend.set_password
        before = dict(self.backend.passwords)

        def fail_order_once(service, account, value):
            if account == PROVIDER_ORDER_ACCOUNT and value != before[(service, account)]:
                raise RuntimeError("first-placeholder must not be exposed")
            original(service, account, value)

        with patch.object(self.backend, "set_password", side_effect=fail_order_once):
            with self.assertRaises(CredentialStoreError) as raised:
                self.store.delete_custom_api(self.first)
        self.assertNotIn("first-placeholder", str(raised.exception))
        self.assertEqual(self.backend.passwords, before)

    def test_record_delete_failure_restores_metadata_even_after_delete_mutates(self):
        original = self.backend.delete_password
        before = dict(self.backend.passwords)

        def delete_then_fail(service, account):
            original(service, account)
            if account == self.first:
                raise RuntimeError("first-placeholder must not be exposed")

        with patch.object(self.backend, "delete_password", side_effect=delete_then_fail):
            with self.assertRaises(CredentialStoreError) as raised:
                self.store.delete_custom_api(self.first)
        self.assertNotIn("first-placeholder", str(raised.exception))
        self.assertEqual(self.backend.passwords, before)

    def test_corrupt_index_or_read_failure_does_not_delete_record(self):
        self.backend.set_password(SERVICE_NAME, CUSTOM_API_INDEX, '{"unexpected":"index"}')
        before = dict(self.backend.passwords)
        with self.assertRaises(CredentialStoreError):
            self.store.delete_custom_api(self.first)
        self.assertEqual(self.backend.passwords, before)
        with patch.object(self.backend, "get_password", side_effect=RuntimeError("first-placeholder")):
            with self.assertRaises(CredentialStoreError) as raised:
                self.store.delete_custom_api(self.first)
        self.assertNotIn("first-placeholder", str(raised.exception))
        self.assertEqual(self.backend.passwords, before)

    def test_delete_only_legacy_order_entry_clears_empty_order_record(self):
        self.backend.set_password(SERVICE_NAME, PROVIDER_ORDER_ACCOUNT, "custom")
        self.store.delete_custom_api()
        self.assertNotIn((SERVICE_NAME, PROVIDER_ORDER_ACCOUNT), self.backend.passwords)


if __name__ == "__main__":
    unittest.main()
