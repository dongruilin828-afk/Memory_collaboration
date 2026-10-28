"""Persistent built-in deletion uses fake vault records only."""

import json
import unittest
from unittest.mock import patch

from gui.credential_store import (
    ACCOUNT_NAMES, DELETED_BUILTIN_APIS_ACCOUNT, PROVIDER_ORDER_ACCOUNT, SERVICE_NAME,
    CredentialStoreError, WindowsCredentialStore,
)
from tests.test_gui_api_keys import FakeCredentialBackend


class DeleteBuiltinAPIStoreTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeCredentialBackend()
        self.store = WindowsCredentialStore(self.backend)
        self.custom = "custom_" + "a" * 32
        self.store.save_api_keys({provider: provider + "-placeholder" for provider in ACCOUNT_NAMES})
        self.store.save_custom_api(dict(name="保留接口", url="https://example.test/v1", model="unknown"),
                                   "custom-placeholder", self.custom)
        self.store.save_provider_order([self.custom, "deepseek", "gemini", "siliconflow"])

    def test_old_installation_keeps_defaults_without_a_deletion_marker(self):
        self.assertEqual(self.store.load_deleted_builtin_apis(), ())
        self.assertTrue(set(ACCOUNT_NAMES).issubset(self.store.load_provider_order()))
        self.assertTrue(set(ACCOUNT_NAMES).issubset(self.store.load_api_keys()))

    def test_each_builtin_deletion_persists_and_preserves_custom_profiles(self):
        custom_before = self.store.load_custom_apis()
        deleted = set()
        for provider in ("deepseek", "gemini", "siliconflow"):
            with self.subTest(provider=provider):
                self.store.delete_builtin_api(provider)
                deleted.add(provider)
                reopened = WindowsCredentialStore(self.backend)
                self.assertEqual(reopened.load_deleted_builtin_apis(),
                                 tuple(item for item in ACCOUNT_NAMES if item in deleted))
                self.assertNotIn((SERVICE_NAME, ACCOUNT_NAMES[provider]), self.backend.passwords)
                self.assertTrue(deleted.isdisjoint(reopened.load_api_keys()))
                self.assertTrue(deleted.isdisjoint(reopened.load_provider_order()))
                raw_order = self.backend.passwords[(SERVICE_NAME, PROVIDER_ORDER_ACCOUNT)].split(",")
                self.assertNotIn(provider, raw_order)
                self.assertEqual(reopened.load_custom_apis(), custom_before)
                self.assertEqual(reopened.load_api_keys()[self.custom], "custom-placeholder")

    def test_keyless_and_repeated_deletion_are_supported(self):
        self.backend.delete_password(SERVICE_NAME, ACCOUNT_NAMES["gemini"])
        self.store.delete_builtin_api("gemini")
        first = dict(self.backend.passwords)
        self.store.delete_builtin_api("gemini")
        self.assertEqual(self.backend.passwords, first)
        self.assertEqual(self.store.load_deleted_builtin_apis(), ("gemini",))

    def test_stale_save_cannot_resurrect_a_deleted_builtin(self):
        self.store.delete_builtin_api("gemini")
        # Even an old form containing the removed key cannot enable it again.
        self.store.save_api_keys({"gemini": "stale-placeholder", "deepseek": "retained-placeholder"})
        self.store.save_provider_order(["gemini", "deepseek", self.custom, "siliconflow"])
        self.assertNotIn((SERVICE_NAME, ACCOUNT_NAMES["gemini"]), self.backend.passwords)
        self.assertNotIn("gemini", self.store.load_api_keys())
        self.assertNotIn("gemini", self.store.load_provider_order())
        self.assertEqual(self.store.load_api_keys()["deepseek"], "retained-placeholder")

    def test_restore_appends_without_restoring_secret_and_is_idempotent(self):
        self.store.delete_builtin_api("gemini")
        before = tuple(self.store.load_provider_order())
        self.store.restore_builtin_api("gemini")
        self.assertEqual(self.store.load_deleted_builtin_apis(), ())
        self.assertEqual(self.store.load_provider_order(), (*before, "gemini"))
        self.assertNotIn("gemini", self.store.load_api_keys())
        self.assertNotIn((SERVICE_NAME, DELETED_BUILTIN_APIS_ACCOUNT), self.backend.passwords)
        self.store.save_api_keys({"gemini": "new-placeholder", "deepseek": "kept-placeholder"})
        before_records = dict(self.backend.passwords)
        self.store.restore_builtin_api("gemini")
        self.assertEqual(self.backend.passwords, before_records)
        self.assertEqual(self.store.load_api_keys()["gemini"], "new-placeholder")

    def test_restore_one_keeps_other_deleted_providers_hidden(self):
        for provider in ACCOUNT_NAMES:
            self.store.delete_builtin_api(provider)
        self.store.restore_builtin_api("siliconflow")
        self.assertEqual(self.store.load_deleted_builtin_apis(), ("gemini", "deepseek"))
        self.assertNotIn("gemini", self.store.load_provider_order())
        self.assertNotIn("deepseek", self.store.load_provider_order())
        self.assertEqual(self.store.load_provider_order()[-1], "siliconflow")
        self.assertEqual(self.store.load_api_keys(), {self.custom: "custom-placeholder"})

    def test_invalid_ids_are_rejected_without_mutation(self):
        before = dict(self.backend.passwords)
        for provider in ("custom", self.custom, "unknown", "", None, [], 1):
            for action in (self.store.delete_builtin_api, self.store.restore_builtin_api):
                with self.subTest(provider=provider, action=action.__name__), self.assertRaises(ValueError):
                    action(provider)
        self.assertEqual(self.backend.passwords, before)

    def test_corrupt_marker_stops_loads_and_mutations_without_exposing_data(self):
        for raw in ("", "{bad json", "{}", '["unknown"]', '[null]', '["gemini", 1]'):
            self.backend.set_password(SERVICE_NAME, DELETED_BUILTIN_APIS_ACCOUNT, raw)
            before = dict(self.backend.passwords)
            actions = (
                self.store.load_deleted_builtin_apis, self.store.load_api_keys, self.store.load_provider_order,
                lambda: self.store.save_api_keys({"gemini": "new-placeholder"}),
                lambda: self.store.save_provider_order(["gemini"]),
                lambda: self.store.delete_builtin_api("gemini"),
                lambda: self.store.restore_builtin_api("gemini"),
            )
            for action in actions:
                with self.subTest(raw=raw, action=action), self.assertRaises(CredentialStoreError) as raised:
                    action()
                self.assertNotIn("placeholder", str(raised.exception))
                self.assertEqual(self.backend.passwords, before)

    def test_metadata_failure_rolls_back_before_deleting_key(self):
        original = self.backend.set_password
        before = dict(self.backend.passwords)

        def fail_new_order(service, account, value):
            if account == PROVIDER_ORDER_ACCOUNT and value != before[(service, account)]:
                raise RuntimeError("gemini-placeholder must not leak")
            original(service, account, value)

        with patch.object(self.backend, "set_password", side_effect=fail_new_order):
            with self.assertRaises(CredentialStoreError) as raised:
                self.store.delete_builtin_api("gemini")
        self.assertNotIn("gemini-placeholder", str(raised.exception))
        self.assertEqual(self.backend.passwords, before)

    def test_key_delete_then_failure_rolls_back_marker_order_and_secret(self):
        original = self.backend.delete_password
        before = dict(self.backend.passwords)

        def delete_then_fail(service, account):
            original(service, account)
            if account == ACCOUNT_NAMES["gemini"]:
                raise RuntimeError("gemini-placeholder must not leak")

        with patch.object(self.backend, "delete_password", side_effect=delete_then_fail):
            with self.assertRaises(CredentialStoreError) as raised:
                self.store.delete_builtin_api("gemini")
        self.assertNotIn("gemini-placeholder", str(raised.exception))
        self.assertEqual(self.backend.passwords, before)

    def test_failed_restore_keeps_row_deleted_and_rolls_back_stale_key_cleanup(self):
        self.store.delete_builtin_api("gemini")
        self.backend.set_password(SERVICE_NAME, ACCOUNT_NAMES["gemini"], "stale-placeholder")
        before = dict(self.backend.passwords)
        original = self.backend.delete_password

        def fail_marker_removal(service, account):
            original(service, account)
            if account == DELETED_BUILTIN_APIS_ACCOUNT:
                raise RuntimeError("stale-placeholder must not leak")

        with patch.object(self.backend, "delete_password", side_effect=fail_marker_removal):
            with self.assertRaises(CredentialStoreError) as raised:
                self.store.restore_builtin_api("gemini")
        self.assertNotIn("stale-placeholder", str(raised.exception))
        self.assertEqual(self.backend.passwords, before)
        self.assertEqual(self.store.load_deleted_builtin_apis(), ("gemini",))

    def test_successful_restore_clears_any_stale_secret_before_visibility(self):
        self.store.delete_builtin_api("gemini")
        self.backend.set_password(SERVICE_NAME, ACCOUNT_NAMES["gemini"], "stale-placeholder")
        self.store.restore_builtin_api("gemini")
        self.assertNotIn("gemini", self.store.load_api_keys())
        self.assertIn("gemini", self.store.load_provider_order())

    def test_marker_loader_has_stable_order_and_never_reads_keys(self):
        self.backend.set_password(SERVICE_NAME, DELETED_BUILTIN_APIS_ACCOUNT,
                                  json.dumps(["deepseek", "gemini", "deepseek"]))
        with patch.object(self.backend, "get_password", wraps=self.backend.get_password) as read:
            self.assertEqual(self.store.load_deleted_builtin_apis(), ("gemini", "deepseek"))
        read.assert_called_once_with(SERVICE_NAME, DELETED_BUILTIN_APIS_ACCOUNT)


if __name__ == "__main__":
    unittest.main()
