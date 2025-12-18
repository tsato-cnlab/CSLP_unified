"""結果可視化クラス

設計意図:
- 関数ベースではなくクラスベースで可視化機能を提供
- SimulationResultを受け取り、各種グラフを生成
- matplotlibの設定を一箇所で管理
- メソッドチェーンで複数のグラフを連続生成可能
"""
import pickle
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from typing import Optional, Tuple
import japanize_matplotlib
import warnings
warnings.filterwarnings('ignore')

from src.simulation.simulation_result import SimulationResult
from src.util.cost_calculator import calc_initial_costs, calc_running_costs, calc_diff_trnsprt_costs


class ResultVisualizer:
    """シミュレーション結果の可視化を担当するクラス

    設計意図:
    - 状態（SimulationResult）を保持し、複数の可視化メソッドを提供
    - matplotlib設定を一元管理
    - 再利用可能な可視化ロジック

    使用例:
        >>> result = load_worker_data(worker_id=1)
        >>> viz = ResultVisualizer(result)
        >>> viz.plot_waiting_times()
        >>> viz.plot_kwh_timeseries()
    """

    def __init__(self, result: SimulationResult):
        """
        Args:
            result: 可視化対象のシミュレーション結果
        """
        self.result = result
        # matplotlib日本語フォント設定（既にjapanize_matplotlibで設定済み）

    def plot_waiting_times(
        self,
        title: str = "待ち時間分布",
        xlim_range: Tuple[float, float] = (0, 60),
        ylim_range: Optional[Tuple[float, float]] = None,
        bins: int = 20
    ) -> None:
        """待ち時間のヒストグラムをプロット

        設計意図:
        - 95パーセンタイルを強調表示（外れ値の影響を可視化）
        - カスタマイズ可能な軸範囲
        """
        waiting_times_minute = self._get_waiting_times_minutes()

        plt.figure(figsize=(10, 6))
        plt.hist(waiting_times_minute, bins=bins, range=xlim_range,
                 color='skyblue', edgecolor='black', alpha=0.7)

        # 95パーセンタイル表示
        p95 = np.percentile(waiting_times_minute, 95)
        plt.axvline(p95, color='red', linestyle='dashed', linewidth=2,
                   label=f'95%tile: {p95:.1f}分')

        plt.title(title, fontsize=14)
        plt.xlabel('待ち時間 (分)', fontsize=12)
        plt.ylabel('台数', fontsize=12)
        plt.xlim(xlim_range)
        if ylim_range:
            plt.ylim(ylim_range)
        plt.grid(axis='y', alpha=0.3)
        plt.legend()

        # 統計情報表示
        mean_wait = np.mean(waiting_times_minute)
        total_wait = np.sum(waiting_times_minute)
        print(f"95%tile: {p95:.2f}分, 平均: {mean_wait:.2f}分, 総待ち時間: {total_wait:.2f}分")

        plt.tight_layout()
        plt.show()

    def plot_kwh_timeseries(self, case: str = "シミュレーション結果") -> None:
        """累積充電量の時系列プロット

        設計意図:
        - CS別の累積充電量を可視化
        - 稼働状況を一目で確認可能
        """
        timeseries_kw = self.result.time_series_kw.copy()
        timeseries_kw.index = pd.to_datetime(timeseries_kw.index, unit='s')

        # Nanの列を削除
        timeseries_kw = timeseries_kw.dropna(axis=1, how='all')

        # CS設定取得
        cs_df = self.result.get_cs_summary()
        valid_cs = cs_df[cs_df['ports'] > 0]

        plt.figure(figsize=(12, 6))

        # 累積和計算
        cumulative_kwh = timeseries_kw.cumsum() / 60  # kW·s → kWh

        for col, port, cap in zip(cumulative_kwh.columns, valid_cs['ports'], valid_cs['capacity_kw']):
            plt.plot(cumulative_kwh[col],
                    label=f'ID{int(col)%900000}_Port{port}_{cap}kW')

        plt.title(f'累積充電量({case})', fontsize=14)
        plt.xlabel('Time', fontsize=12)
        plt.ylabel('Cumulative Power (kWh)', fontsize=12)
        plt.legend()
        plt.grid()
        plt.tight_layout()
        plt.show()

    def plot_costs_breakdown(self, case: str = "ベストトライアル") -> None:
        """コスト内訳を積み上げ棒グラフで表示

        設計意図:
        - 初期・運用・ユーザーコストの内訳を可視化
        - 正負のコストを分けて表示
        """
        # コスト計算
        initial_cost = calc_initial_costs(
            self.result.cs_config,
            self.result.time_series_kw
        )
        operational_cost = calc_running_costs(
            self.result.cs_config,
            self.result.time_series_kw
        )
        _, user_cost_yearly = calc_diff_trnsprt_costs(self.result.vehicle_trip)

        # 割引計算（簡略版、実際はcost_calculatorの定数を使用すべき）
        YEAR = 5
        DISCOUNT_RATE = 0.03
        operational_cost_discounted = sum(
            operational_cost / ((1 + DISCOUNT_RATE) ** i) for i in range(1, YEAR + 1)
        )
        user_cost_discounted = sum(
            user_cost_yearly / ((1 + DISCOUNT_RATE) ** i) for i in range(1, YEAR + 1)
        )

        total_cost = initial_cost + operational_cost_discounted + user_cost_discounted

        # プロット
        plt.figure(figsize=(10, 6))

        costs_values = [initial_cost, operational_cost_discounted, user_cost_discounted]
        labels = ['初期コスト', '運用コスト', 'ユーザーコスト']
        colors = ['skyblue', 'orange', 'green']

        # 正負を分けて積み上げ
        bottom_pos = 0
        for cost, label, color in zip(costs_values, labels, colors):
            if cost >= 0:
                plt.bar(0, cost, bottom=bottom_pos, width=0.6,
                       label=label, color=color, alpha=0.7)
                plt.text(0, bottom_pos + cost/2, f'{cost:.0f}',
                        ha='center', va='center', fontweight='bold')
                bottom_pos += cost

        # 総コスト線
        plt.axhline(y=total_cost, color='red', linestyle='--', linewidth=2,
                   label=f'総コスト: {total_cost:.0f}万円')

        plt.title(f'コスト内訳({case})', fontsize=14)
        plt.ylabel('コスト (万円)', fontsize=12)
        plt.xticks([0], [case])
        plt.legend(loc='upper right')
        plt.grid(axis='y', alpha=0.3)
        plt.tight_layout()
        plt.show()

    def _get_waiting_times_minutes(self) -> pd.Series:
        """待ち時間を分単位で取得（内部メソッド）

        設計意図:
        - 共通計算ロジックを内部メソッドとして抽出
        - 複数の可視化メソッドで再利用
        """
        charging_trip = self.result.vehicle_trip[
            self.result.vehicle_trip['startChargingTime'] > 0
        ]
        waiting_times_minute = (
            charging_trip['startChargingTime'] - charging_trip['WaitingEntryTime']
        ) / 60
        return waiting_times_minute

    @staticmethod
    def from_pickle(filepath: str) -> 'ResultVisualizer':
        """pickleファイルからResultVisualizerを生成

        設計意図:
        - ファクトリーメソッドでインスタンス生成を簡潔に
        - ファイルからの読み込みを1行で実現

        使用例:
            >>> viz = ResultVisualizer.from_pickle("result.pkl")
            >>> viz.plot_waiting_times()
        """
        with open(filepath, 'rb') as f:
            result = pickle.load(f)

        # 後方互換性: 辞書の場合はSimulationResultに変換
        if isinstance(result, dict):
            result = SimulationResult(**result)

        return ResultVisualizer(result)


def get_waiting_times(result_file: str) -> pd.Series:
    """待ち時間を取得する関数（後方互換性のため残す）

    設計意図:
    - 既存コードとの互換性維持
    - 新しいコードではResultVisualizer.from_pickle()を推奨
    """
    viz = ResultVisualizer.from_pickle(result_file)
    return viz._get_waiting_times_minutes()
