import concurrent.futures
import os
import sys
import time
from datetime import datetime
from multiprocessing import Lock, Pool

import optuna

# プロジェクトのルートディレクトリをパスに追加
project_root = os.path.abspath(os.path.join(os.getcwd(), '..'))
if project_root not in sys.path:
    sys.path.append(project_root)

from src.simulation.create_emates_env import prepare_parallel_environment
from src.simulation.data_load import save_data_to_pickle
from src.simulation.run_emates import only_run_emates
from src.util.convergence_checker import check_convergence

# 新しいモジュール構成に対応
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

# ファイル書き込み用のロック
file_write_lock = Lock()

# グローバル変数（multiprocessing用）
SAVE_DIR = None
T_HOUR = 26
# 故障シナリオ設定
FAILURE_FLAG = True
# FAILURE_TIME = [15]  # 故障発生時間（15時）
FAILURE_TIME = list(range(0, T_HOUR+1))  # 故障発生時間（0-25時）

def run_single_failure_scenario(task_data):
    """単一の故障シナリオを実行（multiprocessing用）"""
    cs_config, failure_cs_idx, trial_number, worker_id, save_dir, combination_id = task_data
    try:
        # 制約チェック
        if not check_cs_placement(cs_config):
            print(f"❌ Worker{worker_id}: 制約違反")
            return {
                'failure_cs_idx': failure_cs_idx,
                'combination_id': combination_id,
                'cost': float('inf'),
                'wait_time_95p': float('inf'),
                'error': 'constraint_violation'
            }

        # 故障情報作成
        create_failure_info_for_worker(cs_config, failure_cs_idx, worker_id,
                                     FAILURE_TIME=FAILURE_TIME, file_write_lock=file_write_lock)

        # CS設定をファイルに書き込み
        csList_file = get_paths(worker_id)["csList"]
        update_cs_list(cs_config, csList_file)

        # シミュレーション実行
        if T_HOUR is None:
            only_run_emates(worker_id=worker_id)
        else:
            only_run_emates(worker_id=worker_id, HOUR=T_HOUR)

        # 結果保存とコスト計算
        results_filename = f"trial_{trial_number}_combo_{combination_id}_failure_{failure_cs_idx}.pkl"
        results_filepath = os.path.join(save_dir, results_filename)
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
        print(f"💥 Worker{worker_id}: 故障CS{failure_cs_idx} でエラー: {e}")
        return {
            'failure_cs_idx': failure_cs_idx,
            'combination_id': combination_id,
            'worker_id': worker_id,
            'cost': float('inf'),
            'wait_time_95p': float('inf'),
            'error': str(e)
        }

def _simulate_and_calculate_cost(cs_configs, trial) -> tuple:
    """シングルスレッド用のシミュレーション実行"""
    prepare_parallel_environment(cs_configs)
    only_run_emates()

    results_filename = f"trial_{trial.number}.pkl"
    results_filepath = os.path.join(SAVE_DIR, results_filename)
    save_data_to_pickle(filename=results_filepath)

    evaluation_cost, emates_results = evaluation_total_costs(result_file=results_filepath)

    return evaluation_cost, emates_results

def create_failure_scenario_parallel_safe(cs_config_dict, trial_params, trial_number, outer_parallel_count, combination_id):
    """プロセス間通信対応版の故障シナリオ処理（修正：Optuna一切使用しない）"""
    # Optunaオブジェクトを使わず、辞書データのみを受け取る
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

    # 組み合わせごとにWorkerを8個ずつ割り当て
    worker_start = combination_id * 8 + 1
    print(f"Worker割り当て: {worker_start}-{worker_start + 7}")

    # タスクデータを準備
    task_data_list = []
    for i, failure_cs_idx in enumerate(installed_cs_indices):
        worker_id = worker_start + (i % 8)
        task_data = (cs_config_dict, failure_cs_idx, trial_number, worker_id, SAVE_DIR, combination_id)
        task_data_list.append(task_data)

    # multiprocessingで並列実行（修正：Optunaに一切触れない）
    print(f"⚡ 故障シナリオを並列実行中... ({len(task_data_list)}個)")
    max_processes = min(8, len(task_data_list))

    try:
        # 注意: ここではOptunaに関する処理は一切行わない
        with Pool(processes=max_processes) as pool:
            results = pool.map(run_single_failure_scenario, task_data_list)
    except Exception as e:
        print(f"❌ Pool処理エラー: {e}")
        # フォールバック: 順次処理
        print("🔄 順次処理にフォールバック")
        results = []
        for task_data in task_data_list:
            result = run_single_failure_scenario(task_data)
            results.append(result)

    # 結果を処理
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

    # ワーストケース以外の結果ファイルを削除（バックグラウンドで実行）
    def cleanup_files():
        for result in results:
            if result['cost'] != worst_cost and 'results_filepath' in result:
                try:
                    if os.path.exists(result['results_filepath']):
                        os.remove(result['results_filepath'])
                except Exception:
                    pass  # エラーは無視

    import threading
    if TOTAL_TRIALS > 1:
        threading.Thread(target=cleanup_files, daemon=True).start()

    # 重要: ここではOptunaには一切触れず、結果のみを返す
    return {
        'trial_number': trial_number,
        'worst_cost': worst_cost,
        'worst_details': worst_result,
        'all_results': valid_results
    }

def run_parallel_optimization_batch_with_failure(study, batch_size, outer_parallel):
    """故障CSを考慮した並列バッチ最適化を実行（トライアル状態管理修正版）"""
    print(f"\n🔥 {batch_size}個のトライアルを{outer_parallel}並列で故障シナリオ処理中...")

    # 実際のトライアル数を計算（outer_parallelと同じ）
    actual_trials = outer_parallel

    # 各ワーカー用のトライアルを個別に生成（修正：登録を後で行うため状態を管理）
    batch_trials = []
    batch_configs = []
    trial_states = []  # トライアルの状態を追跡

    for i in range(actual_trials):
        trial = study.ask()  # 個別にトライアルを取得
        config = set_cs_placement(trial)
        batch_trials.append(trial)
        batch_configs.append(config)
        trial_states.append('RUNNING')  # 初期状態をRUNNINGに設定

    # パラメータ確認
    print("\n🔍 バッチ内パラメータ:")
    param_hashes = set()
    duplicate_count = 0

    for i, (trial, config) in enumerate(zip(batch_trials, batch_configs)):
        combination_id = i
        param_str = str(sorted(trial.params.items()))
        param_hash = hash(param_str)

        if param_hash in param_hashes:
            duplicate_count += 1
            print(f"  ⚠️ Trial {trial.number} (組み合わせ{combination_id}): 重複パラメータ検出!")
        else:
            param_hashes.add(param_hash)

        print(f"  Trial {trial.number} (組み合わせ{combination_id}): {dict(list(trial.params.items())[:3])}...")

        active_cs = sum(1 for p in config['ports'] if p > 0)
        total_ports = sum(config['ports'])
        print(f"    └─ CS配置: {active_cs}箇所, 合計{total_ports}ポート")

    if duplicate_count > 0:
        print(f"❌ 警告: {duplicate_count}件の重複パラメータが検出されました")
    else:
        print("✅ すべてのパラメータが一意です")

    # 環境構築
    max_workers_needed = actual_trials * 8
    prepare_parallel_environment(batch_configs[0], parallel_count=actual_trials, batch_size=8)

    # csListの更新（メインプロセスで実行）
    for parallel in range(actual_trials):
        for worker_id in range(1, 9):
            global_worker_id = parallel * 8 + worker_id
            cs_config = batch_configs[parallel]
            csList_file = get_paths(global_worker_id)["csList"]
            update_cs_list(cs_config, csList_file)

    # 各トライアルの故障シナリオを処理（修正：Optunaオブジェクトを完全に分離）
    print(f"\n⚡ {actual_trials}並列で故障シナリオ処理開始...")

    cpu_cores = os.cpu_count()
    optimal_outer_processes = min(actual_trials, cpu_cores // 8)
    print(f"🖥️  CPU情報: {cpu_cores}コア, outer_parallel数: {optimal_outer_processes}")

    batch_results = []

    if actual_trials == 1:
        # 単一トライアルの場合は順次処理
        for i, (trial, config) in enumerate(zip(batch_trials, batch_configs)):
            print(f"\n--- トライアル {i+1}/{len(batch_trials)} ---")
            # 修正：trial.paramsの代わりにtrial.numberのみを渡す
            result = create_failure_scenario_parallel_safe(
                config, None, trial.number, actual_trials, combination_id=i
            )
            batch_results.append((trial, config, result))
    else:
        # 並列処理（修正：Optunaオブジェクトを完全に排除）
        with concurrent.futures.ProcessPoolExecutor(max_workers=optimal_outer_processes) as executor:
            future_to_data = {}

            for i, (trial, config) in enumerate(zip(batch_trials, batch_configs)):
                # 修正：プリミティブなデータのみを渡す（Optunaオブジェクト一切なし）
                future = executor.submit(
                    create_failure_scenario_parallel_safe,
                    config,           # 辞書データ
                    None,            # trial.paramsは渡さない
                    trial.number,     # int
                    actual_trials,    # int
                    i                 # combination_id (int)
                )
                future_to_data[future] = (trial, config, i)

            # 結果を収集
            print(f"📊 {len(future_to_data)}個のfutureを待機中...")

            for future in concurrent.futures.as_completed(future_to_data, timeout=3600):
                trial, config, combination_id = future_to_data[future]
                try:
                    result = future.result(timeout=600)
                    batch_results.append((trial, config, result))
                    print(f"✅ Trial {trial.number} (組み合わせ{combination_id}) 完了: ワーストコスト={result['worst_cost']:.2f}万円")
                except Exception as e:
                    print(f"❌ Trial {trial.number} (組み合わせ{combination_id}) エラー: {e}")
                    import traceback
                    traceback.print_exc()
                    batch_results.append((trial, config, {
                        'trial_number': trial.number,
                        'worst_cost': float('inf'),
                        'worst_details': {},
                        'all_results': []
                    }))

    # 結果をOptunaに登録（修正：user_attr設定を先に行う）
    print(f"\n📋 {len(batch_results)}個のトライアル結果をOptunaに登録中...")

    successful_registrations = 0

    for trial, config, result in batch_results:
        worst_cost = result['worst_cost']
        worst_details = result['worst_details']

        try:
            # 修正1：まずuser_attrを設定（RUNNING状態のうちに）
            if worst_details and worst_cost != float('inf'):
                try:
                    print(f"📝 Trial {trial.number}: user_attr設定中...")

                    active_cs_info = []
                    for i, (csid, ports, cap) in enumerate(zip(config['csids'], config['ports'], config['cap_kw'])):
                        if ports > 0:
                            active_cs_info.append({
                                'csid': csid,
                                'ports': ports,
                                'capacity_kw': cap
                            })

                    # RUNNING状態のうちにuser_attrを設定
                    trial.set_user_attr('worst_failure_cs', worst_details.get('failure_cs_idx', -1))
                    trial.set_user_attr('worst_cost_details', worst_cost)
                    trial.set_user_attr('worst_wait_time_95p', worst_details.get('wait_time_95p', 0))
                    trial.set_user_attr('active_cs_config', active_cs_info)
                    trial.set_user_attr('total_active_cs', len(active_cs_info))
                    trial.set_user_attr('total_ports', sum(cs['ports'] for cs in active_cs_info))

                    print(f"✅ Trial {trial.number}: user_attr設定完了")

                except Exception as attr_error:
                    print(f"⚠️ Trial {trial.number}: user_attr設定エラー: {attr_error}")
                    # エラーが発生してもstudy.tell()は実行する

            # 修正2：user_attr設定後にstudy.tell()を実行
            print(f"📝 Trial {trial.number}: コスト{worst_cost:.2f}万円を登録中...")
            study.tell(trial, worst_cost)
            print(f"✅ Trial {trial.number}: Optuna登録完了")

            successful_registrations += 1

        except Exception as e:
            print(f"❌ Trial {trial.number} の結果登録でエラー: {e}")
            print(f"   エラータイプ: {type(e).__name__}")
            print(f"   エラー詳細: {str(e)}")
            continue

    print(f"✅ バッチ完了: {successful_registrations}/{len(batch_results)}件の結果をstudyに登録")
    return successful_registrations

def check_convergence(study, patience=50, min_improvement=0.01):
    """収束判定を行う - 連続してpatience回改善が小さい場合に収束と判定"""
    if len(study.trials) < patience + 10:  # 十分なトライアル数が必要
        return False, f"トライアル数不足 ({len(study.trials)}/{patience + 10})"

    # 有効なトライアル（無限大でない値）を取得
    valid_trials = [trial for trial in study.trials
                   if trial.value is not None and trial.value != float('inf')]

    if len(valid_trials) < patience + 10:
        return False, f"有効なトライアル数不足 ({len(valid_trials)}/{patience + 10})"

    # 最近のpatience+10個の有効な値を取得（ベスト値の履歴を作るため）
    recent_values = []
    for trial in reversed(study.trials):  # 新しい順に処理
        if trial.value is not None and trial.value != float('inf'):
            recent_values.append(trial.value)
        if len(recent_values) >= patience + 10:
            break

    recent_values.reverse()  # 古い順に戻す

    # 各時点でのベスト値を計算
    best_so_far = []
    current_best = float('inf')
    for value in recent_values:
        current_best = min(current_best, value)
        best_so_far.append(current_best)

    # 最近のpatience期間で連続して改善が小さいかチェック
    small_improvement_count = 0

    for i in range(10, len(best_so_far)):  # 最初の10個はスキップ
        # i-10時点のベスト値と現在(i時点)のベスト値を比較
        old_best = best_so_far[i-10]
        current_best = best_so_far[i]

        # 改善率を計算
        if abs(old_best) > 1e-10:
            improvement_rate = abs(current_best - old_best) / abs(old_best)
        else:
            improvement_rate = abs(current_best - old_best)

        # 改善が小さい場合
        if improvement_rate < min_improvement:
            small_improvement_count += 1
        else:
            small_improvement_count = 0  # 連続カウントをリセット

        # patience回連続で小さい改善の場合は収束
        if small_improvement_count >= patience:
            total_improvement = abs(best_so_far[-1] - best_so_far[-(patience+1)]) / abs(best_so_far[-(patience+1)]) if abs(best_so_far[-(patience+1)]) > 1e-10 else abs(best_so_far[-1] - best_so_far[-(patience+1)])
            return True, f"収束判定: 連続{patience}期間で改善率{total_improvement*100:.4f}% < 閾値{min_improvement*100:.2f}%"

    # 最新の改善率を表示
    if len(best_so_far) >= 11:
        latest_improvement = abs(best_so_far[-1] - best_so_far[-11]) / abs(best_so_far[-11]) if abs(best_so_far[-11]) > 1e-10 else abs(best_so_far[-1] - best_so_far[-11])
        return False, f"継続中: 最新10期間の改善率{latest_improvement*100:.4f}% (連続小改善回数: {small_improvement_count}/{patience})"

    return False, "継続中: 改善率計算には十分なデータが不足"

def run_optimization_with_parallel_batches_failure(study, total_trials, batch_size, outer_parallel,
                                                timeout, convergence_patience, convergence_threshold):
    """故障CSを考慮した並列バッチ処理による最適化実行（収束判定付き）"""
    print(f"\n🎯🔥 故障CS考慮並列最適化開始: 目標{total_trials}トライアル, バッチサイズ{batch_size}, outer_parallel={outer_parallel}")
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

            completed = run_parallel_optimization_batch_with_failure(study, actual_batch_size, outer_parallel)

            current_trials = len(study.trials)
            print(f"📈 進捗更新: {current_trials}/{total_trials} 完了")

    except KeyboardInterrupt:
        print("\n⚠️ ユーザーによる中断")
    except Exception as e:
        print(f"❌ 最適化中にエラー: {e}")
    finally:
        cleanup_worker_environments()
        print("🧹 最終クリーンアップ完了")

    print(f"🎉 故障CS考慮最適化完了: {len(study.trials)}トライアル実行済み")

# 最適化実行
if __name__ == "__main__":
    # SAVEDIRをグローバル変数として初期化
    current_time = datetime.now().strftime('%Y%m%d_%H%M')
    SAVE_DIR = f"/srv/samba/share/output/{current_time}_robust_FAILURE"  # 故障シナリオ用のディレクトリ名
    # SAVE_DIR = "20250827_1335_FAILURE"  # ここは適宜変更してください
    os.makedirs(SAVE_DIR, exist_ok=True)

    # 並列処理設定
    BATCH_SIZE = 8          # バッチサイズ（同時に処理するトライアル数）
    OUTER_PARALLEL = 8      # outer_parallel数（トライアルごとの故障シナリオ並列度）
    TOTAL_TRIALS = 1000      # 総トライアル数
    TIMEOUT = 60 * 60 * 24  # 12時間タイムアウト

    # 収束判定設定
    CONVERGENCE_PATIENCE = 100        # 収束判定のトライアル数
    CONVERGENCE_THRESHOLD = 0.001    # 改善率の閾値（0.1%）

    print(f"📂 結果保存先: {SAVE_DIR}")
    print(f"⚙️ 並列設定: バッチサイズ{BATCH_SIZE}, outer_parallel={OUTER_PARALLEL}, 目標{TOTAL_TRIALS}トライアル")
    print(f"🔥 故障シナリオ: 設置CS数分の故障シナリオを{OUTER_PARALLEL}並列で処理")
    print(f"🔍 収束判定: {CONVERGENCE_PATIENCE}トライアル連続で改善率{CONVERGENCE_THRESHOLD*100:.1f}%未満で終了")

    # SQLiteデータベースを使用したStudy管理
    db_path = os.path.join(SAVE_DIR, 'optuna_study_failure.db')
    db_url = f"sqlite:///{db_path}"
    study_name = "cs_optimization_failure"

    # 既存または新規Study作成
    start_time = time.time()
    try:
        study = optuna.load_study(study_name=study_name, storage=db_url)
        print(f"📊 既存Studyをロードしました: {len(study.trials)}トライアル済み")
        if len(study.trials) > 0:
            print(f"🏆 現在の最適値: {study.best_value:.2f}")
            # ベストトライアルの詳細情報を表示
            best_trial = study.best_trial
            if hasattr(best_trial, 'user_attrs') and best_trial.user_attrs:
                print(f"🔥 最悪故障CS: {best_trial.user_attrs.get('worst_failure_cs', 'N/A')}")
                print(f"📊 設置CS数: {best_trial.user_attrs.get('total_active_cs', 'N/A')}")
                print(f"🔌 総ポート数: {best_trial.user_attrs.get('total_ports', 'N/A')}")
    except KeyError:
        study = optuna.create_study(
            direction='minimize',
            study_name=study_name,
            storage=db_url,
            sampler=optuna.samplers.TPESampler(
                seed=42,
                n_startup_trials=max(20, BATCH_SIZE * 5),   # バッチサイズに応じたランダム探索期間
                n_ei_candidates=max(24, BATCH_SIZE * 3),    # バッチサイズに応じた候補数
                constant_liar=True,                         # 並列処理対応：仮の値で並列評価中の重複を回避
                multivariate=True,                          # 多変量TPE（パラメータ間の相関を考慮）
                group=True,                                 # グループ化による効率的な探索
                warn_independent_sampling=True              # 独立サンプリングの警告を有効化
            )
        )
        print("🆕 新しいStudyを作成しました")

    # 故障CS考慮並列バッチ最適化実行
    cleanup_worker_environments()
    run_optimization_with_parallel_batches_failure(
        study,
        total_trials=TOTAL_TRIALS,
        batch_size=BATCH_SIZE,
        outer_parallel=OUTER_PARALLEL,
        timeout=TIMEOUT,
        convergence_patience=CONVERGENCE_PATIENCE,
        convergence_threshold=CONVERGENCE_THRESHOLD
    )

    # 最適化完了後のファイル管理
    # SAVE_DIR = "20250829_0129_FAILURE"
    # db_path = os.path.join(SAVE_DIR, 'optuna_study_failure.db')
    # db_url = f"sqlite:///{db_path}"
    # study_name = "cs_optimization_failure"
    # study = optuna.load_study(study_name=study_name, storage=db_url)
    manage_pkl_files_after_optimization(study, SAVE_DIR)
    start_time = time.time()
    elapsed_time = time.time() - start_time

    # 最終結果表示（詳細版）
    print(f"\n=== 故障CS考慮最適化結果サマリー ===")
    print(f"🏆 最適値: {study.best_value:.2f}万円")
    print(f"📋 最適パラメータ: {study.best_params}")
    print(f"📊 実行トライアル数: {len(study.trials)}")
    print(f"📂 結果保存先: {SAVE_DIR}")
    print(f"⏱️ 総経過時間: {elapsed_time/60:.1f}分")

    # ベストトライアルの故障シナリオ詳細
    best_trial = study.best_trial
    if hasattr(best_trial, 'user_attrs') and best_trial.user_attrs:
        print(f"\n=== ベストトライアル詳細 ===")
        print(f"🔥 最悪故障CS: {best_trial.user_attrs.get('worst_failure_cs', 'N/A')}")
        print(f"💰 最悪コスト: {best_trial.user_attrs.get('worst_cost_details', 'N/A'):.2f}万円")
        print(f"⏱️ 最悪95%待ち時間: {best_trial.user_attrs.get('worst_wait_time_95p', 'N/A'):.2f}秒")
        print(f"📊 設置CS数: {best_trial.user_attrs.get('total_active_cs', 'N/A')}")
        print(f"🔌 総ポート数: {best_trial.user_attrs.get('total_ports', 'N/A')}")

        # 設置CS詳細
        active_cs_config = best_trial.user_attrs.get('active_cs_config', [])
        if active_cs_config:
            print(f"\n=== 設置CS詳細 ===")
            for i, cs_info in enumerate(active_cs_config):
                print(f"  CS{i+1}: CSID={cs_info['csid']}, ポート数={cs_info['ports']}, 容量={cs_info['capacity_kw']}kW")

    # 最終クリーンアップ
    print("\n🎉 故障CS考慮最適化完了!")
