"""Windows API 密钥凭据存储。

API 密钥只写入当前 Windows 用户的凭据管理器。模块不使用明文配置文件，
也不会把底层异常（其中可能包含敏感信息）直接展示或写入日志。
"""

from __future__ import annotations

import os
import json
import re
from typing import Any, Iterable, Mapping


SERVICE_NAME = "AI Memory Summary"
ACCOUNT_NAMES = {
    "gemini": "gemini-api-key",
    "siliconflow": "siliconflow-api-key",
    "deepseek": "deepseek-api-key",
}
PROVIDER_ORDER_ACCOUNT = "api-provider-order"
CUSTOM_API_ACCOUNT = "custom-summary-api"
CUSTOM_API_INDEX = "custom-summary-api-index"
DELETED_BUILTIN_APIS_ACCOUNT = "deleted-builtin-apis"
PROVIDERS = (*ACCOUNT_NAMES, "custom")


def is_custom_provider(provider: str) -> bool:
    return provider == "custom" or bool(re.fullmatch(r"custom_[0-9a-f]{32}", provider))


def normalize_provider_order(order: Iterable[str]) -> tuple[str, ...]:
    """保留有效且不重复的顺序，并补齐尚未出现的提供商。"""
    normalized: list[str] = []
    for provider in order:
        if (provider in PROVIDERS or is_custom_provider(provider)) and provider not in normalized:
            normalized.append(provider)
    normalized.extend(
        provider for provider in PROVIDERS if provider not in normalized
    )
    return tuple(normalized)


class CredentialStoreError(RuntimeError):
    """不包含底层敏感细节、可安全展示给用户的凭据错误。"""


class WindowsCredentialStore:
    """通过 keyring 的 Windows 后端读写当前用户的 API 密钥。"""

    def __init__(self, backend: Any = None):
        self._backend = backend

    def _get_backend(self) -> Any:
        if self._backend is not None:
            return self._backend
        if os.name != "nt":
            raise CredentialStoreError("API KEY 安全存储仅支持 Windows。")
        try:
            from keyring.backends.Windows import WinVaultKeyring
        except ImportError:
            raise CredentialStoreError(
                "缺少 Windows 安全凭据组件，请重新安装或修复程序。"
            ) from None
        self._backend = WinVaultKeyring()
        return self._backend

    def load_api_keys(self) -> dict[str, str]:
        """读取已配置密钥；返回值只应在当前操作作用域内使用。"""
        try:
            backend = self._get_backend()
            deleted = set(self.load_deleted_builtin_apis())
            keys = {
                provider: str(
                    backend.get_password(SERVICE_NAME, account) or ""
                ).strip()
                for provider, account in ACCOUNT_NAMES.items() if provider not in deleted
            }
            for provider in self.load_custom_apis():
                keys[provider] = self._load_custom_record(provider)["api_key"].strip()
            order = normalize_provider_order(
                str(
                    backend.get_password(
                        SERVICE_NAME, PROVIDER_ORDER_ACCOUNT
                    ) or ""
                ).split(",") + list(keys)
            )
        except CredentialStoreError:
            raise
        except Exception:
            raise CredentialStoreError(
                "无法读取 Windows 凭据管理器中的 API KEY。"
            ) from None
        return {
            provider: keys[provider]
            for provider in order
            if keys.get(provider)
        }

    @staticmethod
    def _deleted_builtin_ids(raw) -> tuple[str, ...]:
        values = json.loads(raw) if raw is not None else []
        if (not isinstance(values, list)
                or any(not isinstance(value, str) or value not in ACCOUNT_NAMES for value in values)):
            raise ValueError("Invalid deleted API list")
        return tuple(provider for provider in ACCOUNT_NAMES if provider in values)

    def load_deleted_builtin_apis(self) -> tuple[str, ...]:
        """Return removed built-in providers without reading any API secret."""
        try:
            return self._deleted_builtin_ids(
                self._get_backend().get_password(SERVICE_NAME, DELETED_BUILTIN_APIS_ACCOUNT))
        except Exception:
            raise CredentialStoreError("无法读取内置 API 的删除状态，请重试。") from None

    def delete_builtin_api(self, provider: str) -> None:
        """Persist removal of a built-in row and erase its saved secret."""
        self._change_builtin_api(provider, restore=False)

    def restore_builtin_api(self, provider: str) -> None:
        """Restore an explicitly deleted built-in row without restoring a key."""
        self._change_builtin_api(provider, restore=True)

    def _change_builtin_api(self, provider: str, *, restore: bool) -> None:
        if not isinstance(provider, str) or provider not in ACCOUNT_NAMES:
            raise ValueError("无效的内置 API 标识。")
        changed = []
        try:
            backend = self._get_backend()
            raw_deleted = backend.get_password(SERVICE_NAME, DELETED_BUILTIN_APIS_ACCOUNT)
            deleted = set(self._deleted_builtin_ids(raw_deleted))
            if restore and provider not in deleted:
                return
            raw_order = backend.get_password(SERVICE_NAME, PROVIDER_ORDER_ACCOUNT)
            key_account = ACCOUNT_NAMES[provider]
            original_key = backend.get_password(SERVICE_NAME, key_account)
            next_deleted = deleted - {provider} if restore else deleted | {provider}
            next_marker = [item for item in ACCOUNT_NAMES if item in next_deleted]
            marker = json.dumps(next_marker) if next_marker else None
            if restore:
                order = normalize_provider_order([
                    *str(raw_order or "").split(","), *self.load_custom_apis(),
                ])
                next_order = ",".join([
                    *(item for item in order if item not in next_deleted and item != provider), provider,
                ])
            else:
                next_order = (
                    ",".join(item for item in str(raw_order).split(",") if item.strip() != provider) or None
                ) if raw_order is not None else None

            def write(account, original, value):
                if original == value:
                    return
                changed.append((account, original))
                if value is None:
                    backend.delete_password(SERVICE_NAME, account)
                else:
                    backend.set_password(SERVICE_NAME, account, value)

            # Restore clears any stale secret before making the row visible.
            # Delete erases the secret last, after its metadata writes succeed.
            if restore:
                write(key_account, original_key, None)
                write(PROVIDER_ORDER_ACCOUNT, raw_order, next_order)
                write(DELETED_BUILTIN_APIS_ACCOUNT, raw_deleted, marker)
            else:
                write(DELETED_BUILTIN_APIS_ACCOUNT, raw_deleted, marker)
                write(PROVIDER_ORDER_ACCOUNT, raw_order, next_order)
                write(key_account, original_key, None)
        except Exception:
            for account, original in reversed(changed):
                try:
                    if original is None:
                        if backend.get_password(SERVICE_NAME, account) is not None:
                            backend.delete_password(SERVICE_NAME, account)
                    else:
                        backend.set_password(SERVICE_NAME, account, original)
                except Exception:
                    pass
            action = "恢复" if restore else "删除"
            raise CredentialStoreError(f"无法{action}内置 API，请重试。") from None

    def _load_custom_record(self, profile_id="custom") -> dict:
        if not is_custom_provider(profile_id):
            raise ValueError("无效的自定义 API 标识。")
        account = CUSTOM_API_ACCOUNT if profile_id == "custom" else profile_id
        raw = self._get_backend().get_password(SERVICE_NAME, account)
        if not raw:
            return {}
        from scripts.api_config import normalize_custom_api
        data = json.loads(raw)
        return {**normalize_custom_api(data), "api_key": str(data.get("api_key") or "")}

    def load_custom_apis(self) -> dict:
        """Return all profile metadata, retaining the original single-profile record."""
        try:
            raw = self._get_backend().get_password(SERVICE_NAME, CUSTOM_API_INDEX)
            ids = json.loads(raw) if raw else []
            profiles = {}
            for profile_id in dict.fromkeys(["custom", *ids]):
                record = self._load_custom_record(profile_id)
                if record:
                    profiles[profile_id] = {k: v for k, v in record.items() if k != "api_key"}
            return profiles
        except Exception:
            raise CredentialStoreError("无法读取自定义 API 配置，请重试。") from None

    def load_custom_api(self) -> dict:
        """Read endpoint metadata without returning the stored secret."""
        try:
            return {k: v for k, v in self._load_custom_record().items() if k != "api_key"}
        except Exception:
            raise CredentialStoreError("无法读取自定义 API 配置，请重新配置。") from None

    def save_custom_api(self, values: Mapping, api_key: str, profile_id="custom") -> None:
        if not is_custom_provider(profile_id):
            raise ValueError("无效的自定义 API 标识。")
        from scripts.api_config import normalize_custom_api
        data = normalize_custom_api(values)
        data["api_key"] = str(api_key or "").strip()
        try:
            # Endpoint and secret change together, so a failed save cannot pair
            # a new secret with an old endpoint.
            backend = self._get_backend()
            raw = backend.get_password(SERVICE_NAME, CUSTOM_API_INDEX)
            ids = json.loads(raw) if raw else []
            backend.set_password(
                SERVICE_NAME, CUSTOM_API_ACCOUNT if profile_id == "custom" else profile_id,
                json.dumps(data, ensure_ascii=False),
            )
            if profile_id != "custom" and profile_id not in ids:
                backend.set_password(SERVICE_NAME, CUSTOM_API_INDEX, json.dumps([*ids, profile_id]))
        except Exception:
            raise CredentialStoreError("无法安全保存自定义 API 配置。") from None

    def delete_custom_api(self, profile_id="custom") -> None:
        """Remove a custom profile and its secret, preserving unrelated records."""
        if not isinstance(profile_id, str) or not is_custom_provider(profile_id):
            raise ValueError("无效的自定义 API 标识。")
        changed = []
        try:
            backend = self._get_backend()
            account = CUSTOM_API_ACCOUNT if profile_id == "custom" else profile_id
            record = backend.get_password(SERVICE_NAME, account)
            raw_index = backend.get_password(SERVICE_NAME, CUSTOM_API_INDEX)
            ids = json.loads(raw_index) if raw_index else []
            if (not isinstance(ids, list) or any(
                    not isinstance(item, str) or not is_custom_provider(item) for item in ids)):
                raise ValueError("Invalid custom API index")
            raw_order = backend.get_password(SERVICE_NAME, PROVIDER_ORDER_ACCOUNT)

            def write(account_name, old_value, new_value):
                # Remember even an attempted write: a backend can fail after
                # applying its mutation. The combined endpoint/key is deleted
                # last so an index/order failure cannot first lose the secret.
                changed.append((account_name, old_value))
                if new_value is None:
                    backend.delete_password(SERVICE_NAME, account_name)
                else:
                    backend.set_password(SERVICE_NAME, account_name, new_value)

            remaining = [item for item in ids if item != profile_id]
            if remaining != ids:
                write(CUSTOM_API_INDEX, raw_index, json.dumps(remaining))
            if raw_order is not None:
                parts = str(raw_order).split(",")
                remaining_order = [item for item in parts if item.strip() != profile_id]
                if remaining_order != parts:
                    write(PROVIDER_ORDER_ACCOUNT, raw_order, ",".join(remaining_order) or None)
            if record is not None:
                write(account, record, None)
        except Exception:
            for account_name, original in reversed(changed):
                try:
                    if original is None:
                        if backend.get_password(SERVICE_NAME, account_name) is not None:
                            backend.delete_password(SERVICE_NAME, account_name)
                    else:
                        backend.set_password(SERVICE_NAME, account_name, original)
                except Exception:
                    pass
            raise CredentialStoreError("无法删除自定义 API 配置和 KEY，请重试。") from None

    def load_provider_order(self) -> tuple[str, ...]:
        """读取用户设置的提供商兜底顺序。"""
        try:
            backend = self._get_backend()
            deleted = set(self.load_deleted_builtin_apis())
            raw_order = backend.get_password(
                SERVICE_NAME, PROVIDER_ORDER_ACCOUNT
            )
        except CredentialStoreError:
            raise
        except Exception:
            raise CredentialStoreError(
                "无法读取 Windows 凭据管理器中的 API 兜底顺序。"
            ) from None
        return tuple(provider for provider in normalize_provider_order([
            *normalize_provider_order(str(raw_order or "").split(",")),
            *self.load_custom_apis(),
        ]) if provider not in deleted)

    def save_api_keys(self, api_keys: Mapping[str, str]) -> None:
        """保存非空密钥并删除被清空的密钥，不创建任何明文文件。"""
        normalized = {
            provider: str(api_keys.get(provider) or "").strip()
            for provider in ACCOUNT_NAMES
        }
        try:
            backend = self._get_backend()
            deleted = set(self.load_deleted_builtin_apis())
            for profile_id in api_keys:
                if not is_custom_provider(profile_id):
                    continue
                custom = self._load_custom_record(profile_id)
                if custom:
                    self.save_custom_api(custom, api_keys.get(profile_id) or "", profile_id)
                elif str(api_keys.get(profile_id) or "").strip():
                    raise CredentialStoreError("请先编辑自定义 API 的地址和模型，再保存 KEY。")
            for provider, account in ACCOUNT_NAMES.items():
                secret = "" if provider in deleted else normalized[provider]
                existing = backend.get_password(SERVICE_NAME, account)
                if secret:
                    backend.set_password(SERVICE_NAME, account, secret)
                elif existing:
                    backend.delete_password(SERVICE_NAME, account)
        except CredentialStoreError:
            raise
        except Exception:
            raise CredentialStoreError(
                "无法将 API KEY 保存到 Windows 凭据管理器。"
            ) from None

    def save_provider_order(self, order: Iterable[str]) -> None:
        """保存提供商兜底顺序，不创建明文配置文件。"""
        try:
            deleted = set(self.load_deleted_builtin_apis())
            self._get_backend().set_password(
                SERVICE_NAME,
                PROVIDER_ORDER_ACCOUNT,
                ",".join(provider for provider in normalize_provider_order(order) if provider not in deleted),
            )
        except CredentialStoreError:
            raise
        except Exception:
            raise CredentialStoreError(
                "无法将 API 兜底顺序保存到 Windows 凭据管理器。"
            ) from None
