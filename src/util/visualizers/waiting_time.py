#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""待ち時間の可視化"""

from pathlib import Path
import pickle
import matplotlib.pyplot as plt
import japanize_matplotlib  # noqa: F401
import numpy as np
import pandas as pd
from rich.console import Console

from .base import register_visualizer

console = Console()


def _get_waiting_times(result_file: Path) -> pd.Series:
    """結果ファイルから待ち時間を取得（分単位）"""
    with open(result_file, 'rb') as f:
        emates_result = pickle.load(f)

    vehicle_trip = emates_result.vehicle_trip
    charging_trip = vehicle_trip[vehicle_trip['startChargingTime'] > 0]
    waiting_times_minute = (
        charging_trip['startChargingTime'] - charging_trip['WaitingEntryTime']
    ) / 60

    return waiting_times_minute


@register_visualizer(
    name="waiting_time_histogram",
    description="待ち時間ヒストグラム",
    output_file="waiting_time_histogram",
    priority=20,
)
def plot_waiting_time_histogram(
    result_file: Path,
    save_dir: Path,
    bins: int = 20,
    **context,
) -> None:
    """待ち時間ヒストグラムをプロット"""

    save_path = save_dir / "waiting_time_histogram.png"
    waiting_times = _get_waiting_times(result_file)

    if len(waiting_times) == 0:
        console.print("[yellow]⚠️ 充電車両がありません[/yellow]")
        return

    fig, ax = plt.subplots(figsize=(10, 6))

    ax.hist(waiting_times, bins=bins, color='skyblue', edgecolor='black', alpha=0.7)

    # 95パーセンタイル
    p95 = np.percentile(waiting_times, 95)
    ax.axvline(p95, color='red', linestyle='dashed', linewidth=2,
               label=f'95%tile: {p95:.1f}分')

    # 平均
    mean_wait = np.mean(waiting_times)
    ax.axvline(mean_wait, color='orange', linestyle='dotted', linewidth=2,
               label=f'平均: {mean_wait:.1f}分')

    ax.set_title("待ち時間分布", fontsize=14)
    ax.set_xlabel('待ち時間 (分)', fontsize=12)
    ax.set_ylabel('台数', fontsize=12)
    ax.grid(axis='y', alpha=0.3)
    ax.legend()

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()

    console.print(f"[green]✅ 待ち時間ヒストグラムを保存: {save_path}[/green]")


@register_visualizer(
    name="waiting_time_boxplot",
    description="待ち時間箱ひげ図（複数ケース比較用）",
    output_file="waiting_time_boxplot",
    priority=21,
)
def plot_waiting_time_boxplot(
    result_file: Path,
    save_dir: Path,
    result_files: list[Path] = None,
    labels: list[str] = None,
    **context,
) -> None:
    """待ち時間箱ひげ図をプロット（複数ケース比較）"""

    # 複数ファイルが指定されていない場合はスキップ
    if result_files is None or len(result_files) < 2:
        return

    save_path = save_dir / "waiting_time_boxplot.png"

    waiting_times_list = []
    for rf in result_files:
        waiting_times = _get_waiting_times(rf)
        waiting_times_list.append(waiting_times)

    if labels is None:
        labels = [f.stem for f in result_files]

    fig, ax = plt.subplots(figsize=(10, 6))

    ax.boxplot(waiting_times_list, labels=labels, patch_artist=True,
               boxprops=dict(facecolor='lightblue', alpha=0.7))

    ax.set_title("待ち時間比較", fontsize=14)
    ax.set_ylabel('待ち時間 (分)', fontsize=12)
    ax.grid(axis='y', alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()

    console.print(f"[green]✅ 待ち時間箱ひげ図を保存: {save_path}[/green]")
