"""Windows API 密钥凭据存储。

API 密钥只写入当前 Windows 用户的凭据管理器。模块不使用明文配置文件，
也不会把底层异常（其中可能包含敏感信息）直接展示或写入日志。
"""

from __future__ import annotations

import os
import json
from typing import Any, Iterable, Mapping


SERVICE_NAME = "AI Memory Summary"
ACCOUNT_NAMES = {
    "gemini": "gemini-api-key",
    "siliconflow": "siliconflow-api-key",
    "deepseek": "deepseek-api-key",
}
PROVIDER_ORDER_ACCOUNT = "api-provider-order"
CUSTOM_API_ACCOUNT = "custom-summary-api"
PROVIDERS = (*ACCOUNT_NAMES, "custom")


def normalize_provider_order(order: Iterable[str]) -> tuple[str, ...]:
    """保留有效且不重复的顺序，并补齐尚未出现的提供商。"""
    normalized: list[str] = []
    for provider in order:
        if provider in PROVIDERS and provider not in normalized:
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
            keys = {
                provider: str(
                    backend.get_password(SERVICE_NAME, account) or ""
                ).strip()
                for provider, account in ACCOUNT_NAMES.items()
            }
            custom = self._load_custom_record()
            if custom:
                keys["custom"] = str(custom.get("api_key") or "").strip()
            order = normalize_provider_order(
                str(
                    backend.get_password(
                        SERVICE_NAME, PROVIDER_ORDER_ACCOUNT
                    ) or ""
                ).split(",")
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

    def _load_custom_record(self) -> dict:
        raw = self._get_backend().get_password(SERVICE_NAME, CUSTOM_API_ACCOUNT)
        if not raw:
            return {}
        from scripts.api_config import normalize_custom_api
        data = json.loads(raw)
        return {**normalize_custom_api(data), "api_key": str(data.get("api_key") or "")}

    def load_custom_api(self) -> dict:
        """Read endpoint metadata without returning the stored secret."""
        try:
            return {k: v for k, v in self._load_custom_record().items() if k != "api_key"}
        except Exception:
            raise CredentialStoreError("无法读取自定义 API 配置，请重新配置。") from None

    def save_custom_api(self, values: Mapping, api_key: str) -> None:
        from scripts.api_config import normalize_custom_api
        data = normalize_custom_api(values)
        data["api_key"] = str(api_key or "").strip()
        try:
            # Endpoint and secret change together, so a failed save cannot pair
            # a new secret with an old endpoint.
            self._get_backend().set_password(
                SERVICE_NAME, CUSTOM_API_ACCOUNT,
                json.dumps(data, ensure_ascii=False),
            )
        except Exception:
            raise CredentialStoreError("无法安全保存自定义 API 配置。") from None

    def load_provider_order(self) -> tuple[str, ...]:
        """读取用户设置的提供商兜底顺序。"""
        try:
            backend = self._get_backend()
            raw_order = backend.get_password(
                SERVICE_NAME, PROVIDER_ORDER_ACCOUNT
            )
        except CredentialStoreError:
            raise
        except Exception:
            raise CredentialStoreError(
                "无法读取 Windows 凭据管理器中的 API 兜底顺序。"
            ) from None
        return normalize_provider_order(str(raw_order or "").split(","))

    def save_api_keys(self, api_keys: Mapping[str, str]) -> None:
        """保存非空密钥并删除被清空的密钥，不创建任何明文文件。"""
        normalized = {
            provider: str(api_keys.get(provider) or "").strip()
            for provider in ACCOUNT_NAMES
        }
        try:
            backend = self._get_backend()
            if "custom" in api_keys:
                custom = self._load_custom_record()
                if custom:
                    self.save_custom_api(custom, api_keys.get("custom") or "")
                elif str(api_keys.get("custom") or "").strip():
                    raise CredentialStoreError("请先编辑自定义 API 的地址和模型，再保存 KEY。")
            for provider, account in ACCOUNT_NAMES.items():
                secret = normalized[provider]
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
            self._get_backend().set_password(
                SERVICE_NAME,
                PROVIDER_ORDER_ACCOUNT,
                ",".join(normalize_provider_order(order)),
            )
        except CredentialStoreError:
            raise
        except Exception:
            raise CredentialStoreError(
                "无法将 API 兜底顺序保存到 Windows 凭据管理器。"
            ) from None
