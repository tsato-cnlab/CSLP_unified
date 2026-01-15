#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""統合最適化メインスクリプト（GUI設定対応版）

このスクリプトは平常時と故障時を統合した最適化を実行します。
目的関数: F = objective_function(normal_cost, failure_cost, P)

使用方法:
    python cs_optim_unified.py --config unified_config.json
"""

import concurrent.futures
import os
import sys
import time
from datetime import datetime
from multiprocessing import Lock, Pool
from pathlib import Path
from typing import Optional
import argparse
import json

import optuna

# 設定読み込み
from src.config.unified_optimization_config import UnifiedOptimizationConfig

# シミュレーション関連
from src.simulation.create_emates_env import prepare_parallel_environment
from src.simulation.data_load import save_data_to_pickle
from src.simulation.run_emates import only_run_emates

# ユーティリティ関連
from src.util.convergence_checker import check_convergence
from src.util.cost_calculator import (
    calculate_95percentile_wait_time,
    evaluation_total_costs,
)
from src.util.file_manager import (
    cleanup_worker_environments,
    manage_pkl_files_after_optimization,
)
from src.util.optimization import (
    check_cs_placement,
    create_failure_info_for_worker,
    set_cs_placement,
    update_cs_list,
)
from src.util.path_manager import get_paths

# ファイル書き込み用ロック
file_write_lock = Lock()

# グローバル変数（multiprocessing用）
CONFIG: Optional[UnifiedOptimizationConfig] = None


def get_initial_cs_params(config: UnifiedOptimizationConfig) -> list[dict]:
    """初期パラメータセットを生成（CSVから読み込み）

    Args:
        config: 最適化設定（initial_cs_config_fileを含む）

    Returns:
        list[dict]: 初期パラメータのリスト（各要素はOptunaパラメータ辞書）
                   例: [{'ports_0': 1, 'capacity_0': 100, ...}, ...]
    """
    # csList.txtから利用可能なCS情報を取得
    paths = get_paths()
    cslist_file = paths['csList']

    try:
        with open(cslist_file, 'r') as f:
            cslist_data = f.readlines()
        cslist_data = [line.strip() for line in cslist_data if line.strip()]
        csids = [int(line.split(',')[0]) for line in cslist_data]
    except Exception as e:
        print(f"⚠️ csList読み込みエラー: {e}")
        return []

    initial_configs = []

    if not config.initial_cs_config_file:
        print("⚠️ 初期配置ファイルが設定されていません（initial_cs_config_file）")
        return []

    print(f"📋 CSVファイルから初期配置を読み込み: {config.initial_cs_config_file}")
    try:
        import pandas as pd
        df = pd.read_csv(config.initial_cs_config_file)

        # CSVフォーマット: config_name, csid, capacity_kw, ports
        # 同一のconfig_nameは同じcs_configとしてグループ化
        grouped = df.groupby('config_name')

        for config_name, group in grouped:
            # Optunaパラメータ形式の辞書を作成（インデックスベース）
            params = {}

            # 全CSを0で初期化（ports_{i}形式）
            for i in range(len(csids)):
                params[f'ports_{i}'] = 0

            # CSVの各行からCS設定を読み込み
            for _, row in group.iterrows():
                csid = int(row['csid'])
                if csid in csids:
                    idx = csids.index(csid)
                    params[f'ports_{idx}'] = int(row['ports'])
                    params[f'capacity_{idx}'] = int(row['capacity_kw'])

            initial_configs.append(params)
            active_count = sum(1 for i in range(len(csids)) if params.get(f'ports_{i}', 0) > 0)
            print(f"  - {config_name}: {active_count}箇所にCS配置")

        print(f"✅ {len(initial_configs)}個の初期配置を読み込みました")

    except Exception as e:
        print(f"❌ CSV読み込みエラー: {e}")
        import traceback
        traceback.print_exc()
        return []

    return initial_configs


def run_single_failure_scenario(task_data):
    """単一シナリオを実行（平常時・故障時共通、multiprocessing用）

    Args:
        task_data: (cs_config, failure_cs_idx, trial_number, worker_id, save_dir, combination_id, config)
                  failure_cs_idx=Noneの場合は平常時、それ以外は故障時
                  config: UnifiedOptimizationConfig 設定オブジェクト

    Returns:
        dict: 実行結果
    """
    cs_config, failure_cs_idx, trial_number, worker_id, save_dir, combination_id, config = task_data
    scenario_type = "正常ケース" if failure_cs_idx is None else f"故障CS{failure_cs_idx}"
    print(f"🚀 Worker{worker_id}: {scenario_type} 開始")

    try:
        # 制約チェック
        if not check_cs_placement(cs_config):
            print(f"❌ Worker{worker_id}: {scenario_type} 制約違反")
            return {
                'failure_cs_idx': failure_cs_idx,
                'combination_id': combination_id,
                'worker_id': worker_id,
                'cost': float('inf'),
                'error': 'constraint_violation'
            }

        # resultディレクトリ構造を確実に作成
        worker_paths = get_paths(worker_id)
        result_dir = worker_paths["result"]
        os.makedirs(result_dir, exist_ok=True)
        os.makedirs(os.path.join(result_dir, "emates"), exist_ok=True)
        os.makedirs(os.path.join(result_dir, "inst"), exist_ok=True)
        os.makedirs(os.path.join(result_dir, "opendss"), exist_ok=True)

        # 故障情報作成（平常時はfailure_cs_idx=None、故障時は具体的なインデックス）
        create_failure_info_for_worker(
            cs_config, failure_cs_idx, worker_id,
            FAILURE_TIME=config.failure_time,
            file_write_lock=file_write_lock
        )
        print(f"✅ Worker{worker_id}: 故障情報作成完了")

        # CS設定書き込み
        csList_file = worker_paths["csList"]
        update_cs_list(cs_config, csList_file)

        # シミュレーション実行
        only_run_emates(worker_id=worker_id, HOUR=config.t_hour)

        scenario_suffix = "normal" if failure_cs_idx is None else f"failure_{failure_cs_idx}"
        results_filename = f"trial_{trial_number}_combo_{combination_id}_{scenario_suffix}.pkl"
        results_filepath = os.path.join(save_dir, results_filename)

        # 保存先ディレクトリの確認と作成
        os.makedirs(os.path.dirname(results_filepath), exist_ok=True)

        save_data_to_pickle(filename=results_filepath, worker_id=worker_id)

        evaluation_cost, _ = evaluation_total_costs(result_file=results_filepath)
        wait_time_95p = calculate_95percentile_wait_time(results_filepath)

        print(f"✅ Worker{worker_id}: 故障CS{failure_cs_idx} 完了, コスト={evaluation_cost:.2f}万円")

        return {
            'failure_cs_idx': failure_cs_idx,
            'combination_id': combination_id,
            'worker_id': worker_id,
            'cost': evaluation_cost,
            'wait_time_95p': wait_time_95p,
            'results_filepath': results_filepath,
            'cs_config': cs_config.copy()
        }

    except Exception as e:
        import traceback
        print(f"💥 Worker{worker_id}: 故障CS{failure_cs_idx} エラー: {e}")
        print(f"📋 トレースバック:\n{traceback.format_exc()}")
        return {
            'failure_cs_idx': failure_cs_idx,
            'combination_id': combination_id,
            'worker_id': worker_id,
            'cost': float('inf'),
            'error': str(e)
        }


def create_failure_scenario_parallel_safe(cs_config_dict, trial_number, combination_id, config):
    """全故障シナリオを並列実行

    Args:
        cs_config_dict: CS設定辞書
        trial_number: トライアル番号
        combination_id: 組み合わせID
        config: UnifiedOptimizationConfig 設定オブジェクト

    Returns:
        dict: 最悪ケースの結果
    """
    installed_cs_indices = [i for i, ports in enumerate(cs_config_dict['ports']) if ports > 0]

    if len(installed_cs_indices) == 0:
        return {
            'trial_number': trial_number,
            'worst_cost': float('inf'),
            'worst_details': {},
            'all_results': []
        }

    print(f"\n=== Trial {trial_number} (組み合わせ{combination_id}): 故障シナリオ並列処理開始 ===")
    print(f"設置CS数: {len(installed_cs_indices)}, 故障シナリオ数: {len(installed_cs_indices)}")

    # Worker割り当て: 平常時用に1個シフト（combination_id * 9 + 2 から開始）
    worker_start = combination_id * 9 + 2
    print(f"Worker割り当て（故障時）: {worker_start}-{worker_start + 7}")

    # タスクデータ準備
    task_data_list = []
    for i, failure_cs_idx in enumerate(installed_cs_indices):
        worker_id = worker_start + (i % 8)
        task_data = (cs_config_dict, failure_cs_idx, trial_number, worker_id,
                    str(config.save_dir), combination_id, config)
        task_data_list.append(task_data)

    # multiprocessingで並列実行
    print(f"⚡ 故障シナリオを並列実行中... ({len(task_data_list)}個)")
    max_processes = min(8, len(task_data_list))

    try:
        with Pool(processes=max_processes) as pool:
            results = pool.map(run_single_failure_scenario, task_data_list)
    except Exception as e:
        print(f"❌ Pool処理エラー: {e}")
        # フォールバック: 順次処理
        print("🔄 順次処理にフォールバック")
        results = [run_single_failure_scenario(task_data) for task_data in task_data_list]

    # 有効な結果を抽出
    valid_results = [r for r in results if r['cost'] != float('inf')]

    if not valid_results:
        print("❌ 有効な故障シナリオ結果がありません")
        return {
            'trial_number': trial_number,
            'worst_cost': float('inf'),
            'worst_details': {},
            'all_results': results
        }

    # 最悪ケースを特定
    worst_result = max(valid_results, key=lambda x: x['cost'])
    worst_cost = worst_result['cost']

    print(f"📊 故障シナリオ結果: 有効{len(valid_results)}/{len(results)}件, 最悪コスト={worst_cost:.2f}万円")

    return {
        'trial_number': trial_number,
        'worst_cost': worst_cost,
        'worst_details': worst_result,
        'all_results': valid_results
    }


def evaluate_unified_objective(cs_config_dict, trial_number, combination_id, config):
    """統合目的関数を評価

    Args:
        cs_config_dict: CS設定辞書
        trial_number: トライアル番号
        combination_id: 組み合わせID
        config: UnifiedOptimizationConfig 設定オブジェクト

    Returns:
        dict: 統合評価結果
    """
    print(f"\n=== Trial {trial_number}: 統合評価開始 (P={config.failure_weight}) ===")

    normal_cost = 0.0
    normal_result = None
    worst_failure_cost = 0.0
    failure_result = None

    # P値に応じて実行パターンを決定
    run_normal = config.failure_weight < 1.0  # P<1.0の場合に平常時を実行
    run_failure = config.failure_weight > 0.0  # P>0.0の場合に故障時を実行

    # ========================================
    # ケース1: 両方実行（0 < P < 1）→ 並列実行
    # ========================================
    if run_normal and run_failure:
        print(f"⚡ 平常時・故障時シナリオを並列実行中...")

        worker_id_normal = combination_id * 9 + 1  # 平常時Worker
        normal_task = (cs_config_dict, None, trial_number, worker_id_normal,
                      str(config.save_dir), combination_id, config)

        # ThreadPoolExecutorで並列実行（ProcessPoolExecutorはネストした並列処理で問題が起きやすい）
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            # 両方のタスクを同時に開始
            normal_future = executor.submit(run_single_failure_scenario, normal_task)
            failure_future = executor.submit(
                create_failure_scenario_parallel_safe,
                cs_config_dict, trial_number, combination_id, config
            )

            # 結果を収集
            normal_result = normal_future.result()
            failure_result = failure_future.result()

        normal_cost = normal_result['cost']
        worst_failure_cost = failure_result['worst_cost']

        print(f"✅ 平常時コスト: {normal_cost:.2f}万円")
        print(f"✅ ワースト故障コスト: {worst_failure_cost:.2f}万円")

    # ========================================
    # ケース2: 平常時のみ実行（P=0）
    # ========================================
    elif run_normal and not run_failure:
        worker_id = combination_id * 9 + 1  # 平常時Worker
        print(f"📊 平常時シナリオのみ実行中... (Worker {worker_id})")

        normal_task = (cs_config_dict, None, trial_number, worker_id,
                      str(config.save_dir), combination_id, config)
        normal_result = run_single_failure_scenario(normal_task)
        normal_cost = normal_result['cost']

        print(f"✅ 平常時コスト: {normal_cost:.2f}万円")
        print("⏭️  P=0.0のため故障シナリオをスキップ")
        failure_result = {'worst_cost': 0.0, 'worst_details': {}, 'all_results': []}

    # ========================================
    # ケース3: 故障時のみ実行（P=1）
    # ========================================
    elif not run_normal and run_failure:
        print("⏭️  P=1.0のため平常時シナリオをスキップ")
        print(f"🔥 故障シナリオのみ実行中...")

        failure_result = create_failure_scenario_parallel_safe(
            cs_config_dict, trial_number, combination_id, config
        )
        worst_failure_cost = failure_result['worst_cost']
        print(f"✅ ワースト故障コスト: {worst_failure_cost:.2f}万円")

    # ========================================
    # Step 3: 統合コスト計算（カスタム目的関数を使用）
    # ========================================
    unified_cost = config.calculate_objective(normal_cost, worst_failure_cost)

    print(f"📊 統合評価結果:")
    print(f"   目的関数: {config.objective_function.name}")
    print(f"   平常時コスト: {normal_cost:.2f}万円 (重み: {config.normal_weight:.2f})")
    print(f"   故障時コスト: {worst_failure_cost:.2f}万円 (重み: {config.failure_weight:.2f})")
    print(f"   統合コスト: {unified_cost:.2f}万円")

    return {
        'trial_number': trial_number,
        'unified_cost': unified_cost,
        'normal_cost': normal_cost,
        'worst_failure_cost': worst_failure_cost,
        'normal_details': normal_result,
        'failure_details': failure_result
    }


def run_parallel_optimization_batch_unified(study, outer_parallel):
    """統合版並列バッチ最適化

    Args:
        study: Optuna study
        outer_parallel: 並列実行するトライアル数

    Returns:
        int: 成功した登録数
    """
    # CONFIGのNoneチェック
    assert CONFIG is not None, "CONFIG is not initialized"

    print(f"\n🔥 統合最適化バッチ処理開始 (P={CONFIG.failure_weight}, 目的関数={CONFIG.objective_function.name})")

    # トライアル生成
    batch_trials = []
    batch_configs = []

    for i in range(outer_parallel):
        trial = study.ask()
        config = set_cs_placement(trial)
        batch_trials.append(trial)
        batch_configs.append(config)

    # パラメータ確認
    print("\n🔍 バッチ内パラメータ:")
    for i, (trial, config) in enumerate(zip(batch_trials, batch_configs)):
        active_cs = sum(1 for p in config['ports'] if p > 0)
        total_ports = sum(config['ports'])
        print(f"  Trial {trial.number} (組み合わせ{i}): CS配置{active_cs}箇所, 合計{total_ports}ポート")

    # 環境構築: 必要Worker数 = outer_parallel * 9 (各組み合わせに平常時1 + 故障時8)
    max_workers_needed = outer_parallel * 9
    print(f"🖥️  必要Worker数: {max_workers_needed} (平常{outer_parallel} + 故障{outer_parallel*8})")

    prepare_parallel_environment(batch_configs[0], parallel_count=outer_parallel, batch_size=9)

    # csListの更新とディレクトリ構造の確認（メインプロセスで実行）
    for parallel in range(outer_parallel):
        for worker_id in range(1, 10):  # 9個/トライアル
            global_worker_id = parallel * 9 + worker_id
            cs_config = batch_configs[parallel]

            # Workerパスを取得
            worker_paths = get_paths(global_worker_id)

            # resultディレクトリ構造を確実に作成
            result_dir = worker_paths["result"]
            os.makedirs(result_dir, exist_ok=True)
            os.makedirs(os.path.join(result_dir, "emates"), exist_ok=True)
            os.makedirs(os.path.join(result_dir, "inst"), exist_ok=True)
            os.makedirs(os.path.join(result_dir, "opendss"), exist_ok=True)

            # csListを更新
            csList_file = worker_paths["csList"]
            update_cs_list(cs_config, csList_file)

    # 並列評価実行
    print(f"\n⚡ {outer_parallel}並列で統合評価開始...")

    cpu_cores = os.cpu_count()
    # optimal_outer_processes = min(outer_parallel, cpu_cores // 9 if cpu_cores else 1)
    optimal_outer_processes = outer_parallel  # CPUコア数制限を外す
    print(f"🖥️  CPU情報: {cpu_cores}コア, outer_parallel数: {outer_parallel}")

    batch_results = []

    if outer_parallel == 1:
        # 単一トライアルは順次処理
        for i, (trial, cs_config) in enumerate(zip(batch_trials, batch_configs)):
            print(f"\n--- トライアル {i+1}/{len(batch_trials)} ---")
            result = evaluate_unified_objective(cs_config, trial.number, i, CONFIG)
            batch_results.append((trial, cs_config, result))
    else:
        # 並列処理
        with concurrent.futures.ProcessPoolExecutor(max_workers=optimal_outer_processes) as executor:
            future_to_data = {}

            for i, (trial, cs_config) in enumerate(zip(batch_trials, batch_configs)):
                future = executor.submit(
                    evaluate_unified_objective,
                    cs_config, trial.number, i, CONFIG
                )
                future_to_data[future] = (trial, cs_config, i)

            # 結果を収集
            print(f"📊 {len(future_to_data)}個のfutureを待機中...")

            for future in concurrent.futures.as_completed(future_to_data, timeout=3600):
                trial, cs_config, combination_id = future_to_data[future]
                try:
                    result = future.result(timeout=600)
                    batch_results.append((trial, cs_config, result))
                    print(f"✅ Trial {trial.number} (組み合わせ{combination_id}) 完了: "
                          f"統合コスト={result['unified_cost']:.2f}万円")
                except Exception as e:
                    print(f"❌ Trial {trial.number} (組み合わせ{combination_id}) エラー: {e}")
                    import traceback
                    traceback.print_exc()
                    batch_results.append((trial, cs_config, {
                        'trial_number': trial.number,
                        'unified_cost': float('inf'),
                        'normal_cost': float('inf'),
                        'worst_failure_cost': float('inf'),
                        'normal_details': None,
                        'failure_details': {'worst_details': {}, 'all_results': []}
                    }))

    # Optunaに登録
    print(f"\n📋 {len(batch_results)}個のトライアル結果をOptunaに登録中...")

    successful_registrations = 0

    for trial, config, result in batch_results:
        unified_cost = result['unified_cost']

        try:
            # user_attr設定
            trial.set_user_attr('failure_weight', CONFIG.failure_weight)
            trial.set_user_attr('objective_function', CONFIG.objective_function.name)
            trial.set_user_attr('normal_cost', result['normal_cost'])
            trial.set_user_attr('worst_failure_cost', result['worst_failure_cost'])
            trial.set_user_attr('unified_cost', unified_cost)

            # 故障時詳細
            if result['failure_details']:
                failure_details = result['failure_details'].get('worst_details', {})
                if failure_details:
                    trial.set_user_attr('worst_failure_cs', failure_details.get('failure_cs_idx', -1))
                    trial.set_user_attr('worst_wait_time_95p', failure_details.get('wait_time_95p', 0))

            # 平常時詳細
            if result['normal_details']:
                trial.set_user_attr('normal_wait_time_95p',
                                  result['normal_details'].get('wait_time_95p', 0))

            # CS配置情報
            active_cs_info = []
            for i, (csid, ports, cap) in enumerate(zip(config['csids'], config['ports'], config['cap_kw'])):
                if ports > 0:
                    active_cs_info.append({
                        'csid': csid,
                        'ports': ports,
                        'capacity_kw': cap
                    })
            trial.set_user_attr('active_cs_config', active_cs_info)
            trial.set_user_attr('total_active_cs', len(active_cs_info))
            trial.set_user_attr('total_ports', sum(cs['ports'] for cs in active_cs_info))

            # 統合コストでstudyに登録
            study.tell(trial, unified_cost)
            print(f"✅ Trial {trial.number}: 統合コスト{unified_cost:.2f}万円を登録")

            successful_registrations += 1

        except Exception as e:
            print(f"❌ Trial {trial.number} の結果登録でエラー: {e}")
            continue

    print(f"✅ バッチ完了: {successful_registrations}/{len(batch_results)}件の結果をstudyに登録")
    return successful_registrations


def run_optimization_with_unified_objective(study, config: UnifiedOptimizationConfig):
    """統合最適化を実行

    Args:
        study: Optuna study
        config: 統合最適化設定
    """
    print(f"\n🎯🔥 統合最適化開始")
    print(f"   目標: {config.total_trials}トライアル")
    print(f"   並列度: {config.outer_parallel}")
    print(f"   目的関数: {config.objective_function.name}")
    print(f"   {config.get_objective_formula()}")
    print(f"🔍 収束判定: {config.convergence_patience}トライアル連続で"
          f"改善率{config.convergence_threshold*100:.2f}%未満で終了")

    # 完了したトライアル数で判定（enqueue済み未実行は含まない）
    completed_trials_count = len([t for t in study.trials
                                  if t.state == optuna.trial.TrialState.COMPLETE])
    total_trials_count = len(study.trials)
    print(f"📊 現在のトライアル数: {total_trials_count} (完了: {completed_trials_count})")
    remaining_trials = max(0, config.total_trials - completed_trials_count)

    if remaining_trials == 0:
        print("✅ すべてのトライアルが完了済みです")
        return

    print(f"📊 現在の進捗: {completed_trials_count}/{config.total_trials}")
    print(f"🔄 残り{remaining_trials}トライアルを実行します")

    # バッチ数を計算
    batches_needed = (remaining_trials + config.outer_parallel - 1) // config.outer_parallel

    try:
        for batch_idx in range(batches_needed):
            # 完了したトライアル数で判定（enqueue済み未実行は含まない）
            completed_trials_count = len([t for t in study.trials
                                          if t.state == optuna.trial.TrialState.COMPLETE])
            if completed_trials_count >= config.total_trials:
                print("✅ 目標トライアル数に到達しました")
                break

            # 収束判定
            if completed_trials_count >= config.convergence_patience:
                is_converged, convergence_msg = check_convergence(
                    study,
                    patience=config.convergence_patience,
                    min_improvement=config.convergence_threshold
                )

                print(f"🔍 {convergence_msg}")

                if is_converged:
                    print(f"🛑 収束により最適化を終了します (Trial {completed_trials_count})")
                    print(f"📊 最終最適値: {study.best_value:.2f}万円")
                    break

            actual_batch_size = min(config.outer_parallel, config.total_trials - completed_trials_count)
            print(f"\n--- バッチ {batch_idx + 1}/{batches_needed} (サイズ: {actual_batch_size}) ---")

            completed = run_parallel_optimization_batch_unified(study, actual_batch_size)

            completed_trials_count = len([t for t in study.trials
                                          if t.state == optuna.trial.TrialState.COMPLETE])
            print(f"📈 進捗更新: {completed_trials_count}/{config.total_trials} 完了")

    except KeyboardInterrupt:
        print("\n⚠️ ユーザーによる中断")
    except Exception as e:
        print(f"❌ 最適化中にエラー: {e}")
        import traceback
        traceback.print_exc()
    finally:
        cleanup_worker_environments()
        print("🧹 最終クリーンアップ完了")

    print(f"🎉 統合最適化完了: {len(study.trials)}トライアル実行済み")


def run_evaluate_only_mode(config: UnifiedOptimizationConfig, initial_config_name: str | None = None):
    """初期解を評価するだけのモード（最適化をスキップ）

    Args:
        config: 最適化設定
        initial_config_name: 評価する初期配置の名前（Noneの場合は全初期配置を評価）
    """
    global CONFIG
    CONFIG = config

    print("\n" + "=" * 60)
    print("🔍 評価専用モード（最適化スキップ）")
    print("=" * 60)

    # csList.txtから利用可能なCS情報を取得
    paths = get_paths()
    cslist_file = paths['csList']

    try:
        with open(cslist_file, 'r') as f:
            cslist_data = f.readlines()
        cslist_data = [line.strip() for line in cslist_data if line.strip()]
        csids = [int(line.split(',')[0]) for line in cslist_data]
    except Exception as e:
        print(f"❌ csList読み込みエラー: {e}")
        return None

    # 初期配置を取得
    configs_to_evaluate = []

    if config.initial_cs_config_file:
        print(f"📋 CSVファイルから初期配置を読み込み: {config.initial_cs_config_file}")
        try:
            import pandas as pd
            df = pd.read_csv(config.initial_cs_config_file)

            # CSVフォーマット: name, csid, capacity_kw, ports
            # 同一のnameは同じcs_configとしてグループ化
            grouped = df.groupby('config_name')

            for config_name, group in grouped:
                # 特定の名前が指定されている場合はフィルタリング
                if initial_config_name and config_name != initial_config_name:
                    continue

                # cs_config_dictを作成（全CSを0で初期化）
                cs_config_dict = {}
                for csid in csids:
                    cs_config_dict[csid] = {'ports': 0, 'capacity_kw': 0}

                # CSVの各行からCS設定を読み込み
                for _, row in group.iterrows():
                    csid = int(row['csid'])
                    if csid in csids:
                        cs_config_dict[csid] = {
                            'ports': int(row['ports']),
                            'capacity_kw': float(row['capacity_kw'])
                        }

                configs_to_evaluate.append({
                    'name': config_name,
                    'cs_config_dict': cs_config_dict
                })

            print(f"✅ {len(configs_to_evaluate)}個の初期配置を読み込みました")

        except Exception as e:
            print(f"❌ CSV読み込みエラー: {e}")
            import traceback
            traceback.print_exc()
            return None
    else:
        print("⚠️ 初期配置ファイルが設定されていません（initial_cs_config_file）")
        return None

    if not configs_to_evaluate:
        print(f"⚠️ 指定された初期配置 '{initial_config_name}' が見つかりません")
        # CSVファイルから利用可能な配置名を取得して表示
        try:
            import pandas as pd
            df = pd.read_csv(config.initial_cs_config_file)
            available_names = df['config_name'].unique().tolist()
            print(f"   利用可能な配置: {available_names}")
        except Exception:
            pass
        return None

    print(f"📋 評価対象: {len(configs_to_evaluate)}個の初期配置")
    for cfg in configs_to_evaluate:
        active_cs = [csid for csid, v in cfg['cs_config_dict'].items() if v['ports'] > 0]
        print(f"  - {cfg['name']}: {len(active_cs)}箇所にCS配置")

    # 各配置を評価
    results = []
    for idx, eval_cfg in enumerate(configs_to_evaluate):
        print(f"\n{'='*60}")
        print(f"📊 評価開始: {eval_cfg['name']} ({idx+1}/{len(configs_to_evaluate)})")
        print(f"{'='*60}")

        cs_config_raw = eval_cfg['cs_config_dict']
        combination_id = idx  # 評価専用なのでシンプルなID

        # {csid: {'ports': ..., 'capacity_kw': ...}} 形式を
        # {'csids': [...], 'ports': [...], 'cap_kw': [...]} 形式に変換
        # 他の部分との構造の統一を図るため
        cs_config_dict = {
            'csids': list(cs_config_raw.keys()),
            'ports': [v['ports'] for v in cs_config_raw.values()],
            'cap_kw': [v['capacity_kw'] for v in cs_config_raw.values()]
        }
        print(f"cs_config変換後: csids={len(cs_config_dict['csids'])}件, "
              f"active={sum(1 for p in cs_config_dict['ports'] if p > 0)}箇所")
        # シミュレーション環境の作成＆実行
        try:
            unified_cost, details = evaluate_unified_objective(
                cs_config_dict=cs_config_dict,
                trial_number=0,
                combination_id=combination_id,
                config=config
            )

            result = {
                'name': eval_cfg['name'],
                'unified_cost': unified_cost,
                'details': details,
                'cs_config': cs_config_raw,  # 保存用は元の形式
            }
            results.append(result)

            print(f"\n✅ 評価完了: {eval_cfg['name']}")
            print(f"   統合コスト: {unified_cost:,.2f}万円")
            if details and isinstance(details, dict):
                print(f"   平常時コスト: {details.get('normal_cost', 'N/A')}")
                print(f"   最悪故障コスト: {details.get('worst_failure_cost', 'N/A')}")

        except Exception as e:
            print(f"❌ 評価エラー: {eval_cfg['name']}")
            print(f"   エラー内容: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                'name': eval_cfg['name'],
                'unified_cost': float('inf'),
                'error': str(e),
            })

    # 結果を保存
    config.save_dir.mkdir(parents=True, exist_ok=True)
    results_file = config.save_dir / "evaluate_only_results.json"

    # 結果をJSON保存用に変換
    serializable_results = []
    for r in results:
        sr = {
            'name': r['name'],
            'unified_cost': r['unified_cost'] if r['unified_cost'] != float('inf') else 'Infinity',
        }
        if 'details' in r and r['details']:
            sr['details'] = {k: v for k, v in r['details'].items()
                           if not isinstance(v, (dict, list)) or k in ['normal_cost', 'worst_failure_cost']}
        if 'error' in r:
            sr['error'] = r['error']

        # cs_configをシリアライズ
        if 'cs_config' in r:
            sr['cs_config'] = [
                {'csid': csid, 'ports': v['ports'], 'capacity_kw': v['capacity_kw']}
                for csid, v in r['cs_config'].items()
                if v['ports'] > 0
            ]

        serializable_results.append(sr)

    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump({
            'mode': 'evaluate_only',
            'timestamp': datetime.now().isoformat(),
            'config': {
                'experiment_name': config.experiment_name,
                'failure_weight': config.failure_weight,
                'objective_function': config.objective_function.name if hasattr(config.objective_function, 'name') else str(config.objective_function),
            },
            'results': serializable_results
        }, f, indent=2, ensure_ascii=False)

    print(f"\n💾 評価結果を保存: {results_file}")

    # サマリー表示
    print(f"\n{'='*60}")
    print("📊 評価結果サマリー")
    print(f"{'='*60}")
    for r in results:
        cost_str = f"{r['unified_cost']:,.2f}万円" if r['unified_cost'] != float('inf') else "エラー"
        print(f"  {r['name']}: {cost_str}")

    return results


def load_config_from_args() -> tuple[UnifiedOptimizationConfig, bool, dict]:
    """コマンドライン引数から設定を読み込み

    Returns:
        tuple: (設定オブジェクト, 可視化を実行するかどうか, 追加オプション辞書)
    """
    parser = argparse.ArgumentParser(description="統合最適化実行")
    parser.add_argument("--config", type=str, required=True,
                       help="設定JSONファイルパス")
    parser.add_argument("--resume", action="store_true",
                       help="既存のstudyから継続実行")
    parser.add_argument("--no-visualize", action="store_true",
                       help="最適化完了後の可視化をスキップ")
    parser.add_argument("--evaluate-only", "-e", action="store_true",
                       help="初期解のみを評価して最適化をスキップ")
    parser.add_argument("--initial-config-name", type=str, default=None,
                       help="評価する初期解の名前（initial_cs_configs.csvのconfig_name）")

    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        raise FileNotFoundError(f"設定ファイルが見つかりません: {config_path}")

    config = UnifiedOptimizationConfig.from_json(config_path)
    print(f"✅ 設定ファイルを読み込みました: {config_path}")

    options = {
        'evaluate_only': args.evaluate_only,
        'initial_config_name': args.initial_config_name,
    }

    return config, not args.no_visualize, options


def print_config_summary(config: UnifiedOptimizationConfig):
    """設定のサマリーを表示"""
    print("=" * 60)
    print("📋 統合最適化設定サマリー")
    print("=" * 60)
    print(f"実験名: {config.experiment_name}")
    print(f"保存先: {config.save_dir}")
    print(f"データベース: {config.db_path}")
    print(f"\n🎯 最適化設定:")
    print(f"  トライアル数: {config.total_trials}")
    print(f"  並列度: {config.outer_parallel}")
    print(f"  TPEサンプラー: n_startup_trials={config.n_startup_trials}")
    print(f"\n📊 目的関数:")
    print(f"  {config.get_objective_formula()}")
    print(f"  タイプ: {config.objective_function.name}")
    print(f"  平常時重み: {config.normal_weight:.3f}")
    print(f"  故障時重み: {config.failure_weight:.3f}")
    print(f"\n🔍 収束判定:")
    print(f"  patience: {config.convergence_patience}トライアル")
    print(f"  閾値: {config.convergence_threshold*100:.2f}%")
    print(f"\n⚙️ シミュレーション設定:")
    print(f"  時間窓: {config.t_hour}時間")
    if config.failure_flag:
        print(f"  故障発生時刻: {config.failure_time}")
    print("=" * 60)


if __name__ == "__main__":
    # 実行時間を記録
    start_time = time.time()
    print("\n🚀 統合最適化システム起動")

    # 設定読み込み
    config, run_visualization, options = load_config_from_args()
    print_config_summary(config)

    # グローバル設定（multiprocessing用）
    CONFIG = config

    # 保存ディレクトリ作成
    config.save_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n📁 保存先ディレクトリ作成: {config.save_dir}")

    # 評価専用モードの処理
    if options.get('evaluate_only'):
        print("\n🔍 評価専用モードで実行します")
        try:
            results = run_evaluate_only_mode(config, options.get('initial_config_name'))
            if results:
                print(f"\n✅ 評価完了: {len(results)}個の配置を評価しました")
        except Exception as e:
            print(f"❌ 評価エラー: {e}")
            import traceback
            traceback.print_exc()
        finally:
            cleanup_worker_environments()
            print("🧹 クリーンアップ完了")

        print(f"\n{'='*60}")
        print("👋 評価専用モード終了")
        print(f"{'='*60}\n")
        sys.exit(0)

    # 以下は通常の最適化モード
    # データベース設定
    db_url = f"sqlite:///{config.db_path}"
    storage = optuna.storages.RDBStorage(
        url=db_url,
        engine_kwargs={"connect_args": {"timeout": 600.0}}
    )
    print(f"🗄️  SQLiteストレージ: {config.db_path}")

    # サンプラー設定
    sampler = optuna.samplers.TPESampler(
        n_startup_trials=config.n_startup_trials,
        seed=42
    )
    print(f"🎲 TPESampler設定完了")

    # Study作成/読み込み
    study_name = f"unified_optimization_{config.experiment_name}"

    try:
        study = optuna.create_study(
            study_name=study_name,
            direction="minimize",
            sampler=sampler,
            storage=storage,
            load_if_exists=True
        )

        existing_trials = len(study.trials)
        if existing_trials > 0:
            print(f"📚 既存のstudy読み込み: {existing_trials}トライアル")
            print(f"   現在のベスト: {study.best_value:.2f}万円 (Trial {study.best_trial.number})")
        else:
            print(f"📝 新規study作成: {study_name}")

            # 初期値の設定（新規studyの場合のみ）
            print("\n🎯 初期パラメータ設定")
            initial_params = get_initial_cs_params(config)
            if initial_params:
                for i, params in enumerate(initial_params):
                    study.enqueue_trial(params)
                print(f"✅ {len(initial_params)}個の初期パラメータをエンキュー")

    except Exception as e:
        print(f"❌ Study作成/読み込みエラー: {e}")
        sys.exit(1)

    # 最適化実行
    try:
        print(f"\n{'='*60}")
        print("🎯 最適化開始")
        print(f"{'='*60}\n")

        run_optimization_with_unified_objective(study, config)

        print(f"\n{'='*60}")
        print("🎉 最適化完了")
        print(f"{'='*60}")
        print(f"実行トライアル数: {len(study.trials)}")

        # 完了したトライアルの確認
        completed_trials = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]

        if len(completed_trials) == 0:
            print("⚠️ 完了したトライアルがありません")
        else:
            print(f"完了トライアル数: {len(completed_trials)}")
            print(f"最良値: {study.best_value:.2f}万円")
            print(f"最良トライアル: Trial {study.best_trial.number}")

            # 最良パラメータ表示
            print(f"\n📊 最良CS配置:")
            best_cs_config = study.best_trial.user_attrs.get('active_cs_config', [])
            for cs_info in best_cs_config:
                print(f"  CS#{cs_info['csid']}: {cs_info['ports']}ポート, {cs_info['capacity_kw']:.1f}kW")

            print(f"\n📈 最良トライアル詳細:")
            print(f"  平常時コスト: {study.best_trial.user_attrs.get('normal_cost', 0):.2f}万円")
            print(f"  故障時コスト: {study.best_trial.user_attrs.get('worst_failure_cost', 0):.2f}万円")
            print(f"  統合コスト: {study.best_trial.user_attrs.get('unified_cost', 0):.2f}万円")

            # 結果保存
            try:
                # 保存先ディレクトリの確認と作成
                config.save_dir.mkdir(parents=True, exist_ok=True)

                results_file = config.save_dir / "best_result.json"
                with open(results_file, 'w', encoding='utf-8') as f:
                    json.dump({
                        'study_name': study_name,
                        'total_trials': len(study.trials),
                        'completed_trials': len(completed_trials),
                        'best_value': study.best_value,
                        'best_trial_number': study.best_trial.number,
                        'best_params': study.best_trial.params,
                        'best_user_attrs': study.best_trial.user_attrs,
                        'configuration': {
                            'experiment_name': config.experiment_name,
                            'failure_weight': config.failure_weight,
                            'objective_function': config.objective_function.name,
                            'total_trials': config.total_trials
                        }
                    }, f, indent=2, ensure_ascii=False)

                print(f"\n💾 結果を保存しました: {results_file}")
            except Exception as save_error:
                print(f"\n⚠️ 結果保存エラー: {save_error}")
                print(f"   保存先: {config.save_dir}")
                # エラーでも続行

    except KeyboardInterrupt:
        print("\n⚠️ ユーザーによる中断")
    except Exception as e:
        print(f"\n❌ エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n🧹 クリーンアップ実行中...")
        cleanup_worker_environments()
        print("✅ ワーカー環境クリーンアップ完了")

        # pklファイル整理（Best1のみ保持）
        print("\n🗑️ pklファイル整理中...")
        manage_pkl_files_after_optimization(study, str(config.save_dir), keep_best_n=config.keep_best_n)
        print("✅ pklファイル整理完了")

    # 可視化実行
    if run_visualization:
        try:
            from src.util.visualize_results import generate_extended_report
            print("\n📊 可視化レポート生成中...")
            generate_extended_report(
                result_dir=config.save_dir,
                study_name=study_name,
                config=config,
            )
        except Exception as viz_error:
            print(f"⚠️ 可視化エラー（スキップ）: {viz_error}")
            import traceback
            traceback.print_exc()
    else:
        print("\n⏭️ 可視化はスキップされました（--no-visualize）")

    print(f"\n{'='*60}")
    print("👋 統合最適化システム終了")
    print(f"{'='*60}\n")
    end_time = time.time()
    print(f"実行時間: {end_time - start_time}秒")
