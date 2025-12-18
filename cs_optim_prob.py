import concurrent.futures
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from multiprocessing import Lock, Pool

import optuna

# プロジェクトのルートディレクトリをパスに追加
project_root = os.path.abspath(os.path.join(os.getcwd(), ".."))
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
FAILURE_TIME = list(range(0, T_HOUR + 1))  # 故障発生時間（0-25時）
SAVE_DIR = f"/srv/samba/share/output/PROBABILISTIC_50%"  # 確率的最適化用のディレクトリ名

# 確率的最適化設定
FAILURE_PROBABILITY = 0.2  # 全CSのうち一か所が故障する確率（20%）
CHARGER_FAILURE_RATE = 0.02  # 各充電器の故障率（2%）


def process_result_file_parallel(result_data):
    """結果ファイルの並列処理用関数（高速化版）"""
    try:
        results_filepath = result_data["results_filepath"]
        failure_cs_idx = result_data["failure_cs_idx"]

        # ファイルの存在確認
        if not os.path.exists(results_filepath):
            return {
                "failure_cs_idx": failure_cs_idx,
                "cost": float("inf"),
                "wait_time_95p": float("inf"),
                "error": "file_not_found",
            }

        # ファイルサイズチェック（空ファイルの早期検出）
        if os.path.getsize(results_filepath) == 0:
            return {
                "failure_cs_idx": failure_cs_idx,
                "cost": float("inf"),
                "wait_time_95p": float("inf"),
                "error": "empty_file",
            }

        # 並列でコスト計算と待ち時間計算を実行（タイムアウト付き）
        with ThreadPoolExecutor(max_workers=2) as executor:
            cost_future = executor.submit(
                evaluation_total_costs, result_file=results_filepath
            )
            wait_future = executor.submit(
                calculate_95percentile_wait_time, results_filepath
            )

            # タイムアウト設定（30秒）
            try:
                evaluation_cost, _ = cost_future.result(timeout=30)
                wait_time_95p = wait_future.result(timeout=30)
            except concurrent.futures.TimeoutError:
                return {
                    "failure_cs_idx": failure_cs_idx,
                    "cost": float("inf"),
                    "wait_time_95p": float("inf"),
                    "error": "processing_timeout",
                }

        return {
            "failure_cs_idx": failure_cs_idx,
            "cost": evaluation_cost,
            "wait_time_95p": wait_time_95p,
            "results_filepath": results_filepath,
        }

    except Exception as e:
        return {
            "failure_cs_idx": failure_cs_idx,
            "cost": float("inf"),
            "wait_time_95p": float("inf"),
            "error": str(e),
        }


def run_single_failure_scenario(task_data):
    """単一の故障シナリオを実行（multiprocessing用）"""
    cs_config, failure_cs_idx, trial_number, worker_id, save_dir, combination_id = (
        task_data
    )
    try:
        # 制約チェック
        if not check_cs_placement(cs_config):
            scenario_type = (
                "正常ケース" if failure_cs_idx is None else f"故障CS{failure_cs_idx}"
            )
            print(f"❌ Worker{worker_id}: {scenario_type} 制約違反")
            return {
                "failure_cs_idx": failure_cs_idx,
                "combination_id": combination_id,
                "cost": float("inf"),
                "wait_time_95p": float("inf"),
                "error": "constraint_violation",
                "simulation_completed": False,
            }

        # 故障情報作成
        create_failure_info_for_worker(
            cs_config,
            failure_cs_idx,
            worker_id,
            FAILURE_TIME=FAILURE_TIME,
            file_write_lock=file_write_lock,
        )

        # CS設定をファイルに書き込み
        csList_file = get_paths(worker_id)["csList"]
        update_cs_list(cs_config, csList_file)

        # シミュレーション実行
        if T_HOUR is None:
            only_run_emates(worker_id=worker_id)
        else:
            only_run_emates(worker_id=worker_id, HOUR=T_HOUR)

        # 結果保存（ファイル処理は後で並列実行）
        scenario_suffix = (
            "normal" if failure_cs_idx is None else f"failure_{failure_cs_idx}"
        )
        results_filename = (
            f"trial_{trial_number}_combo_{combination_id}_{scenario_suffix}.pkl"
        )
        results_filepath = os.path.join(save_dir, results_filename)
        save_data_to_pickle(filename=results_filepath, worker_id=worker_id)

        scenario_type = (
            "正常ケース" if failure_cs_idx is None else f"故障CS{failure_cs_idx}"
        )
        print(
            f"⚡ Worker{worker_id}: {scenario_type} シミュレーション完了 (結果処理待ち)"
        )

        # シミュレーション完了時はファイルパスのみ返す（コスト計算は後で並列処理）
        return {
            "failure_cs_idx": failure_cs_idx,
            "combination_id": combination_id,
            "worker_id": worker_id,
            "results_filepath": results_filepath,
            "cs_config": cs_config.copy(),
            "simulation_completed": True,
        }

    except Exception as e:
        scenario_type = (
            "正常ケース" if failure_cs_idx is None else f"故障CS{failure_cs_idx}"
        )
        print(f"💥 Worker{worker_id}: {scenario_type} でエラー: {e}")
        return {
            "failure_cs_idx": failure_cs_idx,
            "combination_id": combination_id,
            "worker_id": worker_id,
            "cost": float("inf"),
            "wait_time_95p": float("inf"),
            "error": str(e),
            "simulation_completed": False,
        }


def _simulate_and_calculate_cost(cs_configs, trial) -> tuple:
    """シングルスレッド用のシミュレーション実行"""
    prepare_parallel_environment(cs_configs, parallel_count=1, batch_size=1)
    only_run_emates()

    results_filename = f"trial_{trial.number}.pkl"
    results_filepath = os.path.join(SAVE_DIR, results_filename)
    save_data_to_pickle(filename=results_filepath)

    evaluation_cost, emates_results = evaluation_total_costs(
        result_file=results_filepath
    )

    return evaluation_cost, emates_results


def create_failure_scenario_parallel_safe(
    cs_config_dict, trial_params, trial_number, outer_parallel_count, combination_id
):
    """確率的最適化用の故障シナリオ処理（修正：Optuna一切使用しない）"""
    # Optunaオブジェクトを使わず、辞書データのみを受け取る
    installed_cs_indices = [
        i for i, ports in enumerate(cs_config_dict["ports"]) if ports > 0
    ]
    if len(installed_cs_indices) == 0:
        return {
            "trial_number": trial_number,
            "expected_cost": float("inf"),
            "expected_details": {},
            "all_results": [],
        }

    print(
        f"\n=== Trial {trial_number} (組み合わせ{combination_id}): 故障シナリオ並列処理開始 ==="
    )
    print(
        f"設置CS数: {len(installed_cs_indices)}, 故障シナリオ数: {len(installed_cs_indices)}"
    )

    # 組み合わせごとにWorkerを8個ずつ割り当て
    worker_start = combination_id * MAX_BATCH_SIZE + 1
    print(f"Worker割り当て: {worker_start}-{worker_start + MAX_BATCH_SIZE}")

    # タスクデータを準備
    task_data_list = []
    for i, failure_cs_idx in enumerate(installed_cs_indices):
        worker_id = worker_start + (i % MAX_BATCH_SIZE)
        task_data = (
            cs_config_dict,
            failure_cs_idx,
            trial_number,
            worker_id,
            SAVE_DIR,
            combination_id,
        )
        task_data_list.append(task_data)

    # 正常ケースも追加（故障CSなし）
    worker_id = worker_start + (len(installed_cs_indices) % MAX_BATCH_SIZE)
    normal_task_data = (
        cs_config_dict,
        None,
        trial_number,
        worker_id,
        SAVE_DIR,
        combination_id,
    )
    task_data_list.append(normal_task_data)

    # multiprocessingで並列実行（修正：Optunaに一切触れない）
    print(f"⚡ 故障シナリオ+正常ケースを並列実行中... ({len(task_data_list)}個)")
    max_processes = min(MAX_BATCH_SIZE, len(task_data_list))

    # 注意: ここではOptunaに関する処理は一切行わない
    with Pool(processes=max_processes) as pool:
        simulation_results = pool.map(run_single_failure_scenario, task_data_list)

    print("📊 シミュレーション完了、結果ファイル処理を並列実行中...")

    # シミュレーション成功したものだけ結果処理を並列実行
    completed_simulations = [
        r for r in simulation_results if r.get("simulation_completed", False)
    ]

    if not completed_simulations:
        print("❌ 成功したシミュレーションがありません")
        valid_results = []
    else:
        # CPUコア数に基づく最適なワーカー数を決定
        cpu_count = os.cpu_count() or 2
        optimal_workers = min(
            max(2, cpu_count // 2), len(completed_simulations), 12
        )

        print(f"🔥 結果処理を{optimal_workers}並列で高速実行中...")
        start_time = time.time()

        # 結果処理を並列実行（ThreadPoolExecutorで高速化）
        with ThreadPoolExecutor(max_workers=optimal_workers) as executor:
            # バッチ処理でメモリ効率を向上
            processed_results = []
            batch_size = 20

            for i in range(0, len(completed_simulations), batch_size):
                batch = completed_simulations[i : i + batch_size]
                batch_results = list(executor.map(process_result_file_parallel, batch))
                processed_results.extend(batch_results)

        processing_time = time.time() - start_time

        # 結果をマージ（高速化）
        valid_results = []
        successful_count = 0

        for sim_result, proc_result in zip(completed_simulations, processed_results):
            if proc_result["cost"] != float("inf"):
                # 辞書マージを高速化
                merged_result = sim_result.copy()
                merged_result.update(proc_result)
                valid_results.append(merged_result)
                successful_count += 1

        # 失敗したシミュレーションも含める
        for sim_result in simulation_results:
            if not sim_result.get("simulation_completed", False):
                valid_results.append(sim_result)

        print(
            f"⚡ 高速化処理完了: {successful_count}/{len(processed_results)}件成功 ({processing_time:.2f}秒)"
        )

    if not valid_results:
        print("❌ 有効なシナリオ結果がありません")
        return {
            "trial_number": trial_number,
            "expected_cost": float("inf"),
            "expected_details": {},
            "all_results": simulation_results,
        }

    # 期待値計算（確率的最適化）
    normal_result = None
    failure_results = []

    # 結果を正常ケースと故障ケースに分類
    for result in valid_results:
        if result["failure_cs_idx"] is None:
            normal_result = result
        else:
            failure_results.append(result)

    # 期待値計算
    if normal_result is None:
        print("❌ 正常ケースの結果がありません")
        expected_cost = float("inf")
        expected_details = {}
    else:
        num_installed_cs = len(failure_results)

    if num_installed_cs == 0:
        # 設置CSが0個の場合は正常時のみ
        normal_probability = 1.0
        cs_failure_probabilities = {}
        expected_cost = normal_result["cost"]
        expected_details = {
            "normal_cost": normal_result["cost"],
            "normal_probability": normal_probability,
            "failure_probabilities": {},
            "total_failure_probability": 0.0,
            "num_scenarios": 1,
            "failure_costs": [],
            "cs_ports": {},
        }
    else:
        # 充電器ベースの故障確率モデル（N-1基準：単一CS故障のみ考慮）
        # 各CSの充電器数を取得
        cs_ports = {}
        for failure_result in failure_results:
            failure_cs_idx = failure_result["failure_cs_idx"]
            ports = failure_result.get("cs_config", {}).get("ports", [])[failure_cs_idx]
            cs_ports[failure_cs_idx] = ports

        # 各CSの故障確率 = 1 - (1 - 充電器故障率)^充電器数
        # これは「CS内の少なくとも1台の充電器が故障する確率」
        cs_failure_probabilities = {}
        for cs_idx, ports in cs_ports.items():
            # 充電器が少なくとも1台故障する確率（充電器数が多いほど高くなる）
            cs_failure_prob = 1 - (1 - CHARGER_FAILURE_RATE) ** ports
            cs_failure_probabilities[cs_idx] = cs_failure_prob

        # 全体の故障確率（少なくとも1つのCSが故障する確率）
        # N-1基準では単一CS故障のみ考慮するため、各CS単独故障確率の合計
        total_failure_prob = sum(cs_failure_probabilities.values())

        # 正常時の確率（N-1基準：複数同時故障は考慮しない）
        # ただし、確率の合計を1.0にするため調整が必要
        if total_failure_prob >= 1.0:
            # 故障確率が100%を超える場合は正規化
            print(
                f"⚠️ 警告: 故障確率の合計が1.0以上 ({total_failure_prob:.4f})のため正規化します"
            )
            normalization_factor = 0.99 / total_failure_prob  # 最大99%に抑える
            cs_failure_probabilities = {
                k: v * normalization_factor for k, v in cs_failure_probabilities.items()
            }
            total_failure_prob = sum(cs_failure_probabilities.values())
            normal_probability = 1 - total_failure_prob
        else:
            normal_probability = 1 - total_failure_prob

        # 期待値計算
        expected_cost = normal_probability * normal_result["cost"]

        # 各CS単独故障のコストを加算
        for failure_result in failure_results:
            failure_cs_idx = failure_result["failure_cs_idx"]
            cs_failure_prob = cs_failure_probabilities[failure_cs_idx]
            expected_cost += cs_failure_prob * failure_result["cost"]

        # 確率の合計検証（デバッグ用）
        total_scenario_prob = normal_probability + sum(
            cs_failure_probabilities.values()
        )

        if abs(total_scenario_prob - 1.0) > 0.001:
            print(f"⚠️ 警告: 確率の合計が1.0ではありません: {total_scenario_prob:.6f}")
            print(f"   差分: {abs(total_scenario_prob - 1.0):.6f}")
            print(f"   正常確率: {normal_probability:.6f}")
            print(f"   故障確率合計: {sum(cs_failure_probabilities.values()):.6f}")
            print(f"   各CS故障確率: {cs_failure_probabilities}")
        else:
            print(f"✅ 確率の合計検証OK: {total_scenario_prob:.6f}")

        expected_details = {
            "normal_cost": normal_result["cost"],
            "normal_probability": normal_probability,
            "failure_probabilities": cs_failure_probabilities,  # CS別の故障確率
            "total_failure_probability": total_failure_prob,
            "charger_failure_rate": CHARGER_FAILURE_RATE,  # 充電器故障率パラメータ
            "num_scenarios": len(failure_results) + 1,
            "failure_costs": [r["cost"] for r in failure_results],
            "cs_ports": cs_ports,  # 各CSの充電器数
        }

    total_simulations = len(simulation_results)
    print(
        f"📊 確率的結果: 有効{len(valid_results)}/{total_simulations}件, 期待コスト={expected_cost:.2f}万円"
    )
    if num_installed_cs > 0:
        print(
            f"   正常確率={normal_probability:.3f}, 総故障確率={total_failure_prob:.3f}"
        )
        print(
            f"   CS別故障確率: {', '.join([f'CS{idx}({ports}台):{prob:.4f}' for idx, (ports, prob) in zip(cs_ports.keys(), [(p, cs_failure_probabilities[idx]) for idx, p in cs_ports.items()])])}"
        )
    # ...existing code...
    # すべての結果ファイルを保持（確率的最適化では全結果が重要）
    print("📁 全シナリオ結果ファイルを保持します")

    # 重要: ここではOptunaには一切触れず、結果のみを返す
    return {
        "trial_number": trial_number,
        "expected_cost": expected_cost,
        "expected_details": expected_details,
        "all_results": valid_results,
    }


def run_parallel_optimization_batch_with_failure(study, batch_size, outer_parallel):
    """故障CSを考慮した並列バッチ最適化を実行（トライアル状態管理修正版）"""
    print(
        f"\n🔥 {batch_size}個のトライアルを{outer_parallel}並列で故障シナリオ処理中..."
    )

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
        trial_states.append("RUNNING")  # 初期状態をRUNNINGに設定

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
            print(
                f"  ⚠️ Trial {trial.number} (組み合わせ{combination_id}): 重複パラメータ検出!"
            )
        else:
            param_hashes.add(param_hash)

        print(
            f"  Trial {trial.number} (組み合わせ{combination_id}): {dict(list(trial.params.items())[:3])}..."
        )

        active_cs = sum(1 for p in config["ports"] if p > 0)
        total_ports = sum(config["ports"])
        print(f"    └─ CS配置: {active_cs}箇所, 合計{total_ports}ポート")

    if duplicate_count > 0:
        print(f"❌ 警告: {duplicate_count}件の重複パラメータが検出されました")
    else:
        print("✅ すべてのパラメータが一意です")

    # 環境構築
    prepare_parallel_environment(
        batch_configs[0], parallel_count=actual_trials, batch_size=batch_size
    )

    # csListの更新（メインプロセスで実行）
    for parallel in range(actual_trials):
        for worker_id in range(1, MAX_BATCH_SIZE + 1):
            global_worker_id = parallel * MAX_BATCH_SIZE + worker_id
            cs_config = batch_configs[parallel]
            csList_file = get_paths(global_worker_id)["csList"]
            update_cs_list(cs_config, csList_file)

    # 各トライアルの故障シナリオを処理（修正：Optunaオブジェクトを完全に分離）
    print(f"\n⚡ {actual_trials}並列で故障シナリオ処理開始...")

    cpu_cores = os.cpu_count()
    optimal_outer_processes = min(actual_trials, cpu_cores // MAX_BATCH_SIZE)
    print(f"🖥️  CPU情報: {cpu_cores}コア, outer_parallel数: {optimal_outer_processes}")

    batch_results = []

    if actual_trials == 1:
        # 単一トライアルの場合は順次処理
        for i, (trial, config) in enumerate(zip(batch_trials, batch_configs)):
            print(f"\n--- トライアル {i + 1}/{len(batch_trials)} ---")
            # 修正：trial.paramsの代わりにtrial.numberのみを渡す
            result = create_failure_scenario_parallel_safe(
                config, None, trial.number, actual_trials, combination_id=i
            )
            batch_results.append((trial, config, result))
    else:
        # 並列処理（修正：Optunaオブジェクトを完全に排除）
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=optimal_outer_processes
        ) as executor:
            future_to_data = {}

            for i, (trial, config) in enumerate(zip(batch_trials, batch_configs)):
                # 修正：プリミティブなデータのみを渡す（Optunaオブジェクト一切なし）
                future = executor.submit(
                    create_failure_scenario_parallel_safe,
                    config,  # 辞書データ
                    None,  # trial.paramsは渡さない
                    trial.number,  # int
                    actual_trials,  # int
                    i,  # combination_id (int)
                )
                future_to_data[future] = (trial, config, i)

            # 結果を収集
            print(f"📊 {len(future_to_data)}個のfutureを待機中...")

            for future in concurrent.futures.as_completed(future_to_data, timeout=3600):
                trial, config, combination_id = future_to_data[future]
                try:
                    result = future.result(timeout=600)
                    batch_results.append((trial, config, result))
                    print(
                        f"✅ Trial {trial.number} (組み合わせ{combination_id}) 完了: 期待値コスト={result['expected_cost']:.2f}万円"
                    )
                except Exception as e:
                    print(
                        f"❌ Trial {trial.number} (組み合わせ{combination_id}) エラー: {e}"
                    )
                    import traceback

                    traceback.print_exc()
                    batch_results.append(
                        (
                            trial,
                            config,
                            {
                                "trial_number": trial.number,
                                "expected_cost": float("inf"),
                                "expected_details": {},
                                "all_results": [],
                            },
                        )
                    )

    # 結果をOptunaに登録（修正：user_attr設定を先に行う）
    print(f"\n📋 {len(batch_results)}個のトライアル結果をOptunaに登録中...")

    successful_registrations = 0

    for trial, config, result in batch_results:
        expected_cost = result["expected_cost"]
        expected_details = result["expected_details"]

        try:
            # 修正1：まずuser_attrを設定（RUNNING状態のうちに）
            if expected_details and expected_cost != float("inf"):
                try:
                    print(f"📝 Trial {trial.number}: user_attr設定中...")

                    active_cs_info = []
                    for i, (csid, ports, cap) in enumerate(
                        zip(config["csids"], config["ports"], config["cap_kw"])
                    ):
                        if ports > 0:
                            active_cs_info.append(
                                {"csid": csid, "ports": ports, "capacity_kw": cap}
                            )

                    # RUNNING状態のうちにuser_attrを設定（確率的最適化用）
                    trial.set_user_attr("expected_cost_details", expected_cost)
                    trial.set_user_attr(
                        "normal_cost", expected_details.get("normal_cost", 0)
                    )
                    trial.set_user_attr(
                        "normal_probability",
                        expected_details.get("normal_probability", 0),
                    )
                    trial.set_user_attr(
                        "individual_failure_probability",
                        expected_details.get("failure_probability", 0),
                    )
                    trial.set_user_attr(
                        "total_failure_probability",
                        expected_details.get("total_failure_probability", 0),
                    )
                    trial.set_user_attr(
                        "num_scenarios", expected_details.get("num_scenarios", 0)
                    )
                    trial.set_user_attr("active_cs_config", active_cs_info)
                    trial.set_user_attr("total_active_cs", len(active_cs_info))
                    trial.set_user_attr(
                        "total_ports", sum(cs["ports"] for cs in active_cs_info)
                    )

                    print(f"✅ Trial {trial.number}: user_attr設定完了")

                except Exception as attr_error:
                    print(f"⚠️ Trial {trial.number}: user_attr設定エラー: {attr_error}")
                    # エラーが発生してもstudy.tell()は実行する

            # 修正2：user_attr設定後にstudy.tell()を実行
            print(
                f"📝 Trial {trial.number}: 期待コスト{expected_cost:.2f}万円を登録中..."
            )
            study.tell(trial, expected_cost)
            print(f"✅ Trial {trial.number}: Optuna登録完了")

            successful_registrations += 1

        except Exception as e:
            print(f"❌ Trial {trial.number} の結果登録でエラー: {e}")
            print(f"   エラータイプ: {type(e).__name__}")
            print(f"   エラー詳細: {str(e)}")
            continue

    print(
        f"✅ バッチ完了: {successful_registrations}/{len(batch_results)}件の結果をstudyに登録"
    )
    return successful_registrations


def run_optimization_with_parallel_batches_failure(
    study,
    total_trials,
    batch_size,
    outer_parallel,
    timeout,
    convergence_patience,
    convergence_threshold,
):
    """故障CSを考慮した並列バッチ処理による最適化実行（収束判定付き）"""
    print(
        f"\n🎯🔥 故障CS考慮並列最適化開始: 目標{total_trials}トライアル, バッチサイズ{batch_size}, outer_parallel={outer_parallel}"
    )
    print(
        f"🔍 収束判定: {convergence_patience}トライアル連続で改善率{convergence_threshold * 100:.2f}%未満で終了"
    )

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
                    study,
                    patience=convergence_patience,
                    min_improvement=convergence_threshold,
                )

                print(f"🔍 {convergence_msg}")

                if is_converged:
                    print(f"🛑 収束により最適化を終了します (Trial {current_trials})")
                    print(f"📊 最終最適値: {study.best_value:.2f}万円")
                    break

            actual_batch_size = min(batch_size, total_trials - current_trials)
            print(
                f"\n--- バッチ {batch_idx + 1}/{batches_needed} (サイズ: {actual_batch_size}) ---"
            )

            run_parallel_optimization_batch_with_failure(
                study, actual_batch_size, outer_parallel
            )

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
    start_time = time.time()
    # SAVEDIRをグローバル変数として初期化
    current_time = datetime.now().strftime("%Y%m%d_%H%M")
    SAVE_DIR = f"/srv/samba/share/output/{current_time}_PROBABILISTIC_50%"  # 確率的最適化用のディレクトリ名
    # SAVE_DIR = f"/srv/samba/share/output/20251030_0105_PROBABILISTIC_50%"  # ここは適宜変更してください
    os.makedirs(SAVE_DIR, exist_ok=True)

    # 並列処理設定
    BATCH_SIZE = 9  # バッチサイズ（同時に処理するトライアル数）
    MAX_BATCH_SIZE = 9  # 各outer_parallelあたりの最大Worker数
    OUTER_PARALLEL = 8  # outer_parallel数（トライアルごとの故障シナリオ並列度）
    TOTAL_TRIALS = 1000  # 総トライアル数
    TIMEOUT = 60 * 60 * 24  # 24時間タイムアウト

    # 収束判定設定
    CONVERGENCE_PATIENCE = 100  # 収束判定のトライアル数
    CONVERGENCE_THRESHOLD = 0.01  # 改善率の閾値（1%）

    print(f"📂 結果保存先: {SAVE_DIR}")
    print(
        f"⚙️ 並列設定: バッチサイズ{BATCH_SIZE}, outer_parallel={OUTER_PARALLEL}, 目標{TOTAL_TRIALS}トライアル"
    )
    print(
        f"🔥 確率的最適化: 故障確率{FAILURE_PROBABILITY * 100:.1f}%で期待値を{OUTER_PARALLEL}並列計算"
    )
    print(
        f"🔍 収束判定: {CONVERGENCE_PATIENCE}トライアル連続で改善率{CONVERGENCE_THRESHOLD * 100:.1f}%未満で終了"
    )

    # SQLiteデータベースを使用したStudy管理
    db_path = os.path.join(SAVE_DIR, "optuna_study_failure.db")
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
            if hasattr(best_trial, "user_attrs") and best_trial.user_attrs:
                print(
                    f"🎲 期待値: {best_trial.user_attrs.get('expected_cost_details', 'N/A'):.2f}万円"
                )
                print(
                    f"📊 設置CS数: {best_trial.user_attrs.get('total_active_cs', 'N/A')}"
                )
                print(
                    f"🔌 総ポート数: {best_trial.user_attrs.get('total_ports', 'N/A')}"
                )
    except KeyError:
        study = optuna.create_study(
            direction="minimize",
            study_name=study_name,
            storage=db_url,
            sampler=optuna.samplers.TPESampler(
                seed=42,
                n_startup_trials=max(
                    20, BATCH_SIZE * 5
                ),  # バッチサイズに応じたランダム探索期間
                n_ei_candidates=max(24, BATCH_SIZE * 3),  # バッチサイズに応じた候補数
                constant_liar=True,  # 並列処理対応：仮の値で並列評価中の重複を回避
                multivariate=True,  # 多変量TPE（パラメータ間の相関を考慮）
                group=True,  # グループ化による効率的な探索
                warn_independent_sampling=True,  # 独立サンプリングの警告を有効化
            ),
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
        convergence_threshold=CONVERGENCE_THRESHOLD,
    )

    # 最適化完了後のファイル管理
    # SAVE_DIR = "20250829_0129_FAILURE"
    # db_path = os.path.join(SAVE_DIR, 'optuna_study_failure.db')
    # db_url = f"sqlite:///{db_path}"
    # study_name = "cs_optimization_failure"
    # study = optuna.load_study(study_name=study_name, storage=db_url)
    manage_pkl_files_after_optimization(study, SAVE_DIR)
    elapsed_time = time.time() - start_time

    # 最終結果表示（詳細版）
    print("\n=== 確率的最適化結果サマリー ===")
    print(f"🏆 最適期待値: {study.best_value:.2f}万円")
    print(f"📋 最適パラメータ: {study.best_params}")
    print(f"🎲 充電器故障確率: {CHARGER_FAILURE_RATE * 100:.1f}%")
    print(f"📊 実行トライアル数: {len(study.trials)}")
    print(f"📂 結果保存先: {SAVE_DIR}")
    print(f"⏱️ 総経過時間: {elapsed_time / 60:.1f}分")

    # ベストトライアルの確率的詳細
    best_trial = study.best_trial
    if hasattr(best_trial, "user_attrs") and best_trial.user_attrs:
        print("\n=== ベストトライアル詳細 ===")
        print(
            f"� 期待コスト: {best_trial.user_attrs.get('expected_cost_details', 'N/A'):.2f}万円"
        )
        print(
            f"� 正常時コスト: {best_trial.user_attrs.get('normal_cost', 'N/A'):.2f}万円"
        )
        print(
            f"📊 正常確率: {best_trial.user_attrs.get('normal_probability', 'N/A'):.3f}"
        )
        # print(f"🔥 故障確率: {best_trial.user_attrs.get('failure_probability', 'N/A'):.3f} (各)")
        print(f"🎲 シナリオ数: {best_trial.user_attrs.get('num_scenarios', 'N/A')}")
        print(f"📊 設置CS数: {best_trial.user_attrs.get('total_active_cs', 'N/A')}")
        print(f"🔌 総ポート数: {best_trial.user_attrs.get('total_ports', 'N/A')}")

        # 設置CS詳細
        active_cs_config = best_trial.user_attrs.get("active_cs_config", [])
        if active_cs_config:
            print("\n=== 設置CS詳細 ===")
            for i, cs_info in enumerate(active_cs_config):
                print(
                    f"  CS{i + 1}: CSID={cs_info['csid']}, ポート数={cs_info['ports']}, 容量={cs_info['capacity_kw']}kW"
                )

    # 最終クリーンアップ
    print("\n🎉 確率的最適化完了!")
