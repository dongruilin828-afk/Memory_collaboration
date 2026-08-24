"""GUI 本地路径设置；仅在当前 Windows 用户注册表中保存目录字符串。"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

from scripts.project_paths import PROJECT_ROOT


REGISTRY_PATH = r"Software\AI Memory Summary"
RUNTIME_DATA_VALUE = "RuntimeDataDirectory"
DEFAULT_RESULTS_VALUE = "DefaultResultsDirectory"


class SettingsStoreError(RuntimeError):
    """不暴露底层环境细节、可安全展示给用户的设置错误。"""


@dataclass(frozen=True)
class AppSettings:
    runtime_data_dir: Path
    default_results_dir: Optional[Path] = None

    @property
    def browser_profile_dir(self) -> Path:
        return Path(self.runtime_data_dir) / ".browser_user_data"

    @property
    def log_dir(self) -> Path:
        return Path(self.runtime_data_dir) / "log"

    @property
    def summary_cache_dir(self) -> Path:
        return Path(self.runtime_data_dir) / "summary_results"

    @property
    def debug_html_file(self) -> Path:
        return Path(self.runtime_data_dir) / "debug_last_fetch.html"


def default_app_settings() -> AppSettings:
    return AppSettings(runtime_data_dir=Path(PROJECT_ROOT).resolve())


def normalize_directory(value: object) -> Optional[Path]:
    """把非空绝对目录规范化；拒绝相对路径以避免随启动目录漂移。"""
    raw = str(value or "").strip()
    if not raw:
        return None
    candidate = Path(os.path.expandvars(raw)).expanduser()
    if not candidate.is_absolute():
        return None
    return candidate.resolve(strict=False)


def ensure_writable_directory(path: Path) -> Path:
    """创建目录并做一次无内容探针写入，确认后续运行可以落盘。"""
    directory = Path(path).resolve(strict=False)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / f".ai-memory-write-test-{uuid.uuid4().hex}.tmp"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError:
        raise SettingsStoreError(
            "所选目录不可写，请选择当前用户有权限访问的文件夹。"
        ) from None
    return directory


class WindowsAppSettingsStore:
    """读写非敏感目录设置；API KEY 仍由 Windows 凭据管理器负责。"""

    def _read_values(self) -> dict[str, str]:
        if os.name != "nt":
            return {}
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                REGISTRY_PATH,
                0,
                winreg.KEY_READ,
            ) as key:
                values = {}
                for name in (RUNTIME_DATA_VALUE, DEFAULT_RESULTS_VALUE):
                    try:
                        value, _kind = winreg.QueryValueEx(key, name)
                    except FileNotFoundError:
                        continue
                    values[name] = str(value)
                return values
        except FileNotFoundError:
            return {}
        except OSError:
            raise SettingsStoreError("无法读取当前用户的数据位置设置。") from None

    def _write_values(self, values: Mapping[str, str]) -> None:
        if os.name != "nt":
            raise SettingsStoreError("数据位置持久化仅支持 Windows。")
        try:
            import winreg

            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                REGISTRY_PATH,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(
                    key,
                    RUNTIME_DATA_VALUE,
                    0,
                    winreg.REG_SZ,
                    values[RUNTIME_DATA_VALUE],
                )
                results_value = values.get(DEFAULT_RESULTS_VALUE, "")
                if results_value:
                    winreg.SetValueEx(
                        key,
                        DEFAULT_RESULTS_VALUE,
                        0,
                        winreg.REG_SZ,
                        results_value,
                    )
                else:
                    try:
                        winreg.DeleteValue(key, DEFAULT_RESULTS_VALUE)
                    except FileNotFoundError:
                        pass
        except SettingsStoreError:
            raise
        except OSError:
            raise SettingsStoreError("无法保存当前用户的数据位置设置。") from None

    def load(self) -> AppSettings:
        defaults = default_app_settings()
        values = self._read_values()
        runtime_dir = (
            normalize_directory(values.get(RUNTIME_DATA_VALUE))
            or defaults.runtime_data_dir
        )
        results_dir = normalize_directory(values.get(DEFAULT_RESULTS_VALUE))
        return AppSettings(runtime_dir, results_dir)

    def save(self, settings: AppSettings) -> AppSettings:
        runtime_dir = normalize_directory(settings.runtime_data_dir)
        if runtime_dir is None:
            raise SettingsStoreError("运行数据保存位置必须是绝对路径。")
        runtime_dir = ensure_writable_directory(runtime_dir)

        results_dir = normalize_directory(settings.default_results_dir)
        if settings.default_results_dir is not None and results_dir is None:
            raise SettingsStoreError("结果默认保存位置必须是绝对路径。")
        if results_dir is not None:
            results_dir = ensure_writable_directory(results_dir)

        normalized = AppSettings(runtime_dir, results_dir)
        self._write_values({
            RUNTIME_DATA_VALUE: str(runtime_dir),
            DEFAULT_RESULTS_VALUE: str(results_dir or ""),
        })
        return normalized
