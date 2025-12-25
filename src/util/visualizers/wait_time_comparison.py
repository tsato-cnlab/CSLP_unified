#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""待ち時間比較可視化（箱ひげ図）

P値ごとの故障シナリオ群の待ち時間分布を箱ひげ図で表示。
平均待ち時間と95パーセンタイル待ち時間の2種類を生成。
平常時は★マーカーで強調表示する。
"""

from pathlib import Path
from typing import List, Optional
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from rich.console import Console

# プロジェクトルートの設定
project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.util.scenario_compare import ScenarioComparator

console = Console()

# 日本語フォント設定
plt.rcParams['font.family'] = ['MS Gothic', 'Hiragino Sans', 'IPAGothic', 'sans-serif']


def _create_wait_time_boxplot_matplotlib(
    df: pd.DataFrame,
    column: str,
    ylabel: str,
    title: str,
    save_path: Path,
) -> None:
    """matplotlib版の待ち時間箱ひげ図を生成"""

    p_percents = sorted(df['p_percent'].unique())

    fig, ax = plt.subplots(figsize=(12, 7))

    boxplot_data = []
    positions = []
    normal_x = []
    normal_y = []

    for i, p in enumerate(p_percents):
        # 故障シナリオ
        failure_data = df[(df['p_percent'] == p) & (df['scenario_type'] == 'failure')][column]
        if len(failure_data) > 0:
            boxplot_data.append(failure_data.values)
        else:
            boxplot_data.append([np.nan])
        positions.append(i)

        # 平常時
        normal_data = df[(df['p_percent'] == p) & (df['scenario_type'] == 'normal')][column]
        if len(normal_data) > 0:
            normal_x.append(i)
            normal_y.append(normal_data.values[0])

    # 箱ひげ図
    bp = ax.boxplot(
        boxplot_data,
        positions=positions,
        patch_artist=True,
        widths=0.6,
        boxprops=dict(facecolor='lightgreen', alpha=0.7),
        medianprops=dict(color='darkgreen', linewidth=2),
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
    ax.set_ylabel(ylabel, fontsize=12)
    ax.set_title(title, fontsize=14)
    ax.grid(axis='y', alpha=0.3)
    ax.legend(loc='upper left')

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()
    console.print(f"[green]✅ 保存: {save_path}[/green]")


def _create_wait_time_boxplot_plotly(
    df: pd.DataFrame,
    save_dir: Path,
) -> None:
    """Plotly版の待ち時間箱ひげ図（平均+95%tile）を生成"""

    p_percents = sorted(df['p_percent'].unique())

    # 2行1列のサブプロット
    fig = make_subplots(
        rows=2, cols=1,
        subplot_titles=['平均待ち時間', '95パーセンタイル待ち時間'],
        vertical_spacing=0.12,
    )

    colors = ['lightgreen', 'lightsalmon']
    columns = ['mean_wait_time', 'wait_time_95p']

    for row, (col, color) in enumerate(zip(columns, colors), start=1):
        # 故障シナリオの箱ひげ図
        for p in p_percents:
            failure_data = df[(df['p_percent'] == p) & (df['scenario_type'] == 'failure')][col]
            if len(failure_data) > 0:
                fig.add_trace(go.Box(
                    y=failure_data,
                    name=f'P={p}%',
                    boxmean=True,
                    marker_color=color,
                    showlegend=(row == 1),
                ), row=row, col=1)

        # 平常時を★で追加
        normal_data = df[df['scenario_type'] == 'normal'].copy()
        if len(normal_data) > 0:
            fig.add_trace(go.Scatter(
                x=[f'P={int(p)}%' for p in normal_data['p_percent']],
                y=normal_data[col],
                mode='markers',
                marker=dict(
                    symbol='star',
                    size=18,
                    color='gold',
                    line=dict(color='black', width=2)
                ),
                name='平常時' if row == 1 else None,
                showlegend=(row == 1),
                hovertemplate='P=%{x}<br>待ち時間: %{y:.1f}分<extra>平常時</extra>'
            ), row=row, col=1)

    fig.update_layout(
        title='P値別待ち時間比較（故障シナリオ群 + 平常時★）',
        template='plotly_white',
        height=800,
        showlegend=True,
        hovermode='closest',
    )

    fig.update_yaxes(title_text='待ち時間（分）', row=1, col=1)
    fig.update_yaxes(title_text='待ち時間（分）', row=2, col=1)
    fig.update_xaxes(title_text='故障重み（P値）', row=2, col=1)

    html_path = save_dir / 'wait_time_comparison.html'
    fig.write_html(str(html_path))
    console.print(f"[green]✅ 待ち時間比較HTML保存: {html_path}[/green]")


def plot_wait_time_comparison_boxplot(
    comparator: ScenarioComparator,
    save_dir: Path,
    save_png: bool = True,
    save_html: bool = True,
) -> None:
    """P値ごとの待ち時間箱ひげ図を生成

    Args:
        comparator: 結果が収集済みのScenarioComparator
        save_dir: 保存先ディレクトリ
        save_png: PNGを保存するか
        save_html: HTMLを保存するか
    """
    df = comparator.get_wait_time_comparison_data()

    if df.empty:
        console.print("[yellow]⚠️ 比較データがありません[/yellow]")
        return

    # --- matplotlib版（PNG） ---
    if save_png:
        # 平均待ち時間
        _create_wait_time_boxplot_matplotlib(
            df=df,
            column='mean_wait_time',
            ylabel='平均待ち時間（分）',
            title='P値別平均待ち時間比較（故障シナリオ群 + 平常時★）',
            save_path=save_dir / 'mean_wait_time_comparison.png',
        )

        # 95パーセンタイル待ち時間
        _create_wait_time_boxplot_matplotlib(
            df=df,
            column='wait_time_95p',
            ylabel='95%tile待ち時間（分）',
            title='P値別95%tile待ち時間比較（故障シナリオ群 + 平常時★）',
            save_path=save_dir / 'wait_time_95p_comparison.png',
        )

    # --- Plotly版（HTML） ---
    if save_html:
        _create_wait_time_boxplot_plotly(df, save_dir)
