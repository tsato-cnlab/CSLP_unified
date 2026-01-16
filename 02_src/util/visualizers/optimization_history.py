#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最適化履歴の可視化"""

from pathlib import Path
import matplotlib.pyplot as plt
import japanize_matplotlib  # noqa: F401
import optuna
from rich.console import Console

from .base import register_visualizer

console = Console()


@register_visualizer(
    name="optimization_history",
    description="Optuna最適化推移グラフ",
    output_file="optimization_history",
    requires_study=True,
    requires_result_file=False,
    priority=10,
)
def plot_optimization_history(
    result_file: Path,
    save_dir: Path,
    study: optuna.Study = None,
    **context,
) -> None:
    """Optuna最適化履歴をプロット（matplotlib版）"""

    if study is None:
        console.print("[yellow]⚠️ Studyが指定されていないためスキップ[/yellow]")
        return

    save_path = save_dir / "optimization_history.png"

    # トライアル情報を取得
    trials = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]

    if len(trials) == 0:
        console.print("[yellow]⚠️ 完了したトライアルがありません[/yellow]")
        return

    trial_numbers = [t.number for t in trials]
    trial_values = [t.value for t in trials]

    # ベスト値の推移を計算
    best_values = []
    current_best = float('inf')
    for val in trial_values:
        if val < current_best:
            current_best = val
        best_values.append(current_best)

    # プロット
    fig, ax = plt.subplots(figsize=(12, 6))

    ax.scatter(trial_numbers, trial_values, alpha=0.5, s=30,
               label='各トライアル', color='#1f77b4')

    ax.plot(trial_numbers, best_values, 'r-', linewidth=2,
            label=f'ベスト値推移 (最終: {best_values[-1]:.1f}万円)')

    ax.set_xlabel('トライアル番号', fontsize=12)
    ax.set_ylabel('目的関数値 (万円)', fontsize=12)
    ax.set_title('Optuna最適化履歴', fontsize=14)
    ax.legend(loc='upper right')
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()

    console.print(f"[green]✅ 最適化履歴を保存: {save_path}[/green]")
    console.print(f"[cyan]📊 Best Trial: #{study.best_trial.number}, Value: {study.best_value:.2f}万円[/cyan]")
