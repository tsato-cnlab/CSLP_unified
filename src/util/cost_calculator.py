"""コスト計算関数群

設計意図:
- 単一責任の原則: このモジュールはコスト計算のみに特化
- 純粋関数: 副作用なし、テストしやすい
- 定数の明示化: マジックナンバーを避け、定数として定義
"""
import pickle
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Tuple

# コスト計算の定数（設計意図: ハードコーディングを避け、一箇所で管理）
YEAR = 5
DISCOUNT_RATE = 0.03
CHARGER_COST = {"50": 380, "90": 666, "100": 730}  # kWごとの充電器コスト（万円）
SUBSTATION_COST_PER_KW = 2  # 変電所コスト（万円/kW）
INSTALLATION_COST = 250  # 設置コスト（万円）

MAINTENANCE_COST_PER_YEAR = 30  # 年間保守コスト（万円）
CONTRACT_COST_PER_KW_MONTH = 1911e-4  # 契約コスト（万円/kW/月）
USAGE_COST_PER_KWH = 18e-4  # 使用コスト（万円/kWh/月）
CHARGING_PRICE_PER_KWH = 50e-4  # 充電価格（万円/kWh）

TIME_VALUE_OF_MONEY = 1118 * 1e-4  # 時間価値（万円/時）
AVG_CHARGING_TIME = 0.5  # 平均充電時間（時間）- 終了時待ち台数ペナルティ用
# ベースライン旅行時間（時）（設計意図: 毎回計算せず固定値化）
BASELINE_TRIP_TIME = 6068.83  # 24時間運用時の値
BASELINE_TRIP_TIME = 6073.559 # 26時間運用時の値

def evaluation_total_costs(result_file: str) -> Tuple[float, dict]:
    """年間の総コストを計算

    設計意図:
    - トップレベル関数として全コストを統合
    - 結果ファイルから必要なデータを読み込み、各種コストを計算
    - 返り値にemates_resultを含めることで、呼び出し側での再読み込みを回避
    """
    with open(result_file, 'rb') as f:
        emates_result = pickle.load(f)

    # 辞書型とオブジェクト型の両方に対応
    if isinstance(emates_result, dict):
        timeseries_kw = emates_result.get('time_series_kw')
        cs_config = emates_result.get('cs_config')
        vehicle_trip = emates_result.get('vehicle_trip')
        waiting_line = emates_result.get('waiting_line')
    else:
        timeseries_kw = emates_result.time_series_kw
        cs_config = emates_result.cs_config
        vehicle_trip = emates_result.vehicle_trip
        waiting_line = emates_result.waiting_line

    # 各コストを計算
    initial_costs = calc_initial_costs(cs_config, timeseries_kw)
    running_costs_yearly = calc_running_costs(cs_config, timeseries_kw)

    # 年間コストの割引計算（設計意図: 時間価値を考慮した正確なコスト評価）
    running_costs_discounted = sum(
        (running_costs_yearly / ((1 + DISCOUNT_RATE) ** i)) for i in range(1, YEAR + 1)
    )

    # ユーザーコスト（ベースラインとの差分）
    _, diff_transport_costs = calc_diff_trnsprt_costs(vehicle_trip)
    additional_costs_discounted = sum(
        (diff_transport_costs / ((1 + DISCOUNT_RATE) ** i)) for i in range(1, YEAR + 1)
    )

    # 終了時待ち台数ペナルティ
    waiting_penalty = calc_ending_waiting_penalty(waiting_line)
    waiting_penalty_discounted = sum(
        (waiting_penalty / ((1 + DISCOUNT_RATE) ** i)) for i in range(1, YEAR + 1)
    )

    # 未充電車両ペナルティ
    uncharged_penalty = calc_uncharged_penalty(vehicle_trip)
    uncharged_penalty_discounted = sum(
        (uncharged_penalty / ((1 + DISCOUNT_RATE) ** i)) for i in range(1, YEAR + 1)
    )

    total_costs = (initial_costs + running_costs_discounted + 
                   additional_costs_discounted + waiting_penalty_discounted +
                   uncharged_penalty_discounted)

    return total_costs, emates_result


def calc_initial_costs(cs_config: dict, timeseries_kw: pd.DataFrame) -> float:
    """初期コストの計算

    設計意図:
    - NumPy配列操作でベクトル化し、ループを避ける（高速化）
    - cs_configを辞書で受け取るが、将来的にはCSConfigデータクラスに置き換え予定
    """
    capacity_list = cs_config['cap_kw']
    ports_list = cs_config['ports']

    ports_array = np.array(ports_list)
    capacity_array = np.array(capacity_list)
    max_capacity = ports_array * capacity_array

    # 充電器コスト
    charger_costs = np.array([CHARGER_COST[str(c)] for c in capacity_list])
    cs_costs = charger_costs * ports_array

    # 変電所コスト
    substation_costs = (SUBSTATION_COST_PER_KW * max_capacity).reshape(-1)

    # 設置コスト
    installation_costs = np.array([INSTALLATION_COST] * len(ports_list))

    initial_costs = cs_costs + substation_costs + installation_costs
    return initial_costs.sum()

def calc_running_costs(cs_config: dict, timeseries_kw: pd.DataFrame) -> float:
    """年間のランニングコストの計算

    設計意図:
    - 収益（充電料金）を考慮した純コストを計算
    - 時系列データを集約して月次コストに換算
    """
    ports_array = np.array(cs_config['ports'])
    capacity_array = np.array(cs_config['cap_kw'])
    max_capacity = ports_array * capacity_array
    daily_kwh = timeseries_kw.sum(axis=0) /60  # 各CSの日kWh使用量

    # 各種ランニングコスト
    maintainance_costs = np.array([MAINTENANCE_COST_PER_YEAR] * len(ports_array))
    contract_costs = CONTRACT_COST_PER_KW_MONTH * max_capacity.reshape(-1) * 12

    # 収益（マイナス要素）
    charging_revenue = (CHARGING_PRICE_PER_KWH - USAGE_COST_PER_KWH) * daily_kwh * 365

    running_costs_yearly = maintainance_costs + contract_costs - charging_revenue
    return running_costs_yearly.sum()


def calc_diff_trnsprt_costs(vehicle_trip: pd.DataFrame) -> Tuple[float, float]:
    """輸送コストの計算（ベースラインとの差分）

    設計意図:
    - 待ち時間を2倍の価値で評価（ユーザーにとって待ち時間は特に不快）
    - ベースライン旅行時間を固定値化（毎回計算すると時間がかかるため）

    Args:
        vehicle_trip: 車両トリップデータ

    Returns:
        (差分旅行時間, 年間輸送コスト)
    """
    # 旅行時間計算
    trip_time_hour = _calc_trip_time(vehicle_trip)

    # 充電待ち時間
    charging_trip = vehicle_trip[vehicle_trip['startChargingTime'] > 0]
    waiting_times_hour = (charging_trip['startChargingTime'] - charging_trip['WaitingEntryTime']) / 3600
    total_waiting_times = np.sum(waiting_times_hour)
    print(f"総待ち時間（時間）: {total_waiting_times:.2f} 時間")
    print(f"総旅行時間（時間）: {trip_time_hour:.2f} 時間")
    print(f"ベースライン旅行時間（時間）: {BASELINE_TRIP_TIME:.2f} 時間")

    # ベースラインとの差分
    diff_trip_time = trip_time_hour - BASELINE_TRIP_TIME

    # 時間価値を考慮したコスト（待ち時間は2倍）
    transport_costs = ((diff_trip_time - total_waiting_times) + 2 * total_waiting_times) * TIME_VALUE_OF_MONEY
    transport_costs_yearly = transport_costs * 365

    return diff_trip_time, transport_costs_yearly


def calc_ending_waiting_penalty(waiting_line: pd.DataFrame) -> float:
    """終了時の待ち台数を時間換算してペナルティ計算
    
    設計意図:
    - シミュレーション終了時点で待ち行列に残った車両に対するペナルティ
    - 待ち台数 × 平均充電時間 × 時間価値（2倍）で算出
    - 充電機会損失 + 顧客満足度低下を反映
    
    Args:
        waiting_line: 時系列の待ち台数DataFrame (index=ElapsedTime, columns=CSID)
    
    Returns:
        年間ペナルティ（万円）
    """
    if waiting_line is None or waiting_line.empty:
        return 0.0
    
    # 最終時刻の待ち台数を取得
    final_waiting = waiting_line.iloc[-1].sum()
    
    # 待ち時間換算: 待ち台数 × 平均充電時間
    estimated_wait_hours = final_waiting * AVG_CHARGING_TIME
    
    # 時間価値で換算（待ち時間は2倍）
    penalty_daily = estimated_wait_hours * 2 * TIME_VALUE_OF_MONEY
    penalty_yearly = penalty_daily * 365
    
    if final_waiting > 0:
        print(f"終了時待ち台数: {final_waiting:.0f} 台")
        print(f"推定待ち時間: {estimated_wait_hours:.1f} 時間")
        print(f"待ち台数ペナルティ: {penalty_yearly:.1f} 万円/年")
    
    return penalty_yearly


def calc_uncharged_penalty(vehicle_trip: pd.DataFrame) -> float:
    """充電すべきなのに充電していない車両のペナルティ計算
    
    設計意図:
    - 待ち行列ペナルティと同様の時間換算ロジック
    - 充電機会損失 + 顧客満足度低下を反映
    - InitialSOC≤20%の車両が充電していない場合にペナルティ
    
    Args:
        vehicle_trip: 車両トリップデータ（InitialSOCカラムを含む）
    
    Returns:
        年間ペナルティ（万円）
    """
    if vehicle_trip is None or vehicle_trip.empty:
        return 0.0
    
    # InitialSOC列が存在しない場合は0を返す
    if 'InitialSOC' not in vehicle_trip.columns:
        print("Warning: InitialSOC列が見つかりません。未充電ペナルティは0です。")
        return 0.0
    
    # 1. InitialSOC≤20%の車両を特定
    SOC_THRESHOLD = 0.20
    target_vehicles = vehicle_trip[
        (vehicle_trip['InitialSOC'] <= SOC_THRESHOLD) & 
        (vehicle_trip['InitialSOC'] >= 0)
    ]
    target_count = len(target_vehicles)
    
    if target_count == 0:
        return 0.0
    
    # 2. うち充電していない車両を抽出
    uncharged = target_vehicles[
        (target_vehicles['startChargingTime'] == 0) | 
        (target_vehicles['startChargingTime'].isna())
    ]
    uncharged_count = len(uncharged)
    
    if uncharged_count == 0:
        print(f"充電対象車両: {target_count} 台")
        print(f"未充電車両: 0 台 (充電率100%)")
        return 0.0
    
    # 3. ペナルティ計算
    # 未充電車両 × 平均充電時間 × 時間価値 × 2倍（顧客不満）
    estimated_loss_hours = uncharged_count * AVG_CHARGING_TIME
    penalty_daily = estimated_loss_hours * 2 * TIME_VALUE_OF_MONEY
    penalty_yearly = penalty_daily * 365
    
    print(f"充電対象車両（InitialSOC≤{SOC_THRESHOLD*100:.0f}%）: {target_count} 台")
    print(f"未充電車両: {uncharged_count} 台 ({uncharged_count/target_count*100:.1f}%)")
    print(f"推定損失時間: {estimated_loss_hours:.1f} 時間")
    print(f"未充電ペナルティ: {penalty_yearly:.1f} 万円/年")
    
    return penalty_yearly


def _calc_trip_time(vehicle_trip: pd.DataFrame) -> float:
    """総旅行時間を計算（内部関数）

    設計意図:
    - アンダースコアプレフィックスで内部関数であることを明示
    - 単純な計算だが、再利用性のため関数化
    """
    total_trip_time = vehicle_trip['EndTime'].fillna(86400) - vehicle_trip['StartTime']
    print(f"車両数: {len(vehicle_trip)} 台")
    total_trip_time = total_trip_time.sum() / 3600  # 時間単位に変換
    return total_trip_time


def calculate_95percentile_wait_time(result_file: str) -> float:
    """95パーセンタイル待ち時間を計算

    設計意図:
    - 平均ではなくパーセンタイルを使用（外れ値の影響を抑える）
    - 95%という値は、ほとんどのユーザーが経験する最悪ケースを表す
    """
    with open(result_file, 'rb') as f:
        emates_result = pickle.load(f)

    # 辞書型とオブジェクト型の両方に対応
    if isinstance(emates_result, dict):
        vehicle_trip = emates_result.get('vehicle_trip')
    else:
        vehicle_trip = emates_result.vehicle_trip

    # 充電を行ったトリップのみを抽出
    charging_trip = vehicle_trip[vehicle_trip['startChargingTime'] != 0].copy()

    if len(charging_trip) == 0:
        return float('inf')  # 充電できなかった場合は無限大

    # 完了した充電のみを対象
    completed_charging = charging_trip[~charging_trip['EndTime'].isna()].copy()

    if len(completed_charging) == 0:
        return float('inf')

    # 待ち時間を計算
    waiting_times = (completed_charging['startChargingTime'].values -
                    completed_charging['WaitingEntryTime'].values)

    wait_time_95p = np.percentile(waiting_times, 95)
    return wait_time_95p
