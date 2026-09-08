"""公开数据生成器的版本、规模配置和配置类型，隐藏内部数据库实现细节。"""

from datasets.generator.model import DATASET_VERSION, PROFILES, DatasetProfile

__all__ = ["DATASET_VERSION", "PROFILES", "DatasetProfile"]
