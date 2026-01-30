#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""充電ステーション配置の可視化"""

from pathlib import Path
import pickle
import sys
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import japanize_matplotlib  # noqa: F401
import numpy as np
import pandas as pd
from rich.console import Console

from .base import register_visualizer

# プロジェクトルートの設定
project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.util.path_manager import get_paths

console = Console()


@register_visualizer(
    name="cs_placement_map",
    description="地図上に充電ステーション配置を可視化",
    output_file="cs_placement_map",
    priority=40,
)
def plot_cs_placement_map(
    result_file: Path,
    save_dir: Path,
    **context,
) -> None:
    """地図上に充電ステーション配置を可視化"""

    save_path = save_dir / "cs_placement_map.png"

    # 結果読み込み
    with open(result_file, 'rb') as f:
        emates_result = pickle.load(f)

    cs_config = emates_result.cs_config

    # 地図データ読み込み
    base_paths = get_paths()
    shikata_path = base_paths['shikata']

    map_path = Path(shikata_path) / 'mapPosition.txt'
    network_path = Path(shikata_path) / 'network.txt'
    cslist_path = Path(shikata_path) / 'csList.txt'

    map_df = pd.read_csv(map_path, sep=',', header=None, names=['ID', 'X', 'Y', 'Z'])
    network_df = pd.read_csv(network_path, sep=',', header=None,
                             names=['from', 'link', 'to_1', 'to_2', 'to_3', 'to_4'])
    cslist_df = pd.read_csv(cslist_path, sep=',', header=None, names=['ID', 'port', 'kw'])

    fig, ax = plt.subplots(figsize=(12, 10))

    # ノードの描画
    ax.scatter(map_df['X'], map_df['Y'], c='lightblue', s=5, alpha=0.3, label='ノード')

    # リンクの描画
    for _, row in network_df.iterrows():
        from_node = map_df[map_df['ID'] == row['from']]
        for to_col in ['to_1', 'to_2', 'to_3', 'to_4']:
            if pd.notna(row[to_col]) and row[to_col] != 0:
                to_node = map_df[map_df['ID'] == row[to_col]]
                if not from_node.empty and not to_node.empty:
                    ax.plot([from_node['X'].iloc[0], to_node['X'].iloc[0]],
                           [from_node['Y'].iloc[0], to_node['Y'].iloc[0]],
                           'gray', alpha=0.2, linewidth=0.2)

    # 候補地を表示
    csids_candidates = cslist_df['ID']
    candidate_stations = map_df[map_df['ID'].isin(csids_candidates)]
    ax.scatter(candidate_stations['X'], candidate_stations['Y'], c='lightgray',
              s=80, marker='s', alpha=0.5, label='候補地', edgecolors='gray')

    # CS配置を抽出
    cs_df = pd.DataFrame({
        'csids': cs_config.get('csids', []),
        'ports': cs_config.get('ports', []),
        'cap_kw': cs_config.get('cap_kw', [])
    })
    setting_cs = cs_df[cs_df['ports'] > 0]

    if len(setting_cs) > 0:
        setting_cs_with_pos = pd.merge(
            setting_cs, map_df,
            left_on='csids', right_on='ID', how='inner'
        )

        unique_kw = sorted(setting_cs_with_pos['cap_kw'].unique())
        colors_discrete = plt.cm.viridis(np.linspace(0.2, 0.8, len(unique_kw)))
        color_map = {kw: colors_discrete[i] for i, kw in enumerate(unique_kw)}
        colors = [color_map[kw] for kw in setting_cs_with_pos['cap_kw']]

        sizes = setting_cs_with_pos['ports'] * 200

        ax.scatter(setting_cs_with_pos['X'], setting_cs_with_pos['Y'],
                  c=colors, s=sizes, alpha=0.9,
                  edgecolors='black', linewidths=1.5, label='設置CS')

        for _, row in setting_cs_with_pos.iterrows():
            ax.annotate(
                f'{int(row["ports"])}口\n{int(row["cap_kw"])}kW',
                (row['X'], row['Y']),
                xytext=(5, 5), textcoords='offset points',
                fontsize=9, ha='left', va='bottom',
                bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.8)
            )

        legend_elements = [
            mpatches.Patch(color=color_map[kw], label=f'{int(kw)}kW')
            for kw in unique_kw
        ]
        ax.legend(handles=legend_elements, loc='upper left', title='充電出力')

    ax.set_title("充電ステーション配置", fontsize=14)
    ax.set_xlabel('X座標', fontsize=11)
    ax.set_ylabel('Y座標', fontsize=11)
    ax.axis('equal')
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()

    console.print(f"[green]✅ 配置地図を保存: {save_path}[/green]")
