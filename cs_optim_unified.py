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

# 計算済みの実効パラメータを記録するセット（重複検出用）
visited_effective_params: set[tuple] = set()


def get_effective_key(cs_config: dict) -> tuple:
    """CS配置から実効パラメータキーを生成

    ports=0の箇所はcapacityを無視（-1で正規化）することで、
    シミュレーション結果に影響しないパラメータ違いを同一とみなす。

    Returns:
        tuple: ((csid, ports, cap_or_-1), ...)
    """
    key_list = []
    for csid, ports, cap in zip(cs_config['csids'], cs_config['ports'], cs_config['cap_kw']):
        if ports > 0:
            key_list.append((csid, ports, cap))
        else:
            key_list.append((csid, 0, -1))
    return tuple(key_list)

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



def create_all_tasks_flat(batch_trials, batch_configs, config):
    """全シミュレーションタスクを生成（フラット並列用、メタデータ付与）

    Args:
        batch_trials: Optunaトライアルのリスト
        batch_configs: CS配置設定のリスト
        config: UnifiedOptimizationConfig 設定オブジェクト

    Returns:
        list[dict]: タスク辞書のリスト
    """
    all_tasks = []

    for trial_idx, (trial, cs_config) in enumerate(zip(batch_trials, batch_configs)):
        # トライアルごとのWorker IDオフセット
        worker_offset = trial_idx * 9

        # P値に応じて実行するシナリオを決定
        run_normal = config.failure_weight < 1.0  # P<1.0の場合に平常時を実行
        run_failure = config.failure_weight > 0.0  # P>0.0の場合に故障時を実行

        # 平常時シナリオ
        if run_normal:
            normal_task = {
                'trial_id': trial_idx,
                'trial_number': trial.number,
                'scenario_type': 'normal',
                'scenario_id': None,
                'worker_id': worker_offset + 1,
                'cs_config': cs_config,
                'failure_cs_idx': None,
                'save_dir': str(config.save_dir),
                'config': config
            }
            all_tasks.append(normal_task)

        # 故障時シナリオ
        if run_failure:
            installed_cs_indices = [
                i for i, ports in enumerate(cs_config['ports']) if ports > 0
            ]

            for scenario_idx, failure_cs_idx in enumerate(installed_cs_indices):
                failure_task = {
                    'trial_id': trial_idx,
                    'trial_number': trial.number,
                    'scenario_type': 'failure',
                    'scenario_id': scenario_idx,
                    'worker_id': worker_offset + 2 + (scenario_idx % 8),
                    'cs_config': cs_config,
                    'failure_cs_idx': failure_cs_idx,
                    'save_dir': str(config.save_dir),
                    'config': config
                }
                all_tasks.append(failure_task)

    return all_tasks


def run_single_scenario_from_task(task):
    """タスク辞書から単一シナリオを実行（フラット並列用）

    Args:
        task: タスク辞書（trial_id, worker_id, cs_config等を含む）

    Returns:
        dict: 実行結果（trial_id等のメタデータを含む）
    """
    worker_id = task['worker_id']
    cs_config = task['cs_config']
    failure_cs_idx = task['failure_cs_idx']
    config = task['config']
    trial_number = task['trial_number']
    save_dir = task['save_dir']
    trial_id = task['trial_id']

    scenario_type = "平常時" if failure_cs_idx is None else f"故障CS{failure_cs_idx}"

    try:
        # 制約チェック
        if not check_cs_placement(cs_config):
            print(f"❌ Trial {trial_number} (ID:{trial_id}), Worker{worker_id}: {scenario_type} 制約違反")
            return {
                'trial_id': trial_id,
                'trial_number': trial_number,
                'scenario_type': task['scenario_type'],
                'scenario_id': task['scenario_id'],
                'failure_cs_idx': failure_cs_idx,
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

        # 故障情報作成
        create_failure_info_for_worker(
            cs_config, failure_cs_idx, worker_id,
            FAILURE_TIME=config.failure_time,
            file_write_lock=file_write_lock
        )

        # CS設定書き込み
        csList_file = worker_paths["csList"]
        update_cs_list(cs_config, csList_file)

        # シミュレーション実行
        only_run_emates(worker_id=worker_id, HOUR=config.t_hour)

        scenario_suffix = "normal" if failure_cs_idx is None else f"failure_{failure_cs_idx}"
        results_filename = f"trial_{trial_number}_id{trial_id}_{scenario_suffix}.pkl"
        results_filepath = os.path.join(save_dir, results_filename)

        # 保存先ディレクトリの確認と作成
        os.makedirs(os.path.dirname(results_filepath), exist_ok=True)

        save_data_to_pickle(filename=results_filepath, worker_id=worker_id)

        evaluation_cost, _ = evaluation_total_costs(result_file=results_filepath)
        wait_time_95p = calculate_95percentile_wait_time(results_filepath)

        print(f"✅ Trial {trial_number} (ID:{trial_id}), Worker{worker_id}: {scenario_type} 完了, コスト={evaluation_cost:.2f}万円")

        return {
            'trial_id': trial_id,
            'trial_number': trial_number,
            'scenario_type': task['scenario_type'],
            'scenario_id': task['scenario_id'],
            'failure_cs_idx': failure_cs_idx,
            'worker_id': worker_id,
            'cost': evaluation_cost,
            'wait_time_95p': wait_time_95p,
            'results_filepath': results_filepath,
            'cs_config': cs_config.copy()
        }

    except Exception as e:
        import traceback
        print(f"💥 Trial {trial_number} (ID:{trial_id}), Worker{worker_id}: {scenario_type} エラー: {e}")
        print(f"📋 トレースバック:\n{traceback.format_exc()}")
        return {
            'trial_id': trial_id,
            'trial_number': trial_number,
            'scenario_type': task['scenario_type'],
            'scenario_id': task['scenario_id'],
            'failure_cs_idx': failure_cs_idx,
            'worker_id': worker_id,
            'cost': float('inf'),
            'error': str(e)
        }


def aggregate_results_by_trial(all_results, batch_trials, batch_configs, config):
    """実行結果をtrial_idでグルーピングし、統合コストを計算

    Args:
        all_results: 全シナリオの実行結果リスト
        batch_trials: Optunaトライアルのリスト
        batch_configs: CS配置設定のリスト
        config: UnifiedOptimizationConfig 設定オブジェクト

    Returns:
        dict: trial_idをキーとした集約結果
    """
    # trial_idでグルーピング
    results_by_trial = {}

    for result in all_results:
        trial_id = result['trial_id']

        if trial_id not in results_by_trial:
            results_by_trial[trial_id] = {
                'trial': batch_trials[trial_id],
                'cs_config': batch_configs[trial_id],
                'normal': None,
                'failures': []
            }

        if result['scenario_type'] == 'normal':
            results_by_trial[trial_id]['normal'] = result
        else:
            results_by_trial[trial_id]['failures'].append(result)

    # 各トライアルの統合コストを計算
    aggregated_results = {}

    for trial_id in sorted(results_by_trial.keys()):
        trial_data = results_by_trial[trial_id]

        # 平常時コスト
        normal_cost = 0.0
        normal_details = None
        if trial_data['normal'] is not None:
            normal_cost = trial_data['normal']['cost']
            normal_details = trial_data['normal']

        # 故障時最悪コスト
        worst_failure_cost = 0.0
        worst_failure_details = None
        valid_failures = [f for f in trial_data['failures'] if f['cost'] != float('inf')]

        if valid_failures:
            worst_failure_details = max(valid_failures, key=lambda x: x['cost'])
            worst_failure_cost = worst_failure_details['cost']

        # 統合コスト計算
        unified_cost = config.calculate_objective(normal_cost, worst_failure_cost)

        print(f"📊 Trial {trial_data['trial'].number} (ID:{trial_id}) 集約:")
        print(f"   平常時: {normal_cost:.2f}万円, 故障時最悪: {worst_failure_cost:.2f}万円")
        print(f"   統合コスト: {unified_cost:.2f}万円")

        aggregated_results[trial_id] = {
            'trial': trial_data['trial'],
            'cs_config': trial_data['cs_config'],
            'unified_cost': unified_cost,
            'normal_cost': normal_cost,
            'worst_failure_cost': worst_failure_cost,
            'normal_details': normal_details,
            'failure_details': {
                'worst_details': worst_failure_details,
                'all_results': valid_failures
            }
        }

    return aggregated_results




def run_parallel_optimization_batch_unified(study, outer_parallel):
    """統合版フラット並列バッチ最適化

    Args:
        study: Optuna study
        outer_parallel: 並列実行するトライアル数

    Returns:
        int: 成功した登録数
    """
    # CONFIGのNoneチェック
    assert CONFIG is not None, "CONFIG is not initialized"

    print(f"\n🔥 統合最適化バッチ処理開始（フラット並列）")
    print(f"   並列度: {outer_parallel}トライアル")
    print(f"   目的関数: {CONFIG.objective_function.name}")
    print(f"   P値: {CONFIG.failure_weight}")

    # トライアル生成（重複検出時はリトライ）
    global visited_effective_params
    total_skipped = 0
    MAX_RETRY = 10

    batch_trials = []
    batch_configs = []

    i = 0
    while i < outer_parallel:
        trial = study.ask()
        config = set_cs_placement(trial)

        # 実効パラメータによる重複チェック
        effective_key = get_effective_key(config)
        retry_count = 0
        while effective_key in visited_effective_params and retry_count < MAX_RETRY:
            print(f"↩️  Trial {trial.number}: 重複検出、別の解を探索中... (リトライ{retry_count+1})")
            study.tell(trial, state=optuna.trial.TrialState.PRUNED)
            total_skipped += 1
            trial = study.ask()
            config = set_cs_placement(trial)
            effective_key = get_effective_key(config)
            retry_count += 1

        if retry_count >= MAX_RETRY:
            print(f"⚠️  Trial {trial.number}: リトライ上限到達、そのまま実行")

        visited_effective_params.add(effective_key)
        batch_trials.append(trial)
        batch_configs.append(config)
        i += 1

    # パラメータ確認
    print("\n🔍 バッチ内パラメータ:")
    for i, (trial, config) in enumerate(zip(batch_trials, batch_configs)):
        active_cs = sum(1 for p in config['ports'] if p > 0)
        total_ports = sum(config['ports'])
        print(f"  Trial {trial.number} (ID:{i}): CS配置{active_cs}箇所, 合計{total_ports}ポート")

    # 環境構築
    max_workers_needed = outer_parallel * 9
    print(f"🖥️  必要Worker数: {max_workers_needed}")

    prepare_parallel_environment(batch_configs[0], parallel_count=outer_parallel, batch_size=9)

    # csListの更新とディレクトリ構造の確認
    for parallel in range(outer_parallel):
        for worker_id in range(1, 10):
            global_worker_id = parallel * 9 + worker_id
            cs_config = batch_configs[parallel]

            worker_paths = get_paths(global_worker_id)
            result_dir = worker_paths["result"]
            os.makedirs(result_dir, exist_ok=True)
            os.makedirs(os.path.join(result_dir, "emates"), exist_ok=True)
            os.makedirs(os.path.join(result_dir, "inst"), exist_ok=True)
            os.makedirs(os.path.join(result_dir, "opendss"), exist_ok=True)

            csList_file = worker_paths["csList"]
            update_cs_list(cs_config, csList_file)

    # 全タスクを生成（フラット化）
    all_tasks = create_all_tasks_flat(batch_trials, batch_configs, CONFIG)

    print(f"\n⚡ 合計{len(all_tasks)}タスクをフラット並列実行")
    print(f"   内訳: {outer_parallel}トライアル × 約{len(all_tasks)//outer_parallel}シナリオ/トライアル")

    # フラット並列実行
    cpu_cores = os.cpu_count()
    max_workers = min(cpu_cores if cpu_cores else 64, len(all_tasks))
    print(f"🖥️  CPU情報: {cpu_cores}コア, 使用Max Workers: {max_workers}")

    all_results = []

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        # 全タスクを投入
        future_to_task = {
            executor.submit(run_single_scenario_from_task, task): task
            for task in all_tasks
        }

        print(f"📊 {len(future_to_task)}個のタスクを実行中...")

        # 結果を収集
        for future in concurrent.futures.as_completed(future_to_task):
            task = future_to_task[future]
            try:
                result = future.result()
                all_results.append(result)
            except Exception as e:
                print(f"❌ Trial {task['trial_number']} (ID:{task['trial_id']}) エラー: {e}")
                import traceback
                traceback.print_exc()
                # エラーでも結果として記録
                all_results.append({
                    'trial_id': task['trial_id'],
                    'trial_number': task['trial_number'],
                    'scenario_type': task['scenario_type'],
                    'cost': float('inf'),
                    'error': str(e)
                })

    print(f"\n✅ 全タスク完了: {len(all_results)}件")

    # 結果をtrial_idでグルーピング・集約
    aggregated = aggregate_results_by_trial(all_results, batch_trials, batch_configs, CONFIG)

    # Optunaに登録
    print(f"\n📋 {len(aggregated)}個のトライアル結果をOptunaに登録中...")

    successful_registrations = 0

    for trial_id in sorted(aggregated.keys()):
        data = aggregated[trial_id]
        trial = data['trial']
        cs_config = data['cs_config']
        unified_cost = data['unified_cost']

        try:
            # user_attr設定
            trial.set_user_attr('failure_weight', CONFIG.failure_weight)
            trial.set_user_attr('objective_function', CONFIG.objective_function.name)
            trial.set_user_attr('normal_cost', data['normal_cost'])
            trial.set_user_attr('worst_failure_cost', data['worst_failure_cost'])
            trial.set_user_attr('unified_cost', unified_cost)

            # 故障時詳細
            if data['failure_details']['worst_details']:
                worst_details = data['failure_details']['worst_details']
                trial.set_user_attr('worst_failure_cs', worst_details.get('failure_cs_idx', -1))
                trial.set_user_attr('worst_wait_time_95p', worst_details.get('wait_time_95p', 0))

            # 平常時詳細
            if data['normal_details']:
                trial.set_user_attr('normal_wait_time_95p',
                                  data['normal_details'].get('wait_time_95p', 0))

            # CS配置情報
            active_cs_info = []
            for i, (csid, ports, cap) in enumerate(zip(cs_config['csids'], cs_config['ports'], cs_config['cap_kw'])):
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
            import traceback
            traceback.print_exc()
            continue

    # COMPLETE/PRUNED/総Trial数を表示
    total_trials_in_study = len(study.trials)
    complete_count = len([t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE])
    pruned_count = len([t for t in study.trials if t.state == optuna.trial.TrialState.PRUNED])
    print(f"✅ バッチ完了: {successful_registrations}件登録, 累計{total_skipped}件スキップ")
    print(f"   (総Trial: {total_trials_in_study}, COMPLETE: {complete_count}, PRUNED: {pruned_count})")

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
            pruned_trials_count = len([t for t in study.trials
                                       if t.state == optuna.trial.TrialState.PRUNED])
            print(f"📈 進捗更新: {completed_trials_count}/{config.total_trials} COMPLETE (総Trial: {len(study.trials)}, PRUNED: {pruned_trials_count})")

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
