#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""コスト比較可視化（箱ひげ図）

P値ごとの故障シナリオ群のコスト分布を箱ひげ図で表示。
平常時は★マーカーで強調表示する。
"""

from pathlib import Path
from typing import List, Optional
import sys

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from rich.console import Console

# プロジェクトルートの設定
project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.util.scenario_compare import ScenarioComparator

console = Console()

# 日本語フォント設定
plt.rcParams['font.family'] = ['MS Gothic', 'Hiragino Sans', 'IPAGothic', 'sans-serif']


def plot_cost_comparison_boxplot(
    comparator: ScenarioComparator,
    save_dir: Path,
    save_png: bool = True,
    save_html: bool = True,
) -> None:
    """P値ごとのコスト箱ひげ図を生成

    Args:
        comparator: 結果が収集済みのScenarioComparator
        save_dir: 保存先ディレクトリ
        save_png: PNGを保存するか
        save_html: HTMLを保存するか
    """
    df = comparator.get_cost_comparison_data()

    if df.empty:
        console.print("[yellow]⚠️ 比較データがありません[/yellow]")
        return

    p_percents = sorted(df['p_percent'].unique())

    # --- matplotlib版（PNG） ---
    if save_png:
        fig, ax = plt.subplots(figsize=(12, 7))

        # 故障シナリオの箱ひげ図用データ
        boxplot_data = []
        positions = []
        normal_x = []
        normal_y = []

        for i, p in enumerate(p_percents):
            # 故障シナリオ
            failure_costs = df[(df['p_percent'] == p) & (df['scenario_type'] == 'failure')]['total_cost']
            if len(failure_costs) > 0:
                boxplot_data.append(failure_costs.values)
                positions.append(i)
            else:
                boxplot_data.append([np.nan])
                positions.append(i)

            # 平常時
            normal_cost = df[(df['p_percent'] == p) & (df['scenario_type'] == 'normal')]['total_cost']
            if len(normal_cost) > 0:
                normal_x.append(i)
                normal_y.append(normal_cost.values[0])

        # 箱ひげ図
        bp = ax.boxplot(
            boxplot_data,
            positions=positions,
            patch_artist=True,
            widths=0.6,
            boxprops=dict(facecolor='lightblue', alpha=0.7),
            medianprops=dict(color='darkblue', linewidth=2),
            flierprops=dict(marker='o', markerfacecolor='gray', alpha=0.5),
        )

        # 平常時を★で強調
        ax.scatter(
            normal_x, normal_y,
            marker='*', s=300, c='gold', edgecolors='black', linewidths=1,
            label='平常時', zorder=10
        )

        ax.set_xticks(range(len(p_percents)))
        ax.set_xticklabels([f'P={p}%' for p in p_percents], fontsize=11)
        ax.set_xlabel('故障重み（P値）', fontsize=12)
        ax.set_ylabel('総コスト（万円）', fontsize=12)
        ax.set_title('P値別コスト比較（故障シナリオ群 + 平常時★）', fontsize=14)
        ax.grid(axis='y', alpha=0.3)
        ax.legend(loc='upper left')

        plt.tight_layout()
        png_path = save_dir / 'cost_comparison_boxplot.png'
        plt.savefig(png_path, dpi=150)
        plt.close()
        console.print(f"[green]✅ コスト比較箱ひげ図を保存: {png_path}[/green]")

    # --- Plotly版（HTML） ---
    if save_html:
        fig = go.Figure()

        # 故障シナリオの箱ひげ図
        for p in p_percents:
            failure_costs = df[(df['p_percent'] == p) & (df['scenario_type'] == 'failure')]['total_cost']
            if len(failure_costs) > 0:
                fig.add_trace(go.Box(
                    y=failure_costs,
                    name=f'P={p}%',
                    boxmean=True,
                    marker_color='lightblue',
                    line_color='darkblue',
                ))

        # 平常時を★で追加
        normal_data = df[df['scenario_type'] == 'normal'].copy()
        if len(normal_data) > 0:
            fig.add_trace(go.Scatter(
                x=[f'P={int(p)}%' for p in normal_data['p_percent']],
                y=normal_data['total_cost'],
                mode='markers',
                marker=dict(
                    symbol='star',
                    size=20,
                    color='gold',
                    line=dict(color='black', width=2)
                ),
                name='平常時',
                hovertemplate='P=%{x}<br>コスト: %{y:.1f}万円<extra>平常時</extra>'
            ))

        fig.update_layout(
            title='P値別コスト比較（故障シナリオ群 + 平常時★）',
            xaxis_title='故障重み（P値）',
            yaxis_title='総コスト（万円）',
            template='plotly_white',
            showlegend=True,
            hovermode='closest',
        )

        html_path = save_dir / 'cost_comparison_boxplot.html'
        fig.write_html(str(html_path))
        console.print(f"[green]✅ コスト比較HTML保存: {html_path}[/green]")


def plot_cost_breakdown_comparison(
    comparator: ScenarioComparator,
    save_dir: Path,
) -> None:
    """P値ごとのコスト内訳を比較（積み上げ棒グラフ、平常時のみ）"""

    df = comparator.get_cost_comparison_data()
    normal_df = df[df['scenario_type'] == 'normal'].copy()

    if normal_df.empty:
        return

    normal_df = normal_df.sort_values('p_percent')

    fig, ax = plt.subplots(figsize=(12, 6))

    x = np.arange(len(normal_df))
    width = 0.6

    # 積み上げ
    ax.bar(x, normal_df['initial_cost'], width, label='初期コスト', color='#2ecc71')
    ax.bar(x, normal_df['running_cost'], width, bottom=normal_df['initial_cost'],
           label='運用コスト', color='#3498db')
    ax.bar(x, normal_df['user_cost'], width,
           bottom=normal_df['initial_cost'] + normal_df['running_cost'],
           label='ユーザーコスト', color='#e74c3c')

    ax.set_xticks(x)
    ax.set_xticklabels([f'P={p}%' for p in normal_df['p_percent']], fontsize=11)
    ax.set_xlabel('故障重み（P値）', fontsize=12)
    ax.set_ylabel('コスト（万円）', fontsize=12)
    ax.set_title('P値別コスト内訳（平常時）', fontsize=14)
    ax.legend(loc='upper left')
    ax.grid(axis='y', alpha=0.3)

    plt.tight_layout()
    save_path = save_dir / 'cost_breakdown_comparison.png'
    plt.savefig(save_path, dpi=150)
    plt.close()
    console.print(f"[green]✅ コスト内訳比較を保存: {save_path}[/green]")
