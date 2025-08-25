import sys
import os
from datetime import datetime
import json
import pickle
import numpy as np
import pandas as pd
import optuna
from tqdm import tqdm
import matplotlib.pyplot as plt
import japanize_matplotlib
import shutil
from pathlib import Path
import warnings
warnings.filterwarnings("ignore")

# プロジェクトのルートディレクトリをパスに追加
project_root = os.path.abspath(os.path.join(os.getcwd(), '..'))
if project_root not in sys.path:
    sys.path.append(project_root)
    
from src.simulation.run_emates import only_run_emates
from src.simulation.data_load import save_data_to_pickle
from src.util.path_manager import get_paths
from src.util.optimization import *

import concurrent.futures
import threading
import time
from src.simulation.create_emates_env import prepare_parallel_environment

current_time = datetime.now().strftime('%Y%m%d_%H%M')
SAVE_DIR = current_time
SAVE_DIR = '20250816_1051_2hour_fail'
os.makedirs(SAVE_DIR, exist_ok=True)
FAILURE_FLAG = True
FAILURE_TIME = [15]
def create_failure_scenario_parallel(cs_config: dict, trial, max_workers=None):
    """故障シナリオを並列で処理する統合関数"""
    
    # 1. 設置されているCSのインデックスを取得
    installed_cs_indices = [i for i, ports in enumerate(cs_config['ports']) if ports > 0]
    
    if len(installed_cs_indices) == 0:
        return float('inf'), float('inf')
    
    print(f"\n=== Trial {trial.number}: 故障シナリオ並列処理開始 ===")
    print(f"設置CS数: {len(installed_cs_indices)}, 並列シナリオ数: {len(installed_cs_indices)}")
    
    # 2. 並列数を決定（故障シナリオ数と同じ）
    parallel_count = len(installed_cs_indices)
    if max_workers:
        parallel_count = min(parallel_count, max_workers)
    
    # 3. 並列環境を構築（各ワーカーフォルダを作成）
    print("並列環境構築中...")
    prepare_parallel_environment(cs_config, parallel_count)
    print(f"✓ {parallel_count}個のワーカー環境を構築完了")
    
    # 4. 各故障シナリオを並列で実行
    start_time = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_count) as executor:
        # 各故障シナリオのタスクを投入
        future_to_scenario = {}
        
        for worker_id, failure_cs_idx in enumerate(installed_cs_indices, 1):
            future = executor.submit(
                process_single_failure_scenario_with_worker,
                cs_config, failure_cs_idx, trial.number, SAVE_DIR, worker_id
            )
            future_to_scenario[future] = failure_cs_idx
            # print(f"故障シナリオCS{failure_cs_idx} → Worker{worker_id}に投入")
        
        # 結果を順次収集
        results = []
        completed = 0
        
        for future in concurrent.futures.as_completed(future_to_scenario):
            failure_cs_idx = future_to_scenario[future]
            
            try:
                result = future.result(timeout=3600)  # 1時間タイムアウト
                results.append(result)
                completed += 1
                
                print(f"✓ [{completed}/{len(installed_cs_indices)}] "
                      f"故障CS{failure_cs_idx}完了: "
                      f"コスト={result['cost']:.2f}万円, "
                      f"95%待ち時間={result['wait_time_95p']:.2f}秒")
                
            except concurrent.futures.TimeoutError:
                print(f"❌ 故障CS{failure_cs_idx}がタイムアウト")
                results.append({
                    'failure_cs_idx': failure_cs_idx,
                    'cost': float('inf'),
                    'wait_time_95p': float('inf'),
                    'error': 'timeout'
                })
            except Exception as e:
                print(f"❌ 故障CS{failure_cs_idx}でエラー: {e}")
                results.append({
                    'failure_cs_idx': failure_cs_idx,
                    'cost': float('inf'),
                    'wait_time_95p': float('inf'),
                    'error': str(e)
                })
    
    end_time = time.time()
    print(f"\n並列処理完了（{end_time - start_time:.2f}秒）")
    
    # 5. 結果の集計
    valid_results = [r for r in results if r['cost'] != float('inf')]
    
    if not valid_results:
        print("❌ 有効な結果がありません")
        return float('inf')
    
    # 最悪ケースの抽出
    worst_cost = max(r['cost'] for r in valid_results)
    worst_wait_time = max(r['wait_time_95p'] for r in valid_results)
    
    print(f"📊 結果サマリー:")
    print(f"  有効シナリオ数: {len(valid_results)}/{len(results)}")
    print(f"  最悪ケースコスト: {worst_cost:.2f}万円")
    print(f"  最悪ケース95%待ち時間: {worst_wait_time:.2f}秒")
    # ワーストケース以外を削除
    for result in results:
        if result['cost'] != worst_cost:
            # 該当ワーカーの結果ファイルを削除
            if 'results_filepath' in result:
                try:
                    os.remove(result['results_filepath'])
                    print(f"削除: {result['results_filepath']}")
                except Exception as e:
                    print(f"削除失敗: {result['results_filepath']} - {e}")

    return worst_cost

def process_single_failure_scenario_with_worker(cs_config, failure_cs_idx, trial_number, save_dir, worker_id):
    """指定されたワーカーで単一の故障シナリオを処理"""
    
    try:
        
        # 1. 指定されたワーカー用に故障情報を作成
        create_failure_info_for_worker(cs_config, failure_cs_idx, worker_id, FAILURE_TIME=FAILURE_TIME)
        
        # 2. 該当ワーカーでシミュレーション実行（単一ワーカーのみ）
        only_run_emates(worker_id=worker_id)
        
        # 3. 結果の保存
        results_filename = f"trial_{trial_number}_worker_{worker_id}.pkl"
        results_filepath = os.path.join(save_dir, results_filename)
        save_data_to_pickle(worker_id=worker_id, filename=results_filepath)
        
        # 4. コスト計算
        eval_costs, _ = evaluation_total_costs(results_filepath)
        
        
        # 5. 95パーセンタイル待ち時間計算
        wait_time_95p = calculate_95percentile_wait_time(results_filepath)
        
        return {
            'failure_cs_idx': failure_cs_idx,
            'worker_id': worker_id,
            'cost': eval_costs,
            'wait_time_95p': wait_time_95p,
            'results_filepath': results_filepath
        }
        
    except Exception as e:
        print(f"❌ Worker{worker_id}で故障CS{failure_cs_idx}の処理中にエラー: {e}")
        return {
            'failure_cs_idx': failure_cs_idx,
            'worker_id': worker_id,
            'cost': float('inf'),
            'wait_time_95p': float('inf'),
            'error': str(e)
        }

# 並列処理版の目的関数
def cs_placement_objective_failure_parallel(trial) -> tuple:
    """並列処理版：故障時のみを考慮した多目的最適化の目的関数"""
    
    # 1. OptunaによるCS配置の提案
    cs_config = set_cs_placement(trial)
    
    # 2. CS配置の妥当性チェック
    if not check_cs_placement(cs_config):
        print("CS配置が不適切です。最低2箇所の充電ステーションを設置してください。")
        return float('inf')
    
    # 3. 並列故障シナリオ実行
    worst_failure_cost = create_failure_scenario_parallel(
        cs_config, trial, max_workers=8  # 最大4並列に制限
    )
    
    return worst_failure_cost

def manage_pkl_files_after_optimization(study, save_dir):
    """最適化完了後のpklファイル管理（ベストトライアルのみ保持）"""
    print("\n=== 最適化完了後のファイル管理（ベストのみ保持）===")
    
    save_path = Path(save_dir)
    pkl_files = [f for f in os.listdir(save_path) if f.endswith('.pkl')]
    
    if not pkl_files:
        print("pklファイルが見つかりません。")
        return
    
    # ベストtrialを特定
    best_trial_number = study.best_trial.number
    print(f"ベストtrial: {best_trial_number}")
    
    # 保持するファイルを選定（ベストのみ）
    trials_to_keep = set()
    
    # ベストtrialのファイルパターンを検索
    best_files = [f for f in pkl_files if f.startswith(f"trial_{best_trial_number}_") or f == f"trial_{best_trial_number}.pkl"]
    
    for best_file in best_files:
        trials_to_keep.add(best_file)
        print(f"保持ファイル: {best_file}")
    
    if len(trials_to_keep) == 0:
        print(f"⚠️  ベストtrial {best_trial_number} に対応するファイルが見つかりません。")
        print("利用可能なファイル:")
        for f in pkl_files[:10]:  # 最初の10個を表示
            print(f"  {f}")
        return
    
    # 削除対象を特定
    files_to_delete = set(pkl_files) - trials_to_keep
    
    # 統計情報を表示
    print(f"\n総ファイル数: {len(pkl_files)}")
    print(f"保持ファイル数: {len(trials_to_keep)}")
    print(f"削除対象ファイル数: {len(files_to_delete)}")
    
    if len(files_to_delete) == 0:
        print("削除対象のファイルはありません。")
        return
    
    # ファイルサイズの分析
    keep_size = 0
    delete_size = 0
    
    for file_name in trials_to_keep:
        file_path = save_path / file_name
        if file_path.exists():
            keep_size += file_path.stat().st_size
    
    for file_name in files_to_delete:
        file_path = save_path / file_name
        if file_path.exists():
            delete_size += file_path.stat().st_size
    
    print(f"保持データサイズ: {keep_size / (1024**2):.1f} MB")
    print(f"削除データサイズ: {delete_size / (1024**2):.1f} MB")
    print(f"削除による節約: {delete_size / (keep_size + delete_size) * 100:.1f}%")
    
    # 自動的にバックアップディレクトリに移動
    backup_dir = save_path / "backup_deleted_trials"
    backup_dir.mkdir(exist_ok=True)
    
    moved_count = 0
    for file_name in files_to_delete:
        file_path = save_path / file_name
        backup_path = backup_dir / file_name
        
        if file_path.exists():
            try:
                shutil.move(str(file_path), str(backup_path))
                moved_count += 1
            except Exception as e:
                print(f"ファイル移動失敗 {file_name}: {e}")
    # 同一トライアルに対して複数のファイルがある場合は、スコアが最も低いものを残す
    
    
    print(f"\n✅ {moved_count}個のファイルをバックアップディレクトリに移動しました。")
    print(f"バックアップ先: {backup_dir}")
    print(f"💾 ベストトライアル {best_trial_number} のファイルのみ保持されました。")
    
    # 残りファイルサイズを確認
    remaining_size = sum(f.stat().st_size for f in save_path.glob("*.pkl")) / (1024**2)
    print(f"残りのpklファイルサイズ: {remaining_size:.1f} MB")

# 並列処理版の最適化実行
def run_optuna_failure_optimization_parallel(n_trials=150, timeout = 60*60*24):
    """並列処理版故障時最適化の実行"""
    db_path = os.path.join(SAVE_DIR, 'optuna_failure_study_parallel.db')
    db_url = f"sqlite:///{db_path}"
    study_name = "cs_failure_optimization_parallel"
    
    try:
        study = optuna.load_study(study_name=study_name, storage=db_url)
        print(f"既存の並列処理Studyを読み込みました（トライアル数: {len(study.trials)}）")
    except KeyError:
        study = optuna.create_study(
            directions=['minimize'],
            study_name=study_name, 
            storage=db_url
        )
        print("新しい並列処理Studyを作成しました")
    
    print(f"\n🚀 並列故障シナリオ最適化を開始します")
    print(f"トライアル数: {n_trials}")
    print(f"各トライアルで故障シナリオを並列実行します")
    
    # 最適化実行
    # ✅ --- tqdmによるプログレスバーのセットアップ ---
    with tqdm(total=n_trials, desc="Optimization Progress") as pbar:
        # 各トライアル完了時にプログレスバーを更新するコールバック関数
        def progress_bar_callback(study, trial):
            pbar.update(1)
        study.optimize(cs_placement_objective_failure_parallel, n_trials=n_trials,
                       callbacks=[progress_bar_callback], timeout=timeout)
    # ✅ --- プログレスバーのセットアップここまで ---
    manage_pkl_files_after_optimization(study, SAVE_DIR)

if __name__ == "__main__":
    run_optuna_failure_optimization_parallel()