#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""統計サマリーの生成"""

from pathlib import Path
import pickle
import sys
from rich.console import Console

from .base import register_visualizer

# プロジェクトルートの設定
project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.util.cost_calculator import (
    calc_initial_costs,
    calc_running_costs,
    calc_diff_trnsprt_costs,
    evaluation_total_costs,
    calculate_95percentile_wait_time,
    YEAR,
    DISCOUNT_RATE,
)

console = Console()


def _aggregate_trip_times(result_file: Path) -> dict:
    """旅行時間を充電/非充電車両別に集計"""
    with open(result_file, 'rb') as f:
        emates_result = pickle.load(f)

    vehicle_trip = emates_result.vehicle_trip
    vehicle_trip = vehicle_trip[vehicle_trip['StartTime'] < 86400].copy()
    vehicle_trip['TripTime'] = vehicle_trip['EndTime'] - vehicle_trip['StartTime']

    charging_mask = vehicle_trip['startChargingTime'] > 0
    charging_trips = vehicle_trip[charging_mask]
    non_charging_trips = vehicle_trip[~charging_mask]

    return {
        'charging_count': len(charging_trips),
        'charging_total_time_hours': charging_trips['TripTime'].sum() / 3600,
        'non_charging_count': len(non_charging_trips),
        'non_charging_total_time_hours': non_charging_trips['TripTime'].sum() / 3600,
    }


@register_visualizer(
    name="results_summary",
    description="統計サマリーをテキストファイルとして保存",
    output_file="results_summary",
    priority=50,
)
def generate_results_summary(
    result_file: Path,
    save_dir: Path,
    **context,
) -> None:
    """統計サマリーをテキストファイルとして保存"""

    save_path = save_dir / "results_summary.txt"

    with open(result_file, 'rb') as f:
        emates_result = pickle.load(f)

    cs_config = emates_result.cs_config
    vehicle_trip = emates_result.vehicle_trip
    timeseries_kw = emates_result.time_series_kw

    # コスト計算
    initial_costs = calc_initial_costs(cs_config, timeseries_kw)
    running_costs = calc_running_costs(cs_config, timeseries_kw)
    diff_time, user_costs = calc_diff_trnsprt_costs(vehicle_trip)
    total_cost, _ = evaluation_total_costs(str(result_file))
    wait_time_95p = calculate_95percentile_wait_time(str(result_file))

    # 割引計算
    running_discounted = sum(running_costs / ((1 + DISCOUNT_RATE) ** i)
                            for i in range(1, YEAR + 1))
    user_discounted = sum(user_costs / ((1 + DISCOUNT_RATE) ** i)
                         for i in range(1, YEAR + 1))

    # 旅行時間集計
    trip_stats = _aggregate_trip_times(result_file)

    # CS情報
    active_cs = [(csid, port, cap)
                 for csid, port, cap in zip(
                     cs_config.get('csids', []),
                     cs_config.get('ports', []),
                     cs_config.get('cap_kw', [])
                 ) if port > 0]

    total_ports = sum(port for _, port, _ in active_cs)
    total_capacity = sum(port * cap for _, port, cap in active_cs)

    # サマリーテキスト作成
    lines = [
        "=" * 60,
        "📊 最適化結果サマリー",
        "=" * 60,
        "",
        f"📁 結果ファイル: {result_file.name}",
        "",
        "--- 充電ステーション設定 ---",
        f"  設置CS数: {len(active_cs)} 箇所",
        f"  総ポート数: {total_ports}",
        f"  総最大出力: {total_capacity:.0f} kW",
        "",
    ]

    for csid, port, cap in active_cs:
        lines.append(f"  CS#{csid}: {port}ポート, {cap:.0f}kW")

    lines.extend([
        "",
        "--- コスト計算 ---",
        f"  初期コスト: {initial_costs:,.1f} 万円",
        f"  運用コスト（年間）: {running_costs:,.1f} 万円",
        f"  運用コスト（{YEAR}年割引後）: {running_discounted:,.1f} 万円",
        f"  ユーザーコスト（年間）: {user_costs:,.1f} 万円",
        f"  ユーザーコスト（{YEAR}年割引後）: {user_discounted:,.1f} 万円",
        f"  総コスト: {total_cost:,.1f} 万円",
        "",
        "--- 待ち時間 ---",
        f"  95パーセンタイル: {wait_time_95p:.1f} 秒 ({wait_time_95p/60:.1f} 分)",
        "",
        "--- 車両トリップ ---",
        f"  充電車両数: {trip_stats['charging_count']:,} 台",
        f"  充電車両 総旅行時間: {trip_stats['charging_total_time_hours']:.1f} 時間",
        f"  非充電車両数: {trip_stats['non_charging_count']:,} 台",
        f"  非充電車両 総旅行時間: {trip_stats['non_charging_total_time_hours']:.1f} 時間",
        "",
        "=" * 60,
    ])

    with open(save_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    console.print(f"[green]✅ サマリーを保存: {save_path}[/green]")
