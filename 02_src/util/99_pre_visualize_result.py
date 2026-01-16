#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最適化結果可視化スクリプト

最適化完了後に結果を可視化し、PNGファイルとして保存する。
コマンドラインから単独実行可能。
"""

import argparse
import pickle
import sys
from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import japanize_matplotlib  # noqa: F401
import numpy as np
import optuna
import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

# プロジェクトルートの設定
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.util.path_manager import get_paths
from src.util.cost_calculator import (
    calc_initial_costs,
    calc_running_costs,
    calc_diff_trnsprt_costs,
    evaluation_total_costs,
    calculate_95percentile_wait_time,
    YEAR,
    DISCOUNT_RATE,
)

import warnings
import logging

import matplotlib
# matplotlibのフォント警告を完全に抑制
warnings.filterwarnings('ignore', category=UserWarning, module='matplotlib')
warnings.filterwarnings('ignore', message='findfont:.*')
logging.getLogger('matplotlib.font_manager').setLevel(logging.ERROR)

# 日本語フォント設定（Windows環境対応）
try:
    import japanize_matplotlib  # noqa: F401
except ImportError:
    pass

# 日本語フォントを設定（Windows環境で利用可能なフォントを優先）
matplotlib.rcParams['font.family'] = ['sans-serif']
matplotlib.rcParams['font.sans-serif'] = ['Yu Gothic', 'MS Gothic', 'BIZ UDGothic', 'Meiryo', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False  # マイナス記号の文字化け対策

console = Console()


def plot_optimization_history(
    db_path: Path,
    study_name: str,
    save_path: Path,
) -> None:
    """Optuna最適化履歴をプロット（matplotlib版）

    Args:
        db_path: Optunaデータベースのパス
        study_name: Study名
        save_path: 保存先パス
    """
    storage_url = f"sqlite:///{db_path}"

    try:
        study = optuna.load_study(study_name=study_name, storage=storage_url)
    except Exception as e:
        console.print(f"[red]❌ Study読み込みエラー: {e}[/red]")
        return

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

    # 各トライアルの値
    ax.scatter(trial_numbers, trial_values, alpha=0.5, s=30,
               label='各トライアル', color='#1f77b4')

    # ベスト値の推移
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


def get_waiting_times_from_result(result_file: Path) -> pd.Series:
    """結果ファイルから待ち時間を取得

    Args:
        result_file: 結果pklファイルのパス

    Returns:
        待ち時間のSeries（分単位）
    """
    with open(result_file, 'rb') as f:
        emates_result = pickle.load(f)

    vehicle_trip = emates_result.vehicle_trip
    charging_trip = vehicle_trip[vehicle_trip['startChargingTime'] > 0]
    waiting_times_minute = (
        charging_trip['startChargingTime'] - charging_trip['WaitingEntryTime']
    ) / 60

    return waiting_times_minute


def plot_waiting_time_histogram(
    result_file: Path,
    save_path: Path,
    title: str = "待ち時間分布",
    bins: int = 20,
) -> None:
    """待ち時間ヒストグラムをプロット（単一ケース）

    Args:
        result_file: 結果pklファイルのパス
        save_path: 保存先パス
        title: グラフタイトル
        bins: ビン数
    """
    waiting_times = get_waiting_times_from_result(result_file)

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

    ax.set_title(title, fontsize=14)
    ax.set_xlabel('待ち時間 (分)', fontsize=12)
    ax.set_ylabel('台数', fontsize=12)
    ax.grid(axis='y', alpha=0.3)
    ax.legend()

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()

    console.print(f"[green]✅ 待ち時間ヒストグラムを保存: {save_path}[/green]")


def plot_waiting_time_boxplot(
    result_files: list[Path],
    labels: list[str],
    save_path: Path,
    title: str = "待ち時間比較",
) -> None:
    """待ち時間箱ひげ図をプロット（複数ケース比較）

    Args:
        result_files: 結果pklファイルのリスト
        labels: 各ケースのラベル
        save_path: 保存先パス
        title: グラフタイトル
    """
    waiting_times_list = []

    for result_file in result_files:
        waiting_times = get_waiting_times_from_result(result_file)
        waiting_times_list.append(waiting_times)

    fig, ax = plt.subplots(figsize=(10, 6))

    ax.boxplot(waiting_times_list, labels=labels, patch_artist=True,
               boxprops=dict(facecolor='lightblue', alpha=0.7))

    ax.set_title(title, fontsize=14)
    ax.set_ylabel('待ち時間 (分)', fontsize=12)
    ax.grid(axis='y', alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()

    console.print(f"[green]✅ 待ち時間箱ひげ図を保存: {save_path}[/green]")


def aggregate_trip_times(result_file: Path) -> dict:
    """旅行時間を充電/非充電車両別に集計

    Args:
        result_file: 結果pklファイルのパス

    Returns:
        集計結果の辞書
    """
    with open(result_file, 'rb') as f:
        emates_result = pickle.load(f)

    vehicle_trip = emates_result.vehicle_trip

    # StartTimeが86400秒未満のデータのみ使用
    vehicle_trip = vehicle_trip[vehicle_trip['StartTime'] < 86400].copy()
    vehicle_trip['TripTime'] = vehicle_trip['EndTime'] - vehicle_trip['StartTime']

    # 充電車両と非充電車両に分割
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


def plot_trip_time_comparison(
    result_file: Path,
    save_path: Path,
    title: str = "旅行時間比較",
) -> None:
    """充電/非充電車両の旅行時間を比較プロット

    Args:
        result_file: 結果pklファイルのパス
        save_path: 保存先パス
        title: グラフタイトル
    """
    stats = aggregate_trip_times(result_file)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    # 左: 総旅行時間
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

    for i, (cat, val) in enumerate(zip(categories, total_times)):
        axes[0].text(i, val + max(total_times) * 0.02, f'{val:.1f}h',
                    ha='center', fontsize=10)

    # 右: 車両数
    counts = [stats['charging_count'], stats['non_charging_count']]

    axes[1].bar(categories, counts, color=colors, edgecolor='black', alpha=0.8)
    axes[1].set_title('車両数', fontsize=12)
    axes[1].set_ylabel('台数', fontsize=11)
    axes[1].grid(axis='y', alpha=0.3)

    for i, (cat, val) in enumerate(zip(categories, counts)):
        axes[1].text(i, val + max(counts) * 0.02, f'{val:,}台',
                    ha='center', fontsize=10)

    fig.suptitle(title, fontsize=14)
    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()

    console.print(f"[green]✅ 旅行時間比較を保存: {save_path}[/green]")


def plot_cs_placement_map(
    result_file: Path,
    save_path: Path,
    title: str = "充電ステーション配置",
) -> None:
    """地図上に充電ステーション配置を可視化

    Args:
        result_file: 結果pklファイルのパス
        save_path: 保存先パス
        title: グラフタイトル
    """
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
        # 座標情報をマージ
        setting_cs_with_pos = pd.merge(
            setting_cs, map_df,
            left_on='csids', right_on='ID', how='inner'
        )

        # カラーマップ
        unique_kw = sorted(setting_cs_with_pos['cap_kw'].unique())
        cmap = plt.cm.get_cmap('viridis')
        colors_discrete = cmap(np.linspace(0.2, 0.8, len(unique_kw)))
        color_map = {kw: colors_discrete[i] for i, kw in enumerate(unique_kw)}
        colors = [color_map[kw] for kw in setting_cs_with_pos['cap_kw']]

        # サイズはポート数に比例
        sizes = setting_cs_with_pos['ports'] * 200

        ax.scatter(setting_cs_with_pos['X'], setting_cs_with_pos['Y'],
                  c=colors, s=sizes, alpha=0.9,
                  edgecolors='black', linewidths=1.5, label='設置CS')

        # アノテーション
        for _, row in setting_cs_with_pos.iterrows():
            ax.annotate(
                f'{int(row["ports"])}口\n{int(row["cap_kw"])}kW',
                (row['X'], row['Y']),
                xytext=(5, 5), textcoords='offset points',
                fontsize=9, ha='left', va='bottom',
                bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.8)
            )

        # カラーバー用凡例
        import matplotlib.patches as mpatches
        legend_elements = [
            mpatches.Patch(color=color_map[kw], label=f'{int(kw)}kW')
            for kw in unique_kw
        ]
        ax.legend(handles=legend_elements, loc='upper left', title='充電出力')

    ax.set_title(title, fontsize=14)
    ax.set_xlabel('X座標', fontsize=11)
    ax.set_ylabel('Y座標', fontsize=11)
    ax.axis('equal')
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()

    console.print(f"[green]✅ 配置地図を保存: {save_path}[/green]")


def generate_results_summary(
    result_file: Path,
    save_path: Path,
) -> None:
    """統計サマリーをテキストファイルとして保存

    Args:
        result_file: 結果pklファイルのパス
        save_path: 保存先パス
    """
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
    trip_stats = aggregate_trip_times(result_file)

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


def generate_results_report(
    result_dir: Path,
    study_name: Optional[str] = None,
    result_file: Optional[Path] = None,
) -> None:
    """全可視化をまとめて実行

    Args:
        result_dir: 結果ディレクトリのパス
        study_name: Optuna Study名（指定しない場合は推測）
        result_file: 対象の結果pklファイル（指定しない場合は最新のnormal結果）
    """
    result_dir = Path(result_dir)

    if not result_dir.exists():
        console.print(f"[red]❌ ディレクトリが存在しません: {result_dir}[/red]")
        return

    console.print()
    console.rule("[bold cyan]最適化結果可視化[/bold cyan]", style="cyan")
    console.print()
    console.print(Panel(f"📁 対象ディレクトリ: {result_dir}", border_style="cyan"))

    # データベースを探す
    db_path = result_dir / "optuna_study_unified.db"
    best_trial_number = None

    if db_path.exists():
        if study_name is None:
            # Study名を推測
            study_name = f"unified_optimization_{result_dir.name.split('_')[-1]}"
            # フォールバック: 標準的なStudy名を試す
            try:
                storage = optuna.storages.RDBStorage(url=f"sqlite:///{db_path}")
                study_summaries = storage.get_all_studies()
                if study_summaries:
                    study_name = study_summaries[0].study_name
            except Exception:
                pass

        console.print(f"[cyan]📊 Study名: {study_name}[/cyan]")

        # 最適トライアル番号を取得
        try:
            study = optuna.load_study(study_name=study_name, storage=f"sqlite:///{db_path}")
            best_trial_number = study.best_trial.number
            console.print(f"[green]🏆 最適トライアル: #{best_trial_number} (コスト: {study.best_value:.2f}万円)[/green]")
        except Exception as e:
            console.print(f"[yellow]⚠️ 最適トライアル取得エラー: {e}[/yellow]")

        plot_optimization_history(
            db_path, study_name,
            result_dir / "optimization_history.png"
        )
    else:
        console.print("[yellow]⚠️ Optunaデータベースが見つかりません[/yellow]")

    # 結果pklファイルを探す
    if result_file is None:
        pkl_files = list(result_dir.glob("*.pkl"))

        if not pkl_files:
            console.print("[red]❌ 結果pklファイルが見つかりません[/red]")
            return

        # 最適トライアル番号がある場合、そのトライアルのファイルを優先
        if best_trial_number is not None:
            # trial_{番号}_のパターンで最適トライアルのファイルを探す
            best_trial_pattern = f"trial_{best_trial_number}_"
            best_trial_files = [f for f in pkl_files if best_trial_pattern in f.name]

            # normalファイルを優先
            normal_files = [f for f in best_trial_files if "_normal" in f.name]
            if normal_files:
                best_trial_files = normal_files

            if best_trial_files:
                # 最適トライアルのファイルから読み込み可能なものを選択
                for candidate in best_trial_files:
                    try:
                        with open(candidate, 'rb') as f:
                            _ = pickle.load(f)
                        result_file = candidate
                        console.print(f"[green]✅ 最適トライアル #{best_trial_number} のファイルを使用[/green]")
                        break
                    except Exception:
                        continue

        # 最適トライアルのファイルが見つからない場合はフォールバック
        if result_file is None:
            # _normal.pklを優先
            normal_files = [f for f in pkl_files if "_normal.pkl" in f.name]
            if normal_files:
                pkl_files = normal_files

            # ファイルサイズでソート
            pkl_files = sorted(pkl_files, key=lambda f: f.stat().st_size, reverse=True)

            for candidate in pkl_files:
                try:
                    with open(candidate, 'rb') as f:
                        _ = pickle.load(f)
                    result_file = candidate
                    break
                except Exception:
                    console.print(f"[yellow]⚠️ {candidate.name} はスキップ（読み込みエラー）[/yellow]")
                    continue

            if result_file is None:
                console.print("[red]❌ 有効な結果pklファイルが見つかりません[/red]")
                return

    console.print(f"[cyan]📄 対象ファイル: {result_file.name}[/cyan]")

    # 各可視化を実行
    plot_waiting_time_histogram(
        result_file,
        result_dir / "waiting_time_histogram.png"
    )

    plot_trip_time_comparison(
        result_file,
        result_dir / "trip_time_comparison.png"
    )

    plot_cs_placement_map(
        result_file,
        result_dir / "cs_placement_map.png"
    )

    generate_results_summary(
        result_file,
        result_dir / "results_summary.txt"
    )

    console.print()
    console.print(Panel("[bold green]✨ 全可視化完了 ✨[/bold green]", border_style="green"))
    console.print()


def run_visualizers_from_config(
    result_dir: Path,
    result_file: Optional[Path],
    study: Optional[optuna.Study] = None,
    config_path: Optional[Path] = None,
) -> None:
    """設定ファイルに基づいてプラグインを実行

    Args:
        result_dir: 保存先ディレクトリ
        result_file: 結果pklファイル
        study: Optuna Study（任意）
        config_path: 設定ファイルパス（省略時はデフォルト）
    """
    import yaml
    from src.util.visualizers import get_visualizers_sorted

    # デフォルト設定パス
    if config_path is None:
        config_path = project_root / "visualization_config.yaml"

    # 設定読み込み
    enabled_visualizers = {}
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        visualizers_config = config.get('visualizers', {})
        for name, settings in visualizers_config.items():
            if isinstance(settings, dict):
                enabled_visualizers[name] = settings.get('enabled', True)
            else:
                enabled_visualizers[name] = bool(settings)

    # コンテキスト作成
    context = {
        'study': study,
        'result_dir': result_dir,
    }

    # 登録済みプラグインを順番に実行
    for visualizer in get_visualizers_sorted():
        # 設定で無効化されていればスキップ
        if visualizer.name in enabled_visualizers and not enabled_visualizers[visualizer.name]:
            console.print(f"[dim]⏭️ {visualizer.name} はスキップ（設定で無効化）[/dim]")
            continue

        # 必要なリソースがなければスキップ
        if visualizer.requires_study and study is None:
            console.print(f"[dim]⏭️ {visualizer.name} はスキップ（Studyが必要）[/dim]")
            continue

        if visualizer.requires_result_file and result_file is None:
            console.print(f"[dim]⏭️ {visualizer.name} はスキップ（結果ファイルが必要）[/dim]")
            continue

        try:
            visualizer.func(result_file, result_dir, **context)
        except Exception as e:
            console.print(f"[yellow]⚠️ {visualizer.name} でエラー: {e}[/yellow]")


def compare_scenarios(
    result_dirs: list[Path],
    output_dir: Path,
    save_png: bool = True,
    save_html: bool = True,
) -> None:
    """複数シナリオを比較可視化

    Args:
        result_dirs: 比較対象のディレクトリリスト
        output_dir: 出力先ディレクトリ
        save_png: PNGを保存するか
        save_html: HTMLを保存するか
    """
    from src.util.scenario_compare import ScenarioComparator
    from src.util.visualizers.cost_comparison import (
        plot_cost_comparison_boxplot,
        plot_cost_breakdown_comparison,
    )
    from src.util.visualizers.wait_time_comparison import (
        plot_wait_time_comparison_boxplot,
    )

    console.print()
    console.rule("[bold cyan]シナリオ間比較可視化[/bold cyan]", style="cyan")
    console.print()

    # ディレクトリ一覧表示
    table = Table(title="比較対象ディレクトリ", box=box.ROUNDED)
    table.add_column("No.", style="dim")
    table.add_column("ディレクトリ", style="cyan")
    for i, d in enumerate(result_dirs, 1):
        table.add_row(str(i), str(d.name))
    console.print(table)
    console.print()

    # 出力ディレクトリ作成
    output_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"[cyan]📁 出力先: {output_dir}[/cyan]")
    console.print()

    # 結果収集
    console.print("[yellow]📊 結果を収集中...[/yellow]")
    comparator = ScenarioComparator(result_dirs)
    comparator.collect_all_results()

    n_p_values = len(comparator.p_value_results)
    n_total_scenarios = sum(
        1 + len(pv.failure_results)
        for pv in comparator.p_value_results
        if pv.normal_result
    )
    console.print(f"[green]✅ {n_p_values}個のP値、計{n_total_scenarios}シナリオを収集[/green]")
    console.print()

    # コスト比較
    console.print("[yellow]📈 コスト比較を生成中...[/yellow]")
    plot_cost_comparison_boxplot(comparator, output_dir, save_png, save_html)
    plot_cost_breakdown_comparison(comparator, output_dir)

    # 待ち時間比較
    console.print("[yellow]⏱️ 待ち時間比較を生成中...[/yellow]")
    plot_wait_time_comparison_boxplot(comparator, output_dir, save_png, save_html)

    console.print()
    console.print(Panel("[bold green]✨ シナリオ比較完了 ✨[/bold green]", border_style="green"))
    console.print()

    # 投資対効果比較
    console.print("[yellow]📊 投資対効果比較を生成中...[/yellow]")
    plot_pareto_from_scenarios(result_dirs, output_dir)
    console.print()
    console.print(Panel("[bold green]✨ 投資対効果比較完了 ✨[/bold green]", border_style="green"))
    console.print()

    # CSVエクスポート（P値ごとのサマリー）
    console.print("[yellow]📄 サマリーCSVを出力中...[/yellow]")
    csv_path = output_dir / "scenario_summary.csv"
    comparator.export_summary_csv(csv_path)
    console.print(f"[green]✅ サマリーCSVを保存: {csv_path}[/green]")
    console.print()

def main():
    """コマンドラインエントリポイント（サブコマンド対応）"""
    parser = argparse.ArgumentParser(
        description="最適化結果可視化ツール",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # 単体可視化（プラグインモード）
  uv run python -m src.util.visualize_results single -d "Z:\\output\\unified_P50"

  # 単体可視化（レガシーモード）
  uv run python -m src.util.visualize_results single -d "Z:\\output\\unified_P50" --legacy

  # シナリオ比較（複数ディレクトリ指定）
  uv run python -m src.util.visualize_results compare -d "Z:\\output\\unified_P00" -d "Z:\\output\\unified_P50" -o "Z:\\output\\comparison"

  # シナリオ比較（パターンマッチ）
  uv run python -m src.util.visualize_results compare --pattern "Z:\\output\\unified_P*" -o "Z:\\output\\comparison"
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="サブコマンド")

    # --- single サブコマンド（単体可視化） ---
    single_parser = subparsers.add_parser(
        "single",
        help="単一ディレクトリの可視化",
        aliases=["s"],
    )
    single_parser.add_argument(
        "--result-dir", "-d",
        type=str,
        required=True,
        help="結果ディレクトリのパス"
    )
    single_parser.add_argument(
        "--study-name", "-s",
        type=str,
        default=None,
        help="Optuna Study名（省略時は自動推測）"
    )
    single_parser.add_argument(
        "--result-file", "-f",
        type=str,
        default=None,
        help="対象の結果pklファイル（省略時は最適トライアルの結果）"
    )
    single_parser.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="可視化設定ファイルパス（省略時はデフォルト）"
    )
    single_parser.add_argument(
        "--legacy",
        action="store_true",
        help="レガシーモード（プラグインを使用しない）"
    )

    # --- compare サブコマンド（シナリオ比較） ---
    compare_parser = subparsers.add_parser(
        "compare",
        help="複数シナリオの比較可視化",
        aliases=["c"],
    )
    compare_parser.add_argument(
        "--result-dir", "-d",
        type=str,
        action="append",
        dest="result_dirs",
        help="比較対象ディレクトリ（複数指定可）"
    )
    compare_parser.add_argument(
        "--pattern", "-p",
        type=str,
        default=None,
        help="ディレクトリ検索パターン（例: Z:\\output\\unified_P*）"
    )
    compare_parser.add_argument(
        "--output", "-o",
        type=str,
        required=True,
        help="出力先ディレクトリ"
    )
    compare_parser.add_argument(
        "--no-png",
        action="store_true",
        help="PNG出力を無効化"
    )
    compare_parser.add_argument(
        "--no-html",
        action="store_true",
        help="HTML出力を無効化"
    )

    args = parser.parse_args()

    # サブコマンドが指定されていない場合（後方互換性のため-dオプションをチェック）
    if args.command is None:
        # 古い形式のCLI引数をパース（後方互換）
        if len(sys.argv) > 1 and sys.argv[1].startswith('-'):
            # 旧形式（-d で始まる）をsingleコマンドとして処理
            args = single_parser.parse_args()
            args.command = "single"
        else:
            parser.print_help()
            return

    if args.command in ("single", "s"):
        # 単体可視化
        result_dir = Path(args.result_dir)
        result_file = Path(args.result_file) if args.result_file else None
        config_path = Path(args.config) if args.config else None

        if args.legacy:
            # レガシーモード（従来の方式）
            generate_results_report(
                result_dir=result_dir,
                study_name=args.study_name,
                result_file=result_file,
            )
        else:
            # プラグインモード（新方式）
            console.print()
            console.rule("[bold cyan]最適化結果可視化（プラグインモード）[/bold cyan]", style="cyan")
            console.print()
            console.print(Panel(f"📁 対象ディレクトリ: {result_dir}", border_style="cyan"))

            # Study読み込み
            study = None
            db_path = result_dir / "optuna_study_unified.db"
            study_name = args.study_name
            best_trial_number = None

            if db_path.exists():
                if study_name is None:
                    try:
                        storage = optuna.storages.RDBStorage(url=f"sqlite:///{db_path}")
                        study_summaries = storage.get_all_studies()
                        if study_summaries:
                            study_name = study_summaries[0].study_name
                    except Exception:
                        pass

                try:
                    study = optuna.load_study(study_name=study_name, storage=f"sqlite:///{db_path}")
                    best_trial_number = study.best_trial.number
                    console.print(f"[green]🏆 最適トライアル: #{best_trial_number} (コスト: {study.best_value:.2f}万円)[/green]")
                except Exception as e:
                    console.print(f"[yellow]⚠️ Study読み込みエラー: {e}[/yellow]")

            # 結果ファイル選択
            if result_file is None:
                pkl_files = list(result_dir.glob("*.pkl"))

                if pkl_files:
                    if best_trial_number is not None:
                        best_pattern = f"trial_{best_trial_number}_"
                        best_files = [f for f in pkl_files if best_pattern in f.name and "_normal" in f.name]
                        if not best_files:
                            best_files = [f for f in pkl_files if best_pattern in f.name]

                        for candidate in best_files:
                            try:
                                with open(candidate, 'rb') as f:
                                    pickle.load(f)
                                result_file = candidate
                                console.print(f"[green]✅ 最適トライアルのファイルを使用[/green]")
                                break
                            except Exception:
                                continue

                    if result_file is None:
                        normal_files = [f for f in pkl_files if "_normal.pkl" in f.name]
                        if normal_files:
                            pkl_files = normal_files
                        pkl_files = sorted(pkl_files, key=lambda f: f.stat().st_size, reverse=True)

                        for candidate in pkl_files:
                            try:
                                with open(candidate, 'rb') as f:
                                    pickle.load(f)
                                result_file = candidate
                                break
                            except Exception:
                                continue

            if result_file:
                console.print(f"[cyan]📄 対象ファイル: {result_file.name}[/cyan]")

            # プラグイン実行
            run_visualizers_from_config(
                result_dir=result_dir,
                result_file=result_file,
                study=study,
                config_path=config_path,
            )

            console.print()
            console.print(Panel("[bold green]✨ 全可視化完了 ✨[/bold green]", border_style="green"))
            console.print()

    elif args.command in ("compare", "c"):
        # シナリオ比較
        from src.util.scenario_compare import find_result_dirs_by_pattern

        result_dirs = []

        # --pattern オプション
        if args.pattern:
            result_dirs.extend(find_result_dirs_by_pattern(args.pattern))

        # -d オプション（複数指定）
        if args.result_dirs:
            for d in args.result_dirs:
                p = Path(d)
                if p.is_dir():
                    result_dirs.append(p)

        if not result_dirs:
            console.print("[red]❌ 比較対象ディレクトリが見つかりません[/red]")
            return

        # 重複除去・ソート
        result_dirs = sorted(set(result_dirs), key=lambda d: d.name)

        compare_scenarios(
            result_dirs=result_dirs,
            output_dir=Path(args.output),
            save_png=not args.no_png,
            save_html=not args.no_html,
        )


def plot_pareto_curve_cost_vs_wait(
    p_values: list[int] = None,
    costs: list[float] = None,
    wait_times: list[float] = None,
    save_path: Optional[Path] = None,
    title: str = "コスト vs 待ち時間 パレートフロンティア",
    show_plot: bool = True,
) -> None:
    """コストと待ち時間のトレードオフをパレート曲線として可視化

    EV充電インフラのシミュレーション結果から、故障重みパラメータ(P値)ごとの
    設置コストと平均待ち時間の関係を散布図＋折れ線で表示する。
    費用対効果の良い「エルボーポイント」を視覚的に判断できる。

    Args:
        p_values: 故障重みパラメータのリスト（例: [0, 20, 40, 60, 80, 100]）
        costs: 設置コストのリスト（万円）
        wait_times: 平均待ち時間のリスト（分）
        save_path: 保存先パス（Noneの場合は保存しない）
        title: グラフタイトル
        show_plot: プロットを表示するかどうか

    Example:
        >>> plot_pareto_curve_cost_vs_wait()  # ダミーデータで実行
        >>> plot_pareto_curve_cost_vs_wait(
        ...     p_values=[0, 50, 100],
        ...     costs=[8000, 12000, 15000],
        ...     wait_times=[12.0, 7.5, 5.0],
        ...     save_path=Path("pareto_curve.png")
        ... )
    """
    # ダミーデータ（引数が指定されない場合）
    if p_values is None:
        p_values = [0, 20, 40, 60, 80, 100]
    if costs is None:
        # Pが増えるほど基本的に増加するが、一部ノイズを含む
        costs = [8000, 11000, 14500, 16000, 11500, 14000]
    if wait_times is None:
        # Pが増えるほど基本的に減少するが、一部ノイズを含む
        wait_times = [10.5, 9.0, 8.5, 9.2, 6.0, 5.5]

    # データ検証
    if not (len(p_values) == len(costs) == len(wait_times)):
        console.print("[red]❌ データの長さが一致しません[/red]")
        return

    # プロット設定
    fig, ax = plt.subplots(figsize=(10, 7))

    # 散布図 + 折れ線（P値の順序でプロット）
    # コストでソートして折れ線を引く（パレートフロンティアらしく見せる）
    sorted_indices = np.argsort(costs)
    sorted_costs = [costs[i] for i in sorted_indices]
    sorted_wait_times = [wait_times[i] for i in sorted_indices]
    sorted_p_values = [p_values[i] for i in sorted_indices]

    # 折れ線（パレートフロンティア風）
    ax.plot(
        sorted_costs, sorted_wait_times,
        'o-',
        color='#2196F3',
        linewidth=2,
        markersize=12,
        markerfacecolor='#1565C0',
        markeredgecolor='white',
        markeredgewidth=2,
        label='シミュレーション結果',
        zorder=3,
    )

    # 各点にP値のアノテーションを追加
    for i, (cost, wait, p) in enumerate(zip(sorted_costs, sorted_wait_times, sorted_p_values)):
        # 外れ値（コストが高いのに待ち時間が減っていない）を検出
        is_outlier = False
        if i > 0:
            prev_cost, prev_wait = sorted_costs[i - 1], sorted_wait_times[i - 1]
            # コストが増えているのに待ち時間も増えている場合
            if cost > prev_cost and wait > prev_wait:
                is_outlier = True

        # アノテーションのスタイル
        bbox_color = '#FFCDD2' if is_outlier else '#E3F2FD'
        text_color = '#C62828' if is_outlier else '#1565C0'

        ax.annotate(
            f'P={p}%',
            (cost, wait),
            xytext=(8, 12),
            textcoords='offset points',
            fontsize=10,
            fontweight='bold',
            color=text_color,
            bbox=dict(
                boxstyle='round,pad=0.3',
                facecolor=bbox_color,
                edgecolor=text_color,
                alpha=0.9,
            ),
            zorder=4,
        )

    # 理想的なトレードオフ領域を示す矢印（参考）
    ax.annotate(
        '',
        xy=(min(costs) * 0.95, min(wait_times) * 0.95),
        xytext=(max(costs) * 0.9, max(wait_times) * 0.9),
        arrowprops=dict(
            arrowstyle='->',
            color='gray',
            lw=1.5,
            ls='--',
            alpha=0.5,
        ),
    )
    ax.text(
        (min(costs) + max(costs)) / 2 * 0.85,
        (min(wait_times) + max(wait_times)) / 2 * 0.85,
        '理想的な改善方向',
        fontsize=9,
        color='gray',
        alpha=0.7,
        style='italic',
    )

    # 軸ラベル・タイトル
    ax.set_xlabel('総設置コスト（万円）', fontsize=12, fontweight='bold')
    ax.set_ylabel('平均待ち時間（分）', fontsize=12, fontweight='bold')
    ax.set_title(title, fontsize=14, fontweight='bold', pad=15)

    # グリッド
    ax.grid(True, alpha=0.4, linestyle='-', linewidth=0.5)
    ax.set_axisbelow(True)

    # 凡例
    ax.legend(loc='upper right', fontsize=10)

    # 軸範囲の調整（余白を持たせる）
    x_margin = (max(costs) - min(costs)) * 0.15
    y_margin = (max(wait_times) - min(wait_times)) * 0.15
    ax.set_xlim(min(costs) - x_margin, max(costs) + x_margin)
    ax.set_ylim(min(wait_times) - y_margin, max(wait_times) + y_margin)

    plt.tight_layout()

    # 保存
    if save_path is not None:
        save_path = Path(save_path)
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        console.print(f"[green]✅ パレート曲線を保存: {save_path}[/green]")

    # 表示
    if show_plot:
        plt.show()
    else:
        plt.close()


def demo_pareto_curve():
    """パレート曲線のデモ実行（ダミーデータ使用）"""
    console.print()
    console.rule("[bold cyan]パレート曲線デモ[/bold cyan]", style="cyan")
    console.print()

    # ダミーデータの説明
    console.print("[yellow]📊 ダミーデータでパレート曲線を生成します[/yellow]")
    console.print()

    table = Table(title="ダミーデータ", box=box.ROUNDED)
    table.add_column("P値 (%)", style="cyan", justify="center")
    table.add_column("設置コスト (万円)", style="green", justify="right")
    table.add_column("平均待ち時間 (分)", style="magenta", justify="right")

    p_values = [0, 20, 40, 60, 80, 100]
    costs = [8000, 11000, 14500, 16000, 11500, 14000]
    wait_times = [10.5, 9.0, 8.5, 9.2, 6.0, 5.5]

    for p, c, w in zip(p_values, costs, wait_times):
        table.add_row(str(p), f"{c:,}", f"{w:.1f}")

    console.print(table)
    console.print()

    # プロット生成
    plot_pareto_curve_cost_vs_wait(
        p_values=p_values,
        costs=costs,
        wait_times=wait_times,
        title="EV充電インフラ コスト vs 待ち時間 トレードオフ分析",
    )


def plot_pareto_from_scenarios(
    result_dirs: list[Path],
    save_path: Optional[Path] = None,
    title: str = "投資コスト vs 平均待ち時間 トレードオフ",
    show_plot: bool = True,
) -> None:
    """複数のP値ディレクトリから実データを取得してパレート曲線を描画

    Args:
        result_dirs: P値ごとの結果ディレクトリのリスト（例: [Path("unified_P00"), ...]）
        save_path: 保存先パス（Noneの場合は保存しない）
        title: グラフタイトル
        show_plot: プロットを表示するかどうか

    Example:
        >>> from pathlib import Path
        >>> import glob
        >>> dirs = [Path(d) for d in glob.glob("Z:/output/unified_P*")]
        >>> plot_pareto_from_scenarios(dirs, save_path=Path("pareto_real.png"))
    """
    from src.util.scenario_compare import ScenarioComparator

    if not result_dirs:
        console.print("[red]❌ 結果ディレクトリが指定されていません[/red]")
        return

    console.print()
    console.rule("[bold cyan]パレート曲線（実データ）[/bold cyan]", style="cyan")
    console.print()

    # 結果収集
    console.print(f"[yellow]📊 {len(result_dirs)}個のディレクトリから結果を収集中...[/yellow]")
    comparator = ScenarioComparator(result_dirs)
    comparator.collect_all_results()

    if not comparator.p_value_results:
        console.print("[red]❌ 有効な結果が見つかりませんでした[/red]")
        return

    # P値・投資コスト・平均待ち時間を抽出
    p_values = []
    initial_costs = []
    mean_wait_times = []

    for pv_result in comparator.p_value_results:
        # normalシナリオの結果を使用
        if pv_result.normal_result:
            p_percent = int(pv_result.p_value * 100)
            p_values.append(p_percent)
            initial_costs.append(pv_result.normal_result.initial_cost)
            # 秒から分に変換
            mean_wait_times.append(pv_result.normal_result.mean_wait_time / 60)

    if not p_values:
        console.print("[red]❌ normalシナリオの結果が見つかりませんでした[/red]")
        return

    # データ表示
    table = Table(title="収集データ", box=box.ROUNDED)
    table.add_column("P値 (%)", style="cyan", justify="center")
    table.add_column("投資コスト (万円)", style="green", justify="right")
    table.add_column("平均待ち時間 (分)", style="magenta", justify="right")

    for p, c, w in zip(p_values, initial_costs, mean_wait_times):
        table.add_row(str(p), f"{c:,.0f}", f"{w:.2f}")

    console.print(table)
    console.print()

    # パレート曲線描画
    plot_pareto_curve_cost_vs_wait(
        p_values=p_values,
        costs=initial_costs,
        wait_times=mean_wait_times,
        save_path=save_path,
        title=title,
        show_plot=show_plot,
    )


def run_pareto_from_pattern(pattern: str, output_path: Optional[str] = None, show: bool = True) -> None:
    """パターンマッチでディレクトリを検索してパレート曲線を描画（CLIヘルパー）

    Args:
        pattern: globパターン（例: "Z:/output/unified_P*"）
        output_path: 出力パス（Noneで保存しない）
        show: プロットを表示するか
    """
    import glob

    matched_dirs = [Path(d) for d in glob.glob(pattern) if Path(d).is_dir()]

    if not matched_dirs:
        console.print(f"[red]❌ パターン '{pattern}' にマッチするディレクトリがありません[/red]")
        return

    console.print(f"[green]✅ {len(matched_dirs)}個のディレクトリが見つかりました[/green]")
    for d in sorted(matched_dirs):
        console.print(f"  - {d.name}")

    save_path = Path(output_path) if output_path else None
    plot_pareto_from_scenarios(
        result_dirs=matched_dirs,
        save_path=save_path,
        show_plot=show,
    )


if __name__ == "__main__":
    main()


