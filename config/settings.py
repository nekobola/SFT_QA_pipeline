"""配置解析与验证"""
from pathlib import Path
from typing import Any
import yaml


class Config:
    """配置对象，支持属性访问"""

    def __init__(self, data: dict):
        self._data = data

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            return super().__getattribute__(name)
        value = self._data.get(name)
        if isinstance(value, dict):
            return Config(value)
        return value

    def get(self, name: str, default: Any = None) -> Any:
        return self._data.get(name, default)

    def to_dict(self) -> dict:
        return self._data.copy()


_config: Config | None = None


def load_config(config_path: str | Path) -> Config:
    """加载配置文件"""
    global _config

    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    _config = Config(data)
    return _config


def get_config() -> Config:
    """获取已加载的配置"""
    if _config is None:
        raise RuntimeError("配置未加载，请先调用 load_config()")
    return _config
