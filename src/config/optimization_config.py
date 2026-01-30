"""最適化設定のデータクラス定義"""
from dataclasses import dataclass, field, asdict
from typing import List, Optional
import json
from pathlib import Path


@dataclass
class OptimizationConfig:
    """最適化実行の設定"""
    save_dir: str
    t_hour: int = 26
    batch_size: int = 8
    total_trials: int = 1000
    timeout: int = 86400  # 24時間
    convergence_patience: int = 100
    convergence_threshold: float = 0.01

    @classmethod
    def from_json(cls, path: Path) -> 'OptimizationConfig':
        """JSONファイルから設定を読み込み"""
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return cls(**data)

    def to_json(self, path: Path) -> None:
        """JSONファイルに設定を保存"""
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)


@dataclass
class FailureScenarioConfig:
    """故障シナリオの設定"""
    failure_flag: bool = True
    failure_time: List[int] = field(default_factory=lambda: list(range(27)))
    failure_probability: float = 0.2  # 全CSのうち一か所が故障する確率
    charger_failure_rate: float = 0.02  # 各充電器の故障率

    @classmethod
    def from_json(cls, path: Path) -> 'FailureScenarioConfig':
        """JSONファイルから設定を読み込み"""
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return cls(**data)

    def to_json(self, path: Path) -> None:
        """JSONファイルに設定を保存"""
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)


@dataclass
class CSConfig:
    """充電ステーション設定のデータクラス"""
    csids: List[int]
    ports: List[int]
    cap_kw: List[int]

    def __post_init__(self):
        """データ検証"""
        if not (len(self.csids) == len(self.ports) == len(self.cap_kw)):
            raise ValueError("csids, ports, cap_kwの長さが一致しません")
