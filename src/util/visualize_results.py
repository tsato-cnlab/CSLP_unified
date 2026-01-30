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
import warnings
import logging

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import optuna
import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

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

# Linux環境の場合
if sys.platform == 'linux':
    matplotlib.rcParams['font.family'] = ['sans-serif']
    matplotlib.rcParams['font.sans-serif'] = ['DejaVu Sans']

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
        colors_discrete = plt.cm.viridis(np.linspace(0.2, 0.8, len(unique_kw)))
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
    result_file: Path,
    study: optuna.Study = None,
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


def generate_extended_report(
    result_dir: Path,
    study_name: Optional[str] = None,
    config=None,
) -> None:
    """平常時・故障時（ワーストケース）両方の可視化を実行

    Args:
        result_dir: 結果ディレクトリのパス
        study_name: Optuna Study名（指定しない場合は推測）
        config: UnifiedOptimizationConfig（P値判定に使用）
    """
    result_dir = Path(result_dir)

    if not result_dir.exists():
        console.print(f"[red]❌ ディレクトリが存在しません: {result_dir}[/red]")
        return

    console.print()
    console.rule("[bold cyan]拡張可視化レポート生成[/bold cyan]", style="cyan")
    console.print()
    console.print(Panel(f"📁 対象ディレクトリ: {result_dir}", border_style="cyan"))

    # P値を取得
    failure_weight = 0.0
    if config is not None:
        failure_weight = getattr(config, 'failure_weight', 0.0)
    console.print(f"[cyan]📊 failure_weight (P): {failure_weight}[/cyan]")

    # データベースを探す
    db_path = result_dir / "optuna_study_unified.db"
    study = None
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
    else:
        console.print("[yellow]⚠️ Optunaデータベースが見つかりません[/yellow]")

    # 結果pklファイルを探す
    pkl_files = list(result_dir.glob("*.pkl"))
    if not pkl_files:
        console.print("[red]❌ 結果pklファイルが見つかりません[/red]")
        return

    # 平常時ファイルを特定
    normal_file = None
    failure_file = None

    if best_trial_number is not None:
        best_pattern = f"trial_{best_trial_number}_"

        # 平常時ファイル
        normal_candidates = [f for f in pkl_files if best_pattern in f.name and "_normal" in f.name]
        for candidate in normal_candidates:
            try:
                with open(candidate, 'rb') as f:
                    pickle.load(f)
                normal_file = candidate
                break
            except Exception:
                continue

        # 故障時ファイル（P>0の場合は既に存在するはず）
        failure_candidates = [f for f in pkl_files if best_pattern in f.name and "_failure_" in f.name]
        for candidate in failure_candidates:
            try:
                with open(candidate, 'rb') as f:
                    pickle.load(f)
                failure_file = candidate
                break
            except Exception:
                continue

    # フォールバック: normalファイル
    if normal_file is None:
        normal_candidates = [f for f in pkl_files if "_normal" in f.name]
        normal_candidates = sorted(normal_candidates, key=lambda f: f.stat().st_mtime, reverse=True)
        for candidate in normal_candidates:
            try:
                with open(candidate, 'rb') as f:
                    pickle.load(f)
                normal_file = candidate
                break
            except Exception:
                continue

    if normal_file is None:
        console.print("[red]❌ 平常時結果ファイルが見つかりません[/red]")
        return

    console.print(f"[cyan]📄 平常時ファイル: {normal_file.name}[/cyan]")

    # P=0で故障ファイルがない場合、故障シナリオを実行
    if failure_weight == 0.0 and failure_file is None:
        console.print("[yellow]📊 P=0のため故障シナリオを追加実行します...[/yellow]")
        failure_file = _run_failure_simulation_for_visualization(
            normal_file, result_dir, config
        )

    if failure_file is not None:
        console.print(f"[cyan]📄 故障時ファイル: {failure_file.name}[/cyan]")
    else:
        console.print("[yellow]⚠️ 故障時ファイルが見つかりません（スキップ）[/yellow]")

    # サブディレクトリ作成
    normal_dir = result_dir / "normal"
    failure_dir = result_dir / "failure"
    normal_dir.mkdir(parents=True, exist_ok=True)
    failure_dir.mkdir(parents=True, exist_ok=True)

    # 平常時可視化
    console.print()
    console.rule("[bold green]平常時 可視化[/bold green]", style="green")
    run_visualizers_from_config(
        result_dir=normal_dir,
        result_file=normal_file,
        study=study,
    )

    # 故障時可視化
    if failure_file is not None:
        console.print()
        console.rule("[bold red]故障時（ワーストケース）可視化[/bold red]", style="red")
        run_visualizers_from_config(
            result_dir=failure_dir,
            result_file=failure_file,
            study=study,
        )

    # 最適化履歴はトップレベルに出力
    if db_path.exists() and study_name:
        plot_optimization_history(
            db_path, study_name,
            result_dir / "optimization_history.png"
        )

    console.print()
    console.print(Panel("[bold green]✨ 拡張可視化完了 ✨[/bold green]", border_style="green"))
    console.print(f"  📁 平常時: {normal_dir}")
    console.print(f"  📁 故障時: {failure_dir}")
    console.print()


def _run_failure_simulation_for_visualization(
    normal_file: Path,
    result_dir: Path,
    config,
) -> Optional[Path]:
    """P=0の場合に故障シナリオを実行してワーストケースファイルを返す

    Args:
        normal_file: 平常時結果ファイル
        result_dir: 結果ディレクトリ
        config: UnifiedOptimizationConfig

    Returns:
        ワーストケースのpklファイルパス（失敗時はNone）
    """
    try:
        # 平常時結果からcs_configを取得
        with open(normal_file, 'rb') as f:
            emates_result = pickle.load(f)
        cs_config = emates_result.cs_config

        # 設置済みCSを特定
        installed_cs_indices = [
            i for i, ports in enumerate(cs_config.get('ports', []))
            if ports > 0
        ]

        if len(installed_cs_indices) == 0:
            console.print("[yellow]⚠️ 設置CSがありません[/yellow]")
            return None

        console.print(f"[cyan]🔥 故障シナリオ実行中... (CS数: {len(installed_cs_indices)})[/cyan]")

        # 故障シナリオ実行用のインポート
        from src.simulation.create_emates_env import prepare_parallel_environment
        from src.util.file_manager import cleanup_worker_environments
        from src.util.optimization import create_failure_info_for_worker, update_cs_list
        from src.util.path_manager import get_paths
        from src.simulation.run_emates import only_run_emates
        from src.simulation.data_load import save_data_to_pickle

        # Worker環境準備
        prepare_parallel_environment(cs_config, parallel_count=1, batch_size=8)

        results = []
        worker_start = 1

        for i, failure_cs_idx in enumerate(installed_cs_indices):
            worker_id = worker_start + (i % 8)
            console.print(f"  [dim]故障CS {failure_cs_idx} をシミュレーション中 (Worker {worker_id})...[/dim]")

            try:
                # Workerパスを取得
                worker_paths = get_paths(worker_id)

                # 故障情報作成
                from threading import Lock
                file_write_lock = Lock()
                failure_time = getattr(config, 'failure_time', 36000) if config else 36000
                create_failure_info_for_worker(
                    cs_config, failure_cs_idx, worker_id,
                    FAILURE_TIME=failure_time,
                    file_write_lock=file_write_lock
                )

                # CS設定書き込み
                csList_file = worker_paths["csList"]
                update_cs_list(cs_config, csList_file)

                # シミュレーション実行
                t_hour = getattr(config, 't_hour', 24) if config else 24
                only_run_emates(worker_id=worker_id, HOUR=t_hour)

                # 結果保存
                scenario_suffix = f"failure_{failure_cs_idx}"
                results_filename = f"viz_{scenario_suffix}.pkl"
                results_filepath = result_dir / results_filename

                save_data_to_pickle(filename=str(results_filepath), worker_id=worker_id)

                # コスト評価
                evaluation_cost, _ = evaluation_total_costs(result_file=str(results_filepath))

                results.append({
                    'failure_cs_idx': failure_cs_idx,
                    'cost': evaluation_cost,
                    'filepath': results_filepath,
                })

                console.print(f"  [dim]  → コスト: {evaluation_cost:.2f}万円[/dim]")

            except Exception as e:
                console.print(f"  [yellow]⚠️ 故障CS {failure_cs_idx} でエラー: {e}[/yellow]")
                continue

        # クリーンアップ
        cleanup_worker_environments()

        if not results:
            console.print("[yellow]⚠️ 有効な故障シナリオ結果がありません[/yellow]")
            return None

        # ワーストケース（最大コスト）を特定
        worst_result = max(results, key=lambda x: x['cost'])
        worst_file = worst_result['filepath']
        console.print(f"[green]📊 ワーストケース: 故障CS {worst_result['failure_cs_idx']} "
                     f"(コスト: {worst_result['cost']:.2f}万円)[/green]")

        # ワーストケース以外を削除（無効化：全故障シナリオを保持）
        # for result in results:
        #     if result['filepath'] != worst_file:
        #         try:
        #             result['filepath'].unlink()
        #         except Exception:
        #             pass

        return worst_file

    except Exception as e:
        console.print(f"[red]❌ 故障シナリオ実行エラー: {e}[/red]")
        import traceback
        traceback.print_exc()
        return None


def main():
    """コマンドラインエントリポイント"""
    parser = argparse.ArgumentParser(
        description="最適化結果可視化ツール",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # 基本的な使い方（平常時のみ可視化）
  uv run src/util/visualize_results.py -d results/exp1

  # 拡張可視化（平常時+故障時両方）
  uv run src/util/visualize_results.py -d results/exp1 --extended

  # 拡張可視化（P=0で故障シナリオを追加実行する場合）
  uv run src/util/visualize_results.py -d results/exp1 --extended --optim-config config.json

  # レガシーモード（プラグインを使用しない従来方式）
  uv run src/util/visualize_results.py -d results/exp1 --legacy
"""
    )
    parser.add_argument(
        "--result-dir", "-d",
        type=str,
        required=True,
        help="結果ディレクトリのパス（必須）"
    )
    parser.add_argument(
        "--study-name", "-s",
        type=str,
        default=None,
        help="Optuna Study名（省略時はDBから自動推測）"
    )
    parser.add_argument(
        "--result-file", "-f",
        type=str,
        default=None,
        help="対象の結果pklファイル（省略時は最適トライアルの結果を自動選択）"
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="可視化設定ファイルパス（省略時は visualization_config.yaml）"
    )
    parser.add_argument(
        "--extended", "-e",
        action="store_true",
        help="拡張可視化モード: 平常時と故障時（ワーストケース）の両方を可視化。"
             "出力は normal/ と failure/ サブディレクトリに保存される"
    )
    parser.add_argument(
        "--optim-config",
        type=str,
        default=None,
        help="最適化設定JSONファイルのパス（--extended使用時、P=0で故障シナリオを"
             "追加実行する場合に必要）"
    )
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="レガシーモード: プラグインを使用しない従来の可視化方式"
    )

    args = parser.parse_args()

    # 結果ディレクトリを取得
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
    elif args.extended:
        # 拡張可視化モード（平常時+故障時両方）
        optim_config = None
        if args.optim_config:
            try:
                from src.config.unified_optimization_config import UnifiedOptimizationConfig
                optim_config = UnifiedOptimizationConfig.from_json(Path(args.optim_config))
                console.print(f"[cyan]📋 最適化設定読み込み: {args.optim_config}[/cyan]")
            except Exception as e:
                console.print(f"[yellow]⚠️ 最適化設定読み込みエラー: {e}[/yellow]")
                console.print("[dim]  故障シナリオの追加実行はスキップされます[/dim]")

        generate_extended_report(
            result_dir=result_dir,
            study_name=args.study_name,
            config=optim_config,
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


if __name__ == "__main__":
    main()


