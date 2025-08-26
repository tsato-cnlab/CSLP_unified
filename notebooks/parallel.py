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
import concurrent.futures
import threading
import time

warnings.filterwarnings("ignore")

# プロジェクトのルートディレクトリをパスに追加
project_root = os.path.abspath(os.path.join(os.getcwd()))
if project_root not in sys.path:
    sys.path.append(project_root)
print(f"プロジェクトルート: {project_root}")
    
from src.simulation.run_emates import only_run_emates
from src.simulation.data_load import save_data_to_pickle
from src.util.path_manager import get_paths
from src.util.optimization import *
from src.simulation.create_emates_env import prepare_parallel_environment

# =======================
# CSV処理とファイル管理
# =======================
def cleanup_opendss_csv_files(worker_id=None):
    """OpenDSSのCSVファイルをクリーンアップ"""
    paths = get_paths()
    base_dir = f"{paths['shikata']}_{worker_id}" if worker_id else paths['shikata']
    opendss_dir = os.path.join(base_dir, "result", "opendss")
    
    if os.path.exists(opendss_dir):
        csv_files = [f for f in os.listdir(opendss_dir) if f.endswith('.csv')]
        for csv_file in csv_files:
            try:
                os.remove(os.path.join(opendss_dir, csv_file))
            except Exception as e:
                print(f"⚠️ CSVファイル削除失敗 {csv_file}: {e}")
        if csv_files:
            print(f"🧹 Worker{worker_id}: {len(csv_files)}個のCSVファイルをクリーンアップ")
    return True

def validate_and_fix_csv_file(csv_path, default_value=0):
    """CSVファイルの-1値を修正"""
    if not os.path.exists(csv_path):
        return False
    try:
        df = pd.read_csv(csv_path)
        if (df == -1).any().any():
            df = df.replace(-1, default_value)
            df.to_csv(csv_path, index=False)
            print(f"✓ CSVファイルの-1値を修正: {csv_path}")
        return True
    except Exception as e:
        print(f"❌ CSV修正エラー {csv_path}: {e}")
        try:
            os.remove(csv_path)
        except:
            pass
        return False

def cleanup_worker_environments():
    """ワーカー環境をクリーンアップ"""
    paths = get_paths()
    shikata_dir = paths["shikata"]
    worker_dirs = [d for d in os.listdir(os.path.dirname(shikata_dir)) 
                   if d.startswith(os.path.basename(shikata_dir) + "_")]
    
    cleanup_count = 0
    for worker_dir in worker_dirs:
        full_path = os.path.join(os.path.dirname(shikata_dir), worker_dir)
        if os.path.isdir(full_path):
            try:
                shutil.rmtree(full_path)
                cleanup_count += 1
            except Exception as e:
                print(f"ワーカーディレクトリ削除失敗: {worker_dir} - {e}")
    
    if cleanup_count > 0:
        print(f"✓ {cleanup_count}個のワーカーディレクトリをクリーンアップ")
    return cleanup_count

# =======================
# シミュレーション実行
# =======================
def wait_for_simulation_completion(worker_id, timeout=300):
    """シミュレーション完了を待機"""
    paths = get_paths()
    base_dir = f"{paths['shikata']}_{worker_id}"
    vehicle_trip_path = os.path.join(base_dir, "result", "vehicleTrip.txt")
    
    start_time = time.time()
    while time.time() - start_time < timeout:
        if os.path.exists(vehicle_trip_path) and os.path.getsize(vehicle_trip_path) > 0:
            time.sleep(1)  # 書き込み完了を確実にする
            return True
        time.sleep(0.5)
    
    print(f"⚠️ Worker{worker_id}: シミュレーション完了待機がタイムアウト")
    return False

def run_single_worker_simulation(cs_config, failure_cs_idx, trial_number, save_dir, worker_id):
    """単一ワーカーでシミュレーション実行"""
    try:
        print(f"🚀 Worker{worker_id}: 故障CS{failure_cs_idx}処理開始")
        time.sleep(worker_id * 0.1)  # 競合回避
        
        # CSV クリーンアップ
        cleanup_opendss_csv_files(worker_id)
        
        # 故障情報作成（リトライ付き）
        for retry in range(3):
            try:
                create_failure_info_for_worker(cs_config, failure_cs_idx, worker_id, 
                                             FAILURE_TIME=FAILURE_TIME, file_write_lock=file_write_lock)
                break
            except Exception as e:
                if retry == 2:
                    raise e
                print(f"⚠️ Worker{worker_id} 故障情報作成リトライ {retry + 1}/3")
                time.sleep(1 + retry * 0.5)

        # シミュレーション実行（リトライ付き）
        start_time = time.time()
        for retry in range(3):
            try:
                only_run_emates(worker_id=worker_id)
                if wait_for_simulation_completion(worker_id, timeout=300):
                    break
                else:
                    print(f"⚠️ Worker{worker_id} 完了待機失敗 {retry + 1}/3")
            except Exception as e:
                print(f"⚠️ Worker{worker_id} 実行エラー {retry + 1}/3: {e}")
                
            if retry < 2:
                cleanup_opendss_csv_files(worker_id)
                time.sleep(2 + retry)
        else:
            raise Exception("シミュレーション実行に失敗")
        
        elapsed_time = time.time() - start_time
        print(f"✅ Worker{worker_id}: シミュレーション完了 ({elapsed_time:.1f}秒)")
        
        # CSV検証・修正
        validate_csv_files(worker_id)
        
        # 結果保存・計算
        return save_and_calculate_results(trial_number, failure_cs_idx, save_dir, worker_id)
        
    except Exception as e:
        print(f"💥 Worker{worker_id}: 故障CS{failure_cs_idx}で致命的エラー: {e}")
        try:
            cleanup_opendss_csv_files(worker_id)
        except:
            pass
        
        return {
            'failure_cs_idx': failure_cs_idx,
            'worker_id': worker_id,
            'cost': float('inf'),
            'wait_time_95p': float('inf'),
            'error': str(e)
        }

def validate_csv_files(worker_id):
    """ワーカーのCSVファイルを検証・修正"""
    paths = get_paths()
    base_dir = f"{paths['shikata']}_{worker_id}"
    opendss_dir = os.path.join(base_dir, "result", "opendss")
    
    if os.path.exists(opendss_dir):
        csv_files = [f for f in os.listdir(opendss_dir) if f.endswith('.csv')]
        for csv_file in csv_files:
            csv_path = os.path.join(opendss_dir, csv_file)
            validate_and_fix_csv_file(csv_path, default_value=0)

def save_and_calculate_results(trial_number, failure_cs_idx, save_dir, worker_id):
    """結果保存とコスト計算"""
    results_filename = f"trial_{trial_number}_failureCS_{failure_cs_idx}_worker_{worker_id}.pkl"
    results_filepath = os.path.join(save_dir, results_filename)
    save_data_to_pickle(worker_id=worker_id, filename=results_filepath)
    
    eval_costs, _ = evaluation_total_costs(results_filepath)
    wait_time_95p = calculate_95percentile_wait_time(results_filepath)
    
    print(f"🎉 Worker{worker_id}: コスト={eval_costs:.2f}万円, 待ち時間={wait_time_95p:.2f}秒")
    
    return {
        'failure_cs_idx': failure_cs_idx,
        'worker_id': worker_id,
        'cost': eval_costs,
        'wait_time_95p': wait_time_95p,
        'results_filepath': results_filepath
    }

# =======================
# 並列処理制御
# =======================
def create_failure_scenario_parallel(cs_config, trial, max_workers, parallel_count, combination_id):
    """故障シナリオを並列で処理"""
    installed_cs_indices = [i for i, ports in enumerate(cs_config['ports']) if ports > 0]
    
    if len(installed_cs_indices) == 0:
        return float('inf')
    
    print(f"\n=== Trial {trial.number} (組み合わせ{combination_id + 1}): 故障シナリオ並列処理開始 ===")    
    
    # 組み合わせごとに固定で8個のWorkerを割り当て
    worker_start = combination_id * 8 + 1  # 1-8, 9-16, 17-24, 25-32
    worker_end = worker_start + 7
    print(f"Worker割り当て: {worker_start}-{worker_end}, 設置CS数: {len(installed_cs_indices)}")

    # 並列実行
    start_time = time.time()
    max_concurrent = min(8, len(installed_cs_indices))

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        future_to_scenario = {}
        
        for i, failure_cs_idx in enumerate(installed_cs_indices):
            worker_id = worker_start + (i % 8)  # 組み合わせ内で8個のWorkerを循環利用
            future = executor.submit(
                run_single_worker_simulation,
                cs_config, failure_cs_idx, trial.number, SAVE_DIR, worker_id
            )
            future_to_scenario[future] = failure_cs_idx
            print(f"故障シナリオCS{failure_cs_idx} → Worker{worker_id}に投入")
            
        # 結果収集
        results = collect_parallel_results(future_to_scenario, installed_cs_indices)
    
    elapsed_time = time.time() - start_time
    print(f"並列処理完了（{elapsed_time:.2f}秒）")
    
    return process_results(results)

def collect_parallel_results(future_to_scenario, installed_cs_indices):
    """並列実行の結果を収集"""
    results = []
    completed = 0
    
    for future in concurrent.futures.as_completed(future_to_scenario):
        failure_cs_idx = future_to_scenario[future]
        try:
            result = future.result(timeout=3600)
            results.append(result)
            completed += 1
            
            print(f"✓ [{completed}/{len(installed_cs_indices)}] "
                    f"故障CS{failure_cs_idx}完了: "
                    f"コスト={result['cost']:.2f}万円")
        except Exception as e:
            print(f"❌ 故障CS{failure_cs_idx}の処理でエラー: {e}")
            results.append({
                'failure_cs_idx': failure_cs_idx,
                'cost': float('inf'),
                'wait_time_95p': float('inf'),
                'error': str(e)
            })
    
    return results

def process_results(results):
    """結果を処理して最悪ケースを返す"""
    valid_results = [r for r in results if r['cost'] != float('inf')]
    
    if not valid_results:
        print("❌ 有効な結果がありません")
        return float('inf')
    
    worst_cost = max(r['cost'] for r in valid_results)
    print(f"📊 有効シナリオ数: {len(valid_results)}/{len(results)}")
    print(f"📊 最悪ケースコスト: {worst_cost:.2f}万円")
    
    # ワーストケース以外を削除
    delete_non_worst_results(results, worst_cost)
    return worst_cost

def delete_non_worst_results(results, worst_cost):
    """最悪ケース以外の結果ファイルを削除"""
    for result in results:
        if result['cost'] != worst_cost and 'results_filepath' in result:
            try:
                os.remove(result['results_filepath'])
                print(f"削除: {result['results_filepath']}")
            except Exception as e:
                print(f"削除失敗: {result['results_filepath']} - {e}")

# =======================
# 環境構築とバッチ実行
# =======================
def setup_worker_environment(cs_sample, max_batch, parallel_count):
    """32個のワーカー環境を構築"""
    print("🔧 32個のワーカー環境を構築中...")
    for retry in range(3):
        try:
            prepare_parallel_environment(cs_sample, max_batch, parallel_count)
            time.sleep(0.5 + retry * 0.2)
            print(f"✓ 32個のワーカー環境を構築完了")
            return True
        except Exception as e:
            print(f"⚠️ 環境構築リトライ {retry + 1}/3: {e}")
            if retry == 2:
                print("❌ 環境構築に失敗しました")
                return False
    return False

def execute_batch_parallel(batch_trials, batch_params, max_batch, parallel_count):
    """バッチを並列実行"""
    with concurrent.futures.ProcessPoolExecutor(max_workers=len(batch_trials)) as executor:
        futures = [
            executor.submit(create_failure_scenario_parallel, 
                          params, trial, max_batch, parallel_count, combination_id)
            for combination_id, (trial, params) in enumerate(zip(batch_trials, batch_params))
        ]
        return [f.result() for f in futures]

def run_random_search_phase(study, n_startup_trials, parallel_count, max_batch, csids):
    """ランダム探索フェーズを実行"""
    current_completed = len(study.trials)
    if current_completed >= n_startup_trials:
        print("ランダム探索フェーズは既に完了しています。")
        return
    
    remaining_trials = n_startup_trials - current_completed
    print(f"🎲 ランダム探索開始: 残り{remaining_trials}回")
    
    batches_needed = (remaining_trials + parallel_count - 1) // parallel_count
    
    for batch_idx in tqdm(range(batches_needed), desc="Random Search Batches"):
        study = load_or_create_study()
        current_completed = len(study.trials)
        
        if current_completed >= n_startup_trials:
            break
        
        actual_parallel_count = min(parallel_count, n_startup_trials - current_completed)
        
        # バッチ準備
        batch_params = [generate_random_params(csids) for _ in range(actual_parallel_count)]
        
        # 環境構築・実行
        cleanup_worker_environments()
        time.sleep(1)
        
        if not setup_worker_environment(batch_params[0], max_batch, parallel_count):
            continue
        
        # トライアル作成・実行
        batch_trials = [study.ask() for _ in batch_params]
        results = execute_batch_parallel(batch_trials, batch_params, max_batch, parallel_count)
        
        # DB保存
        for trial, result in zip(batch_trials, results):
            study.tell(trial, result)
        
        print(f"ランダムバッチ {batch_idx + 1}/{batches_needed} 完了: {len(results)}件")

def run_tpe_search_phase(study, n_trials, parallel_count, max_batch):
    """TPE探索フェーズを実行"""
    current_completed = len(study.trials)
    if current_completed >= n_trials:
        print("TPE探索フェーズも完了しています。")
        return
    
    remaining_trials = n_trials - current_completed
    print(f"🧠 TPE探索開始: 残り{remaining_trials}回")
    
    batches_needed = (remaining_trials + parallel_count - 1) // parallel_count
    
    for batch_idx in tqdm(range(batches_needed), desc="TPE Search Batches"):
        study = load_or_create_study()
        current_completed = len(study.trials)
        
        if current_completed >= n_trials:
            break
        
        actual_parallel_count = min(parallel_count, n_trials - current_completed)
        
        # TPEバッチ準備
        batch_trials = [study.ask() for _ in range(actual_parallel_count)]
        batch_params = [set_cs_placement(trial, worker_id=None) for trial in batch_trials]
        
        # 環境構築・実行
        cleanup_worker_environments()
        time.sleep(1)
        
        if not setup_worker_environment(batch_params[0], max_batch, parallel_count):
            continue
        
        results = execute_batch_parallel(batch_trials, batch_params, max_batch, parallel_count)
        
        # DB保存
        for trial, result in zip(batch_trials, results):
            study.tell(trial, result)
        
        print(f"TPEバッチ {batch_idx + 1}/{batches_needed} 完了: {len(results)}件")

# =======================
# メイン実行関数
# =======================
def run_multi_batch_parallel_failure_optimization(n_trials=250, parallel_count=4, max_batch=8, random_phase_ratio=0.25):
    """メイン最適化実行関数"""
    print("🧹 ワーカー環境のクリーンアップ中...")
    cleanup_worker_environments()
    time.sleep(2)

    paths = get_paths()
    cslist_file = paths['csList']
    with open(cslist_file, 'r') as f:
        cslist_data = f.readlines()
        csids = [int(line.split(',')[0]) for line in cslist_data 
                if line.strip() and line.split(',')[0].isdigit()]

    n_startup_trials = int(n_trials * random_phase_ratio)
    study = load_or_create_study()
    completed_trials = len(study.trials)
    print(f"📊 DB進捗確認: {completed_trials}/{n_trials} 完了")
    
    if completed_trials >= n_trials:
        print("✅ すべてのトライアルが完了しています。")
        manage_pkl_files_after_optimization(study, SAVE_DIR)
        return
    
    try:
        # ランダム探索フェーズ
        run_random_search_phase(study, n_startup_trials, parallel_count, max_batch, csids)
        
        # TPE探索フェーズ
        run_tpe_search_phase(study, n_trials, parallel_count, max_batch)
        
    except Exception as e:
        print(f"❌ 最適化中にエラー: {e}")
        raise e
    finally:
        cleanup_worker_environments()

    print("🎉 すべての最適化が完了しました。")
    manage_pkl_files_after_optimization(study, SAVE_DIR)

# =======================
# ユーティリティ関数
# =======================
def generate_random_params(csids):
    """ランダムなCS配置パラメータを生成"""
    import random
    cs_config = {'csids': [], 'ports': [], 'cap_kw': []}
    for csid in csids:
        ports = random.randint(0, 4)
        capacity = random.choice([50, 100]) if ports > 0 else 90
        cs_config['csids'].append(csid)
        cs_config['ports'].append(ports)
        cs_config['cap_kw'].append(capacity)
    return cs_config

def load_or_create_study():
    """Optuna Studyを読み込みまたは作成"""
    db_path = os.path.join(SAVE_DIR, 'optuna_failure_study_parallel.db')
    db_url = f"sqlite:///{db_path}"
    study_name = "cs_failure_optimization_parallel"
    try:
        study = optuna.load_study(study_name=study_name, storage=db_url)
    except KeyError:
        study = optuna.create_study(
            directions=['minimize'],
            study_name=study_name,
            storage=db_url,
            sampler=optuna.samplers.TPESampler(seed=42)
        )
    return study

def manage_pkl_files_after_optimization(study, save_dir):
    """最適化完了後のpklファイル管理（ベストのみ保持）"""
    print("\n=== 最適化完了後のファイル管理 ===")
    save_path = Path(save_dir)
    pkl_files = [f for f in os.listdir(save_path) if f.endswith('.pkl')]
    
    if not pkl_files:
        print("pklファイルが見つかりません。")
        return
    
    best_trial_number = study.best_trial.number
    print(f"ベストtrial: {best_trial_number}")
    
    # ベストファイルを特定
    best_files = [f for f in pkl_files if f.startswith(f"trial_{best_trial_number}_")]
    trials_to_keep = set(best_files)
    
    if not trials_to_keep:
        print(f"⚠️ ベストtrial {best_trial_number} のファイルが見つかりません。")
        return
    
    files_to_delete = set(pkl_files) - trials_to_keep
    print(f"保持: {len(trials_to_keep)}件, 削除: {len(files_to_delete)}件")
    
    # バックアップディレクトリに移動
    backup_dir = save_path / "backup_deleted_trials"
    backup_dir.mkdir(exist_ok=True)
    
    moved_count = 0
    for file_name in files_to_delete:
        try:
            shutil.move(str(save_path / file_name), str(backup_dir / file_name))
            moved_count += 1
        except Exception as e:
            print(f"ファイル移動失敗 {file_name}: {e}")
    
    print(f"✅ {moved_count}個のファイルをバックアップに移動完了")

# =======================
# 実行部分
# =======================
if __name__ == "__main__":
    from multiprocessing import Lock

    file_write_lock = Lock()
    current_time = datetime.now().strftime('%Y%m%d_%H%M')
    SAVE_DIR = f'{current_time}_1DAY'
    SAVE_DIR = '20250826_0924_1DAY'
    os.makedirs(SAVE_DIR, exist_ok=True)
    FAILURE_FLAG = True
    FAILURE_TIME = list(range(0, 25))
    
    run_multi_batch_parallel_failure_optimization(
        n_trials=250, 
        parallel_count=4, 
        max_batch=8, 
        random_phase_ratio=0.25
    )