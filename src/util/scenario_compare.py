#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""シナリオ間比較モジュール

複数の最適化結果ディレクトリ（P値別）から結果を収集し、
コスト・待ち時間などを横断的に比較可視化するための機能を提供する。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any
import pickle
import re
import glob

import pandas as pd
import numpy as np

from src.util.cost_calculator import (
    calc_initial_costs,
    calc_running_costs,
    calc_diff_trnsprt_costs,
    evaluation_total_costs,
    calculate_95percentile_wait_time,
)


@dataclass
class ScenarioResult:
    """単一シナリオ（平常時または故障時）の結果"""

    scenario_type: str  # "normal" or "failure_{idx}"
    result_file: Path
    total_cost: float
    initial_cost: float
    running_cost: float
    user_cost: float
    wait_time_95p: float  # 秒
    mean_wait_time: float  # 秒
    cs_placements: List[Dict]  # [{"csid": ..., "ports": ..., "cap_kw": ...}, ...]

    @property
    def is_normal(self) -> bool:
        return self.scenario_type == "normal"


@dataclass
class PValueResult:
    """あるP値（故障重み）における全シナリオの結果"""

    p_value: float  # 0.0 ~ 1.0
    dir_path: Path
    normal_result: Optional[ScenarioResult] = None
    failure_results: List[ScenarioResult] = field(default_factory=list)

    @property
    def all_costs(self) -> List[float]:
        """全シナリオ（故障）のコストリスト"""
        return [r.total_cost for r in self.failure_results]

    @property
    def all_wait_times_95p(self) -> List[float]:
        """全シナリオ（故障）の95%tile待ち時間リスト（秒）"""
        return [r.wait_time_95p for r in self.failure_results]

    @property
    def all_mean_wait_times(self) -> List[float]:
        """全シナリオ（故障）の平均待ち時間リスト（秒）"""
        return [r.mean_wait_time for r in self.failure_results]


def extract_p_value_from_dirname(dirname: str) -> Optional[float]:
    """ディレクトリ名からP値を抽出

    例: "unified_P50" -> 0.5, "unified_P00" -> 0.0
    """
    match = re.search(r'_P(\d+)', dirname)
    if match:
        return int(match.group(1)) / 100.0
    return None


def load_scenario_result(result_file: Path) -> ScenarioResult:
    """pklファイルからシナリオ結果を読み込み"""

    with open(result_file, 'rb') as f:
        emates_result = pickle.load(f)

    cs_config = emates_result.cs_config
    vehicle_trip = emates_result.vehicle_trip
    timeseries_kw = emates_result.time_series_kw

    # コスト計算
    initial_cost = calc_initial_costs(cs_config, timeseries_kw)
    running_cost = calc_running_costs(cs_config, timeseries_kw)
    _, user_cost = calc_diff_trnsprt_costs(vehicle_trip)
    total_cost, _ = evaluation_total_costs(str(result_file))
    wait_time_95p = calculate_95percentile_wait_time(str(result_file))

    # 平均待ち時間
    charging_trip = vehicle_trip[vehicle_trip['startChargingTime'] > 0]
    if len(charging_trip) > 0:
        wait_times = (
            charging_trip['startChargingTime'] - charging_trip['WaitingEntryTime']
        )
        mean_wait_time = wait_times.mean()
    else:
        mean_wait_time = 0.0

    # CS配置
    cs_placements = []
    for csid, ports, cap_kw in zip(
        cs_config.get('csids', []),
        cs_config.get('ports', []),
        cs_config.get('cap_kw', [])
    ):
        if ports > 0:
            cs_placements.append({
                'csid': csid,
                'ports': ports,
                'cap_kw': cap_kw
            })

    # シナリオタイプ判定
    filename = result_file.name
    if "_normal" in filename:
        scenario_type = "normal"
    elif "_failure" in filename:
        # failure_N の形式からインデックスを抽出
        match = re.search(r'_failure_?(\d+)?', filename)
        if match and match.group(1):
            scenario_type = f"failure_{match.group(1)}"
        else:
            scenario_type = "failure"
    else:
        scenario_type = "unknown"

    return ScenarioResult(
        scenario_type=scenario_type,
        result_file=result_file,
        total_cost=total_cost,
        initial_cost=initial_cost,
        running_cost=running_cost,
        user_cost=user_cost,
        wait_time_95p=wait_time_95p,
        mean_wait_time=mean_wait_time,
        cs_placements=cs_placements,
    )


def collect_p_value_results(result_dir: Path) -> PValueResult:
    """1つのP値ディレクトリから全シナリオの結果を収集"""

    p_value = extract_p_value_from_dirname(result_dir.name)
    if p_value is None:
        p_value = 0.5  # フォールバック

    result = PValueResult(p_value=p_value, dir_path=result_dir)

    # pklファイルを探索
    pkl_files = list(result_dir.glob("*.pkl"))

    for pkl_file in pkl_files:
        try:
            scenario = load_scenario_result(pkl_file)
            if scenario.is_normal:
                result.normal_result = scenario
            else:
                result.failure_results.append(scenario)
        except Exception as e:
            print(f"⚠️ {pkl_file.name} の読み込みエラー: {e}")

    return result


class ScenarioComparator:
    """複数P値のシナリオを比較"""

    def __init__(self, result_dirs: List[Path]):
        """
        Args:
            result_dirs: 比較対象のディレクトリリスト（各P値ごと）
        """
        self.result_dirs = sorted(result_dirs, key=lambda d: d.name)
        self.p_value_results: List[PValueResult] = []

    def collect_all_results(self) -> None:
        """全ディレクトリから結果を収集"""
        for dir_path in self.result_dirs:
            if dir_path.is_dir():
                result = collect_p_value_results(dir_path)
                self.p_value_results.append(result)

        # P値でソート
        self.p_value_results.sort(key=lambda r: r.p_value)

    def get_cost_comparison_data(self) -> pd.DataFrame:
        """コスト比較用のDataFrameを生成

        Returns:
            DataFrameの列:
            - p_value: 故障重み（0-1）
            - p_percent: 故障重み（0-100%）
            - scenario_type: "normal" or "failure"
            - total_cost: 総コスト
        """
        rows = []
        for pv_result in self.p_value_results:
            p_percent = int(pv_result.p_value * 100)

            # 平常時
            if pv_result.normal_result:
                rows.append({
                    'p_value': pv_result.p_value,
                    'p_percent': p_percent,
                    'scenario_type': 'normal',
                    'total_cost': pv_result.normal_result.total_cost,
                    'initial_cost': pv_result.normal_result.initial_cost,
                    'running_cost': pv_result.normal_result.running_cost,
                    'user_cost': pv_result.normal_result.user_cost,
                })

            # 故障時
            for f_result in pv_result.failure_results:
                rows.append({
                    'p_value': pv_result.p_value,
                    'p_percent': p_percent,
                    'scenario_type': 'failure',
                    'total_cost': f_result.total_cost,
                    'initial_cost': f_result.initial_cost,
                    'running_cost': f_result.running_cost,
                    'user_cost': f_result.user_cost,
                })

        return pd.DataFrame(rows)

    def get_wait_time_comparison_data(self) -> pd.DataFrame:
        """待ち時間比較用のDataFrameを生成

        Returns:
            DataFrameの列:
            - p_value, p_percent, scenario_type
            - wait_time_95p: 95パーセンタイル待ち時間（分）
            - mean_wait_time: 平均待ち時間（分）
        """
        rows = []
        for pv_result in self.p_value_results:
            p_percent = int(pv_result.p_value * 100)

            if pv_result.normal_result:
                rows.append({
                    'p_value': pv_result.p_value,
                    'p_percent': p_percent,
                    'scenario_type': 'normal',
                    'wait_time_95p': pv_result.normal_result.wait_time_95p / 60,
                    'mean_wait_time': pv_result.normal_result.mean_wait_time / 60,
                })

            for f_result in pv_result.failure_results:
                rows.append({
                    'p_value': pv_result.p_value,
                    'p_percent': p_percent,
                    'scenario_type': 'failure',
                    'wait_time_95p': f_result.wait_time_95p / 60,
                    'mean_wait_time': f_result.mean_wait_time / 60,
                })

        return pd.DataFrame(rows)


def find_result_dirs_by_pattern(pattern: str) -> List[Path]:
    """パターンにマッチするディレクトリを検索

    Args:
        pattern: globパターン（例: "Z:\\output\\unified_P*"）

    Returns:
        マッチしたディレクトリのリスト
    """
    matched = glob.glob(pattern)
    dirs = [Path(p) for p in matched if Path(p).is_dir()]
    return sorted(dirs, key=lambda d: d.name)
