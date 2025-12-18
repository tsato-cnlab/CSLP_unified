import optuna
import sys
import os
from datetime import datetime
import json
import pickle
import numpy as np
import pandas as pd
import shutil
from pathlib import Path
from multiprocessing import Pool, Lock
import time

# プロジェクトのルートディレクトリをパスに追加
project_root = os.path.abspath(os.path.join(os.getcwd(), '..'))
if project_root not in sys.path:
    sys.path.append(project_root)

from src.simulation.run_emates import only_run_emates
from src.simulation.data_load import save_data_to_pickle
from src.util.path_manager import get_paths
# 新しいモジュール構成に対応（設計意図: 明示的インポートで依存関係を明確化）
from src.util.cost_calculator import evaluation_total_costs
from src.util.convergence_checker import check_convergence
from src.util.file_manager import cleanup_worker_environments, manage_pkl_files_after_optimization
from src.util.optimization import (
    check_cs_placement, set_cs_placement, update_cs_list
)
from src.simulation.create_emates_env import prepare_parallel_environment

# ファイル書き込み用のロック
file_write_lock = Lock()

# グローバル変数（multiprocessing用）
SAVE_DIR = None
T_HOUR = 26

def init_worker_globals(save_dir):
    """ワーカープロセス初期化用の関数"""
    global SAVE_DIR
    SAVE_DIR = save_dir

def run_single_optimization_trial(task_data):
    """単一の最適化トライアルを実行（multiprocessing用）"""
    cs_config, trial_number, worker_id, save_dir = task_data

    print(f"� Worker{worker_id}: Trial {trial_number} 開始")

    # 制約チェック
    if not check_cs_placement(cs_config):
        print(f"❌ Worker{worker_id}: 制約違反")
        return float('inf')
    installed_locations = [i for i, port in enumerate(cs_config['ports']) if port > 0]
    if (len(installed_locations) != 5):  # 最低5箇所は設置
        print(f"❌ Worker{worker_id}: 5箇所設置制約違反")
        return float('inf')
    try:
        # CS設定をファイルに書き込み
        csList_file = get_paths(worker_id)["csList"]
        update_cs_list(cs_config, csList_file)

        # シミュレーション実行
        if T_HOUR is None:
            only_run_emates(worker_id=worker_id)
        else:
            only_run_emates(worker_id=worker_id, HOUR=T_HOUR)

        # 結果保存とコスト計算
        results_filename = f"trial_{trial_number}.pkl"
        results_filepath = os.path.join(save_dir, results_filename)
        save_data_to_pickle(filename=results_filepath, worker_id=worker_id)

        evaluation_cost, _ = evaluation_total_costs(result_file=results_filepath)

        print(f"✅ Worker{worker_id}: Trial {trial_number} 完了, コスト={evaluation_cost:.2f}万円")
        return evaluation_cost

    except Exception as e:
        print(f"� Worker{worker_id}: Trial {trial_number} でエラー: {e}")
        return float('inf')

def run_parallel_optimization_batch(study, batch_size):
    """並列バッチ最適化を実行（multiprocessing版）"""
    print(f"\n🔄 {batch_size}個のトライアルを並列実行中...")

    # バッチ用のトライアルを生成
    batch_trials = [study.ask() for _ in range(batch_size)]

    # 各ワーカー用のパラメータを個別に生成（重複回避）
    batch_configs = []
    for i, trial in enumerate(batch_trials):
        config = set_cs_placement(trial)
        batch_configs.append(config)

    # パラメータ確認（情報表示のみ）
    print("\n🔍 バッチ内パラメータ:")
    param_hashes = set()
    duplicate_count = 0

    for i, (trial, config) in enumerate(zip(batch_trials, batch_configs)):
        worker_id = i + 1
        # パラメータの重複チェック用ハッシュ値を生成
        param_str = str(sorted(trial.params.items()))
        param_hash = hash(param_str)

        if param_hash in param_hashes:
            duplicate_count += 1
            print(f"  ⚠️ Trial {trial.number} (Worker{worker_id}): 重複パラメータ検出!")
        else:
            param_hashes.add(param_hash)

        # パラメータの詳細表示（最初の3つのパラメータ）
        print(f"  Trial {trial.number} (Worker{worker_id}): {dict(list(trial.params.items())[:3])}...")

        # CS配置の要約も表示
        active_cs = sum(1 for p in config['ports'] if p > 0)
        total_ports = sum(config['ports'])
        print(f"    └─ CS配置: {active_cs}箇所, 合計{total_ports}ポート")

    if duplicate_count > 0:
        print(f"❌ 警告: {duplicate_count}件の重複パラメータが検出されました")
    else:
        print("✅ すべてのパラメータが一意です")

    # ワーカー環境のクリーンアップ
    cleanup_worker_environments()
    time.sleep(1)  # クリーンアップ完了を待つ

    # 並列環境の準備（全ワーカー分）
    prepare_parallel_environment(batch_configs[0], batch_size, 1)

    # multiprocessingで並列実行
    print("\n⚡ multiprocessingで並列実行開始...")

    # タスクデータを準備
    task_data_list = []
    for i, (trial, config) in enumerate(zip(batch_trials, batch_configs)):
        worker_id = i + 1
        task_data = (config, trial.number, worker_id, SAVE_DIR)
        task_data_list.append(task_data)

    # CPUコア数に基づく最適なプロセス数
    cpu_cores = os.cpu_count()
    optimal_processes = min(batch_size, cpu_cores)
    print(f"🖥️  CPU情報: {cpu_cores}コア, 使用プロセス数: {optimal_processes}")

    # multiprocessingで並列実行
    with Pool(processes=optimal_processes, initializer=init_worker_globals, initargs=(SAVE_DIR,)) as pool:
        results = pool.map(run_single_optimization_trial, task_data_list)

    # 結果をOptunaのstudyに登録
    for i, (trial, result) in enumerate(zip(batch_trials, results)):
        study.tell(trial, result)
        print(f"✅ Trial {trial.number}: {result:.6f}")

    print(f"✅ バッチ完了: {len(results)}件の結果をstudyに登録")
    return len(results)



def run_optimization_with_parallel_batches(study, total_trials, batch_size, timeout,
                                         convergence_patience, convergence_threshold):
    """並列バッチ処理による最適化実行（収束判定付き）"""
    print(f"\n🎯 並列最適化開始: 目標{total_trials}トライアル, バッチサイズ{batch_size}")
    print(f"🔍 収束判定: {convergence_patience}トライアル連続で改善率{convergence_threshold*100:.2f}%未満で終了")

    current_trials = len(study.trials)
    remaining_trials = max(0, total_trials - current_trials)

    if remaining_trials == 0:
        print("✅ すべてのトライアルが完了済みです")
        return

    print(f"📊 現在の進捗: {current_trials}/{total_trials}")
    print(f"🔄 残り{remaining_trials}トライアルを実行します")

    # バッチ数を計算
    batches_needed = (remaining_trials + batch_size - 1) // batch_size

    try:
        for batch_idx in range(batches_needed):
            current_trials = len(study.trials)
            if current_trials >= total_trials:
                print("✅ 目標トライアル数に到達しました")
                break

            # 収束判定
            if current_trials >= convergence_patience:
                is_converged, convergence_msg = check_convergence(
                    study, patience=convergence_patience, min_improvement=convergence_threshold
                )

                print(f"🔍 {convergence_msg}")

                if is_converged:
                    print(f"🛑 収束により最適化を終了します (Trial {current_trials})")
                    print(f"📊 最終最適値: {study.best_value:.2f}万円")
                    break

            actual_batch_size = min(batch_size, total_trials - current_trials)
            print(f"\n--- バッチ {batch_idx + 1}/{batches_needed} (サイズ: {actual_batch_size}) ---")

            completed = run_parallel_optimization_batch(study, actual_batch_size)

            current_trials = len(study.trials)
            print(f"📈 進捗更新: {current_trials}/{total_trials} 完了")

    except KeyboardInterrupt:
        print("\n⚠️ ユーザーによる中断")
    except Exception as e:
        print(f"❌ 最適化中にエラー: {e}")
    finally:
        cleanup_worker_environments()
        print("🧹 最終クリーンアップ完了")

    print(f"🎉 最適化完了: {len(study.trials)}トライアル実行済み")


# 最適化実行
if __name__ == "__main__":
    # SAVEDIRをグローバル変数として初期化
    current_time = datetime.now().strftime('%Y%m%d_%H%M')
    SAVE_DIR = f"/srv/samba/share/output/{current_time}_5locations"
    # SAVE_DIR = "20250827_1335"  # ここは適宜変更してください
    os.makedirs(SAVE_DIR, exist_ok=True)

    # 並列処理設定
    BATCH_SIZE = 8          # 並列実行数（Workerの数）
    TOTAL_TRIALS = 1000     # 総トライアル数を増加（より多くの探索）
    TIMEOUT = 60 * 60 * 24  # 24時間タイムアウト

    # 収束判定設定
    CONVERGENCE_PATIENCE = 100       # 収束判定のトライアル数（連続30回小改善で収束）
    CONVERGENCE_THRESHOLD = 0.001   # 改善率の閾値（0.1%）

    print(f"📂 結果保存先: {SAVE_DIR}")
    print(f"⚙️ 並列設定: バッチサイズ{BATCH_SIZE}, 目標{TOTAL_TRIALS}トライアル")
    print(f"🔍 収束判定: {CONVERGENCE_PATIENCE}トライアル連続で改善率{CONVERGENCE_THRESHOLD*100:.1f}%未満で終了")

    # SQLiteデータベースを使用したStudy管理
    db_path = os.path.join(SAVE_DIR, 'optuna_study.db')
    db_url = f"sqlite:///{db_path}"
    study_name = "cs_optimization"

    # 既存または新規Study作成
    start_time = time.time()
    try:
        study = optuna.load_study(study_name=study_name, storage=db_url)
        print(f"📊 既存Studyをロードしました: {len(study.trials)}トライアル済み")
        if len(study.trials) > 0:
            print(f"🏆 現在の最適値: {study.best_value:.2f}")
    except KeyError:
        study = optuna.create_study(
            direction='minimize',
            study_name=study_name,
            storage=db_url,
            sampler=optuna.samplers.TPESampler(
                seed=42,
                n_startup_trials=max(50, BATCH_SIZE * 5),  # バッチサイズに応じたランダム探索期間
                n_ei_candidates=max(24, BATCH_SIZE * 3),    # バッチサイズに応じた候補数
                constant_liar=True,                         # 並列処理対応：仮の値で並列評価中の重複を回避
                multivariate=True,                          # 多変量TPE（パラメータ間の相関を考慮）
                group=True,                                 # グループ化による効率的な探索
                warn_independent_sampling=True              # 独立サンプリングの警告を有効化
            )
        )
        print("🆕 新しいStudyを作成しました")

    # 並列バッチ最適化実行
    run_optimization_with_parallel_batches(
        study,
        total_trials=TOTAL_TRIALS,
        batch_size=BATCH_SIZE,
        timeout=TIMEOUT,
        convergence_patience=CONVERGENCE_PATIENCE,
        convergence_threshold=CONVERGENCE_THRESHOLD
    )

    # 最適化完了後のファイル管理
    manage_pkl_files_after_optimization(study, SAVE_DIR)
    elapsed_time = time.time() - start_time
    # 最終結果表示
    print(f"\n=== 最適化結果サマリー ===")
    print(f"🏆 最適値: {study.best_value:.2f}万円")
    print(f"📋 最適パラメータ: {study.best_params}")
    print(f"📊 実行トライアル数: {len(study.trials)}")
    print(f"📂 結果保存先: {SAVE_DIR}")
    print(f"⏱️ 総経過時間: {elapsed_time/60:.1f}分")
    # 最終クリーンアップ
    # cleanup_worker_environments()
