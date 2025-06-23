import optuna
import sys
import os
from datetime import datetime
import json
import pickle
import numpy as np
# プロジェクトのルートディレクトリをパスに追加
project_root = os.path.abspath(os.path.join(os.getcwd(), '..'))
if project_root not in sys.path:
    sys.path.append(project_root)
    
from src.simulation.run_emates import run_parallel_emates_simulations
from src.simulation.data_load import save_data_to_pickle
from src.util.path_manager import get_paths

# SAVEDIRをグローバル変数として初期化。
current_time = datetime.now().strftime('%Y%m%d_%H%M')
SAVE_DIR = current_time
os.makedirs(SAVE_DIR, exist_ok=True)

def total_costs_yearly(result_file) -> tuple:
    """充電ステーションのコスト計算:https://www.notion.so/2098044c3b9180acade1c42c52872eda?source=copy_link
    CSコスト：初期コスト＋運用コスト

    初期コストは以下の三つで構成される。
    1. 充電器本体コスト
    2. 変電設備コスト
    3. 一か所あたりの設置コスト

    運用コストは以下の三つで構成される。
    1. +保守コスト
    2. +電気料金（契約＋従量）
    3. -充電収益
    """
    # 
    # コストの定義-------------------------------------
    CHARGER_COST = {"50": 380, "90": 666, "100": 730} 
    SUBSTATION_COST_PER_KW = 2 # 万円/kw
    INSTALLATION_COST = 250 # 万円
    # 変数の設定-----------------------------------------
    # データ読み込み
    with open(result_file, 'rb') as f:
        emates_result = pickle.load(f)
    timeseries_kw = emates_result['time_series_kw']
    cs_config = emates_result['cs_config']
    
    capacity_list = cs_config['cap_kw']
    ports_list = cs_config['ports']
    actual_csids = timeseries_kw.columns.tolist()

    # 0ならNaNに
    capacity_list = [np.nan if cap == 0 else cap for cap in capacity_list]
    ports_list = [np.nan if port == 0 else port for port in ports_list]
    # ポート数と容量の配列を作成
    ports_array = np.array(ports_list)
    capacity_array = np.array(capacity_list)
    max_capacity = ports_array * capacity_array
    # -------------------------------------------
    
    # 1.充電器本体コスト
    charger_costs = np.array([CHARGER_COST[str(c)] for c in capacity_list])
    cs_costs = charger_costs * ports_array
    # 2.変電設備コスト
    substation_costs = (SUBSTATION_COST_PER_KW * max_capacity).reshape(-1)

    # 3.一か所あたりの設置コスト 
    installation_costs = np.array([INSTALLATION_COST] * len(actual_csids))
    total_installation_cost = installation_costs.sum()

    # 総コストの計算（充電器本体＋キュービクル＋工事コスト）
    initial_costs = cs_costs + substation_costs + installation_costs

    """運用コスト：
    保守＋電気料金（契約料金＋従量料金ー充電収益）
    CSごとのコストを計算する
    """
    # 1. コストの定義
    MAINTENANCE_COST_PER_YEAR = 30 # 万円/年.一か所あたり
    CONTRACT_COST_PER_KW_MONTH = 1911e-4 # 万円/kw
    USAGE_COST_PER_KWH_MONTH = 18e-4 # 万円/kWh
    CHARGING_PRICE_PER_KWH = 50e-4 # 万円/kWh
    # 2. 年間コスト計算
    maintainance_costs = np.array([MAINTENANCE_COST_PER_YEAR] * len(actual_csids))
    contract_costs = CONTRACT_COST_PER_KW_MONTH * max_capacity.reshape(-1) * 12 # 年間契約料金
    usage_costs = USAGE_COST_PER_KWH_MONTH * timeseries_kw.sum(axis=0) * 12 # 年間従量料金
    chaeging_revenue = CHARGING_PRICE_PER_KWH * timeseries_kw.sum(axis=0) * 12 # 年間充電収益
    # 3. 総コストの計算
    running_costs_yearly = maintainance_costs + contract_costs + usage_costs - chaeging_revenue

    # 初期コスト＋ 年間運用コスト（ベクター）
    total_costs = initial_costs + running_costs_yearly
    
    
    

    
    return total_costs.sum(), emates_result

def cs_placement_objective(trial):
    """CS配置最適化の目的関数"""
    paths = get_paths(1)  # worker_idは1と仮定
    # csList.txtの情報を取得
    cslist_file = paths['csList']
    with open(cslist_file, 'r') as f:
        cslist_data = f.readlines()
    cslist_data = [line.strip() for line in cslist_data if line.strip()]
    csids = [int(line.split(',')[0]) for line in cslist_data if line.strip()]
    ports_list = [int(line.split(',')[1]) for line in cslist_data if line.strip()]
    cap_kw_list = [int(line.split(',')[2]) for line in cslist_data if line.strip()]
    
    
    cs_config = {
        'csids': [],
        'ports': [],
        'cap_kw': []
    }
    for i, csid in enumerate(csids):
        # trialの最初は元々のデータを使用
        if trial.number == 0:
            ports = ports_list[i]
            capacity = cap_kw_list[i]
        else:        
            # 設置するかどうかを決定
            ports = trial.suggest_int(f'ports_{i}', 0, 4)
            if ports > 0:
                # 設置する場合のみ容量を決定
                capacity = trial.suggest_categorical(f'capacity_{i}', [50, 90, 100])
            else:
                # 設置しない場合は容量は任意（50に固定）
                capacity = 90
        # ✅ 修正：辞書に追加
        
        cs_config['csids'].append(csid)
        cs_config['ports'].append(ports)
        cs_config['cap_kw'].append(capacity)
        
    # 2. 制約チェック----------
    # 2.1. ポート数の合計が最大値を超えない
    total_ports = sum(cs_config['ports'])
    if total_ports > 17:  # 最大ポート数は17
        return float('inf')
    # 2.2. 設置箇所の数が最低2箇所
    # 2.2. 設置箇所の数が最低2箇所
    installed_locations = [i for i, port in enumerate(cs_config['ports']) if port > 0]
    if len(installed_locations) < 2:  # 最低2箇所は設置
        return float('inf')
    
    print(f"Trial {trial.number}: CS設定 = {cs_config}")

    #3. シミュレーション実行とコスト計算。evaluation_costを最小化したい！
    evaluation_cost, emates_results = simulate_and_calculate_cost(cs_config, trial)
    
    #4.ペナルティ
    # 最低限満たしてほしい条件：充電実現率80％以上の確保
    HOPED_CHARGING_RATE = 0.8
    vehicle_trip = emates_results['vehicle_trip']
    charging_loss = emates_results['charging_loss']
    
    num_charging_loss = len(charging_loss)
    num_charging_trip = len(vehicle_trip[vehicle_trip['startChargingTime'] != 0])
    satisfied_charging_rate = (num_charging_trip - num_charging_loss) / num_charging_trip
    if satisfied_charging_rate < HOPED_CHARGING_RATE:
        print(f"充電実現率が低い: {satisfied_charging_rate:.2%}。ペナルティを適用します。")
        # 実現率に応じたペナルティを追加
        evaluation_cost += (HOPED_CHARGING_RATE - satisfied_charging_rate) * 1000
    
    return evaluation_cost

def simulate_and_calculate_cost(cs_configs, trial) -> tuple:
    
    """シミュレーション実行とコスト計算（ダミー）"""
    # シミュレーションの実行

    run_parallel_emates_simulations(base_config=cs_configs, parallel_count=1)
    
    # データの保存

    results_filename = f"trial_{trial.number}.pkl"
    results_filepath = os.path.join(SAVE_DIR, results_filename)

    save_data_to_pickle(worker_id=1, filename=results_filepath)
    
    # 評価コストの計算
    evaluation_cost, emates_results = total_costs_yearly(result_file=results_filepath)
    
    return evaluation_cost, emates_results

# 最適化実行
study = optuna.create_study(direction='minimize')
study.optimize(cs_placement_objective, n_trials=50)

print(f"最適コスト: {study.best_value}")
print(f"最適配置: {study.best_params}")

# Optuna実行後のデータ保存

# 最適化結果の保存
optimization_results = {
    'best_value': study.best_value,
    'best_params': study.best_params,
    'n_trials': len(study.trials),
    'optimization_time': datetime.now().strftime('%Y%m%d_%H:%M:%S')
}

# 各試行の結果を保存
trials_data = []
for trial in study.trials:
    trial_info = {
        'number': trial.number,
        'value': trial.value,
        'params': trial.params,
        'state': trial.state.name
    }
    trials_data.append(trial_info)

optimization_results['trials'] = trials_data

# JSONファイルとして保存
results_dir = 'optimization_results'
os.makedirs(results_dir, exist_ok=True)

with open(os.path.join(results_dir, 'optuna_results.json'), 'w', encoding='utf-8') as f:
    json.dump(optimization_results, f, indent=2, ensure_ascii=False)

# Studyオブジェクト（学習済みモデル）を保存
study_filename = os.path.join(results_dir, 'optuna_study.pkl')
with open(study_filename, 'wb') as f:
    pickle.dump(study, f)

print(f"最適化結果を {results_dir}/optuna_results.json に保存しました")
print(f"学習済みStudyオブジェクトを {study_filename} に保存しました")