import pytest
from pathlib import Path
import tempfile
import yaml
from config import load_config, get_config, Config


def test_load_config():
    """测试配置加载"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump({"data": {"output_dir": "test_output"}}, f)
        f.flush()

        config = load_config(f.name)
        assert config.data.output_dir == "test_output"


def test_config_attribute_access():
    """测试配置属性访问"""
    config = Config({"level1": {"level2": "value"}})
    assert config.level1.level2 == "value"


def test_config_get_with_default():
    """测试配置默认值"""
    config = Config({"key": "value"})
    assert config.get("missing", "default") == "default"


def test_get_config_before_load():
    """测试未加载时获取配置抛出异常"""
    # 重置全局配置
    import config.settings as settings
    settings._config = None

    with pytest.raises(RuntimeError, match="配置未加载"):
        get_config()
