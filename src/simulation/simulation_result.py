"""シミュレーション結果データ構造

設計意図:
- 辞書の代わりにdataclassを使用して型安全性を確保
- IDEの補完機能を活用可能に
- データ構造を明示化してドキュメントとして機能
"""
from dataclasses import dataclass
from typing import Optional
import pandas as pd


@dataclass
class SimulationResult:
    """シミュレーション結果を表すデータクラス

    設計意図:
    - 全てのシミュレーション出力を1つのオブジェクトで管理
    - 型ヒントにより、誤った型の代入を防ぐ
    - 不変性を強制したい場合は frozen=True を追加可能

    Attributes:
        time_series_kw: 時系列充電容量データ（ElapsedTime × CSID）
        waiting_line: 時系列待ち行列データ（ElapsedTime × CSID）
        vehicle_trip: 車両トリップデータ
        charging_loss: 充電ロスデータ
        cs_config: 充電ステーション設定（辞書形式、将来的にCSConfigに置き換え可能）
    """
    time_series_kw: pd.DataFrame
    waiting_line: pd.DataFrame
    vehicle_trip: pd.DataFrame
    charging_loss: pd.DataFrame
    cs_config: dict  # 将来的に CSConfig に置き換え可能

    def __post_init__(self):
        """データバリデーション

        設計意図:
        - データロード直後に基本的な検証を行う
        - 実行時エラーの早期発見
        """
        # DataFrameであることを確認
        if not isinstance(self.time_series_kw, pd.DataFrame):
            raise TypeError("time_series_kw must be a DataFrame")
        if not isinstance(self.waiting_line, pd.DataFrame):
            raise TypeError("waiting_line must be a DataFrame")
        if not isinstance(self.vehicle_trip, pd.DataFrame):
            raise TypeError("vehicle_trip must be a DataFrame")
        if not isinstance(self.charging_loss, pd.DataFrame):
            raise TypeError("charging_loss must be a DataFrame")

        # cs_configの必須キーを確認
        required_keys = {'csids', 'ports', 'cap_kw'}
        if not all(key in self.cs_config for key in required_keys):
            raise ValueError(f"cs_config must contain keys: {required_keys}")

    @property
    def total_charging_kwh(self) -> float:
        """総充電量（kWh）を計算

        設計意図:
        - よく使う計算をプロパティとして提供
        - キャッシュが必要な場合は @functools.lru_cache を追加可能
        """
        return self.time_series_kw.sum().sum() / 60  # kW·s → kWh

    @property
    def num_active_cs(self) -> int:
        """稼働中のCS数を返す

        設計意図:
        - データから自動的に計算される情報をプロパティ化
        """
        return sum(1 for port in self.cs_config['ports'] if port > 0)

    def get_cs_summary(self) -> pd.DataFrame:
        """CS設定のサマリーをDataFrameで返す

        設計意図:
        - 可視化やレポート生成に便利な形式で提供
        """
        return pd.DataFrame({
            'csid': self.cs_config['csids'],
            'ports': self.cs_config['ports'],
            'capacity_kw': self.cs_config['cap_kw']
        })


@dataclass
class TimeSeriesData:
    """時系列データを表すデータクラス

    設計意図:
    - load_timeseries_dataの返り値を型安全に
    - タプルの代わりに名前付きフィールドで可読性向上
    """
    cap_kw: pd.DataFrame
    waiting_line: pd.DataFrame

    def __post_init__(self):
        """データバリデーション"""
        if self.cap_kw.shape != self.waiting_line.shape:
            raise ValueError("cap_kw and waiting_line must have the same shape")
