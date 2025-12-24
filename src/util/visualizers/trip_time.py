#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""旅行時間の可視化"""

from pathlib import Path
import pickle
import matplotlib.pyplot as plt
import japanize_matplotlib  # noqa: F401
from rich.console import Console

from .base import register_visualizer

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
        'charging_mean_time_minutes': charging_trips['TripTime'].mean() / 60 if len(charging_trips) > 0 else 0,
        'non_charging_count': len(non_charging_trips),
        'non_charging_total_time_hours': non_charging_trips['TripTime'].sum() / 3600,
        'non_charging_mean_time_minutes': non_charging_trips['TripTime'].mean() / 60 if len(non_charging_trips) > 0 else 0,
    }


@register_visualizer(
    name="trip_time_comparison",
    description="充電/非充電車両の旅行時間比較",
    output_file="trip_time_comparison",
    priority=30,
)
def plot_trip_time_comparison(
    result_file: Path,
    save_dir: Path,
    **context,
) -> None:
    """充電/非充電車両の旅行時間を比較プロット"""

    save_path = save_dir / "trip_time_comparison.png"
    stats = _aggregate_trip_times(result_file)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    categories = ['充電車両', '非充電車両']
    total_times = [
        stats['charging_total_time_hours'],
        stats['non_charging_total_time_hours']
    ]
    colors = ['#4ECDC4', '#95E1D3']

    axes[0].bar(categories, total_times, color=colors, edgecolor='black', alpha=0.8)
    axes[0].set_title('総旅行時間', fontsize=12)
    axes[0].set_ylabel('旅行時間 (時間)', fontsize=11)
    axes[0].grid(axis='y', alpha=0.3)

    for i, val in enumerate(total_times):
        axes[0].text(i, val + max(total_times) * 0.02, f'{val:.1f}h',
                    ha='center', fontsize=10)

    counts = [stats['charging_count'], stats['non_charging_count']]

    axes[1].bar(categories, counts, color=colors, edgecolor='black', alpha=0.8)
    axes[1].set_title('車両数', fontsize=12)
    axes[1].set_ylabel('台数', fontsize=11)
    axes[1].grid(axis='y', alpha=0.3)

    for i, val in enumerate(counts):
        axes[1].text(i, val + max(counts) * 0.02, f'{val:,}台',
                    ha='center', fontsize=10)

    fig.suptitle("旅行時間比較", fontsize=14)
    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()

    console.print(f"[green]✅ 旅行時間比較を保存: {save_path}[/green]")
