import optuna
import sys
import os
from datetime import datetime
import json
import pickle
import numpy as np
import pandas as pd  # pandasも明示的にインポート
import shutil
from pathlib import Path


# プロジェクトのルートディレクトリをパスに追加
project_root = os.path.abspath(os.path.join(os.getcwd(), '..'))
if project_root not in sys.path:
    sys.path.append(project_root)
    
from src.simulation.run_emates import only_run_emates
from src.simulation.data_load import save_data_to_pickle
from src.util.path_manager import get_paths
from src.util.optimization import *
from src.simulation.create_emates_env import prepare_parallel_environment

def cs_placement_objective(trial):
    """CS配置最適化の目的関数"""
    cs_config = set_cs_placement(trial, worker_id=None)

    # 2. 制約チェック----------
    if not check_cs_placement(cs_config):
        return float('inf')
    # 制約違反がある場合は無限大を返す

    #3. シミュレーション実行とコスト計算。evaluation_costを最小化したい！
    evaluation_cost, emates_results = _simulate_and_calculate_cost(cs_config, trial)
    
    #4.ペナルティ....
    return evaluation_cost

def _simulate_and_calculate_cost(cs_configs, trial) -> tuple:
    
    prepare_parallel_environment(cs_configs)
    # シミュレーションの実行
    only_run_emates()    
    # データの保存

    results_filename = f"trial_{trial.number}.pkl"
    results_filepath = os.path.join(SAVE_DIR, results_filename)

    save_data_to_pickle(filename=results_filepath)
    
    # 評価コストの計算
    evaluation_cost, emates_results = evaluation_total_costs(result_file=results_filepath)
    
    return evaluation_cost, emates_results

def manage_pkl_files_after_optimization(study, save_dir):
    """最適化完了後のpklファイル管理"""
    print("\n=== 最適化完了後のファイル管理 ===")
    
    save_path = Path(save_dir)
    pkl_files = [f for f in os.listdir(save_path) if f.endswith('.pkl')]
    
    if not pkl_files:
        print("pklファイルが見つかりません。")
        return
    
    # ベストtrialを特定
    best_trial_number = study.best_trial.number
    print(f"ベストtrial: {best_trial_number}")
    
    # 保持するファイルを選定
    trials_to_keep = set()
    
    # 1. ベストtrial
    best_file = f"trial_{best_trial_number}.pkl"
    if best_file in pkl_files:
        trials_to_keep.add(best_file)
    
    # 2. 10の倍数のtrial
    for f in pkl_files:
        try:
            trial_num = int(f.split('_')[1].split('.')[0])
            if trial_num % 10 == 0:
                trials_to_keep.add(f)
        except (IndexError, ValueError):
            continue
    
    # 3. 最新10個のtrial
    try:
        sorted_files = sorted(pkl_files, 
                            key=lambda x: int(x.split('_')[1].split('.')[0]), 
                            reverse=True)
        for f in sorted_files[:10]:
            trials_to_keep.add(f)
    except (IndexError, ValueError):
        print("ファイル名の解析に失敗しました。")
    
    # 4. 削除対象を特定
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
    
    # 保持ファイルの内訳を表示
    print(f"\n=== 保持ファイル詳細 ===")
    for file in sorted(trials_to_keep):
        try:
            trial_num = int(file.split('_')[1].split('.')[0])
            file_path = save_path / file
            size_mb = file_path.stat().st_size / (1024**2) if file_path.exists() else 0
            
            reason = []
            if file == best_file:
                reason.append("ベスト")
            if trial_num % 10 == 0:
                reason.append("10の倍数")
            if file in sorted_files[:10]:
                reason.append("最新10個")
            
            print(f"  {file} (trial {trial_num}, {size_mb:.1f}MB) - {', '.join(reason)}")
        except (IndexError, ValueError):
            print(f"  {file} - ファイル名解析失敗")
    
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
    
    print(f"\n{moved_count}個のファイルをバックアップディレクトリに移動しました。")
    print(f"バックアップ先: {backup_dir}")
    
    # 残りファイルサイズを確認
    remaining_size = sum(f.stat().st_size for f in save_path.glob("*.pkl")) / (1024**2)
    print(f"残りのpklファイルサイズ: {remaining_size:.1f} MB")

# 最適化実行
if __name__ == "__main__":
    # SAVEDIRをグローバル変数として初期化。
    current_time = datetime.now().strftime('%Y%m%d_%H%M')
    SAVE_DIR = current_time
    SAVE_DIR = "20250815_0955"  # ここは適宜変更してください
    os.makedirs(SAVE_DIR, exist_ok=True)
    
    
    # タイムアウトを設定
    TIMEOUT = 60 * 60 * 22  # 22時間のタイムアウト設定
    additional_trials = 200  # 追加で実行するトライアル数
    
    
    # SQLiteデータベースを使用したStudy管理
    db_path = os.path.join(SAVE_DIR, 'optuna_study.db')
    db_url = f"sqlite:///{db_path}"
    study_name = "cs_optimization"
    
    # 既存のSQLiteデータベースからStudyを読み込み
    try:
        study = optuna.load_study(study_name=study_name, storage=db_url)
        print(f"既存のSQLiteStudyを読み込みました（トライアル数: {len(study.trials)}）")
        print(f"現在の最適値: {study.best_value}")
        print(f"現在の最適パラメータ: {study.best_params}")
    except KeyError:
        # 新しいStudyを作成
        study = optuna.create_study(
            direction='minimize', 
            study_name=study_name, 
            storage=db_url
        )
        print("新しいSQLiteStudyを作成しました")
    
    print(f"追加で{additional_trials}トライアルを実行します...")
    
    # 最適化実行（継続）
    study.optimize(cs_placement_objective, n_trials=additional_trials, n_jobs=1, timeout=TIMEOUT)

    print(f"最適化完了！")
    # 最適化完了後のファイル管理を自動実行
    manage_pkl_files_after_optimization(study, SAVE_DIR)
    
    # 最終結果の表示
    print(f"\n=== 最適化結果サマリー ===")
    print(f"最適値: {study.best_value}")
    print(f"最適パラメータ: {study.best_params}")
    print(f"実行トライアル数: {len(study.trials)}")
    print(f"結果保存先: {SAVE_DIR}")