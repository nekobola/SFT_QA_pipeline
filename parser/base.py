"""解析器基类"""
from abc import ABC, abstractmethod
from pathlib import Path
from hashlib import md5


class BaseParser(ABC):
    """解析器基类"""

    @abstractmethod
    def parse(self, file_path: Path) -> list[dict]:
        """解析文件，返回条款列表"""
        pass

    @staticmethod
    def generate_uid(doc_title: str, article_no: str) -> str:
        """生成条款唯一标识"""
        base = f"{doc_title}_{article_no}"
        return md5(base.encode()).hexdigest()[:16]

    @staticmethod
    def extract_title_from_filename(filename: str) -> str:
        """从文件名中提取标题（《...》之间的内容）"""
        import re
        m = re.search(r"《(.+?)》", filename)
        return m.group(1) if m else Path(filename).stem
