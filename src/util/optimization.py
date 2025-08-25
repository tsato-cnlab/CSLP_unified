import pickle
import os
import numpy as np
import pandas as pd
import sys
from pathlib import Path

# プロジェクトのルートディレクトリをパスに追加
project_root = os.path.abspath(os.path.join(os.getcwd()))
if project_root not in sys.path:
    sys.path.append(project_root)
# print(f'プロジェクトのルートディレクトリ: {project_root}')

from src.util.path_manager import get_paths
from src.util.vis_result import get_waiting_times
# from src.simulation.data_loader import load_vehicle_trip

# 目的関数の指標
# ==========
def evaluation_total_costs(result_file) -> tuple:
    """年間の総コストを計算"""
    YEAR = 5
    DISCOUNT_RATE = 0.03
    # データ読み込み
    with open(result_file, 'rb') as f:
        emates_result = pickle.load(f)
    timeseries_kw = emates_result['time_series_kw']
    cs_config = emates_result['cs_config']
    vehicle_trip = emates_result['vehicle_trip']
    
    # 初期コストとランニングコストの計算
    initial_costs = calc_initial_costs(cs_config, timeseries_kw)
    running_costs_yearly = calc_running_costs(cs_config, timeseries_kw)
    
    # 年間コストの割引計算
    running_costs_discounted = sum(
        (running_costs_yearly / ((1 + DISCOUNT_RATE) ** i)) for i in range(1, YEAR + 1)
    )
    # ユーザーコストの計算(ベースラインとの差分を計算)
    _, diff_transport_costs = calc_diff_trnsprt_costs(vehicle_trip)
    # ユーザーコストの割引計算
    additional_costs_discounted = sum(
        (diff_transport_costs / ((1 + DISCOUNT_RATE) ** i)) for i in range(1, YEAR + 1)
    )

    total_costs = initial_costs + running_costs_discounted + additional_costs_discounted
    
    return total_costs, emates_result

def calc_initial_costs(cs_config, timeseries_kw)-> float:
    """初期コストの計算"""
    CHARGER_COST = {"50": 380, "90": 666, "100": 730}
    SUBSTATION_COST_PER_KW = 2
    INSTALLATION_COST = 250
    
    capacity_list = cs_config['cap_kw']
    ports_list = cs_config['ports']
    ports_array = np.array(ports_list)
    capacity_array = np.array(capacity_list)
    max_capacity = ports_array * capacity_array
    charger_costs = np.array([CHARGER_COST[str(c)] for c in capacity_list])
    cs_costs = charger_costs * ports_array
    substation_costs = (SUBSTATION_COST_PER_KW * max_capacity).reshape(-1)
    installation_costs = np.array([INSTALLATION_COST] * len(ports_list))
    initial_costs = cs_costs + substation_costs + installation_costs
    return initial_costs.sum()

def calc_running_costs(cs_config, timeseries_kw)-> float:
    """年間のランニングコストの計算"""
    MAINTENANCE_COST_PER_YEAR = 30
    CONTRACT_COST_PER_KW_MONTH = 1911e-4
    USAGE_COST_PER_KWH_MONTH = 18e-4
    CHARGING_PRICE_PER_KWH = 50e-4
    
    ports_array = np.array(cs_config['ports'])
    capacity_array = np.array(cs_config['cap_kw'])
    max_capacity = ports_array * capacity_array
    maintainance_costs = np.array([MAINTENANCE_COST_PER_YEAR] * len(ports_array))
    contract_costs = CONTRACT_COST_PER_KW_MONTH * max_capacity.reshape(-1) * 12
    usage_costs = USAGE_COST_PER_KWH_MONTH * timeseries_kw.sum(axis=0) * 12
    charging_revenue = CHARGING_PRICE_PER_KWH * timeseries_kw.sum(axis=0) * 12
    running_costs_yearly = maintainance_costs + contract_costs + usage_costs - charging_revenue
    return running_costs_yearly.sum()

def calc_diff_trnsprt_costs(vehicle_trip: pd.DataFrame) -> float:
    """輸送コストの計算"""
    TIME_VALUE_OF_MONEY = 1118*1e-4  # 時間あたりの価値（円/時）
    RESULT_PATH_NOCS = r'\\wsl.localhost\Ubuntu-22.04\home\tsato-cnlab\Emates\eMATES_2308\network\simple_shikata\result\no_charging_station'
    # 充電ありの総旅行時間
    trip_time = _calc_trip_time(vehicle_trip)
    charging_trip = vehicle_trip[vehicle_trip['startChargingTime'] > 0]
    waiting_times_hour = (charging_trip['startChargingTime'] - charging_trip['WaitingEntryTime']) / 3600  # 時間単位に変換
    total_waiting_times = np.sum(waiting_times_hour)
    # 充電ありと充電なしの総旅行時間の差分
    # baseline_trip_time = _calc_baseline_trip_time(RESULT_PATH_NOCS)
    # diff_trip_time = trip_time - baseline_trip_time
    diff_trip_time = trip_time - 6062.5865
    
    # 時間あたりの価値を掛けて輸送コストを計算(待ち時間は2倍の価値を持つと仮定)
    transport_costs = ((diff_trip_time - total_waiting_times) + 2 * total_waiting_times) * TIME_VALUE_OF_MONEY  # 時間単位に変換
    # 年間の輸送コストを計算
    transport_costs_yearly = transport_costs * 365  # 年単位に変換
    return diff_trip_time, transport_costs_yearly

def _calc_baseline_trip_time(RESULT_PATH_NOCS = r'\\wsl.localhost\Ubuntu-22.04\home\tsato-cnlab\Emates\eMATES_2308\network\simple_shikata\result\no_charging_station') -> float:
    """CSなし状態の総旅行時間を計算"""
    vehicle_trip_noCS = load_vehicle_trip(Path(RESULT_PATH_NOCS))
    # 全ドライバーの総旅行時間（充電なし）
    baseline_trip_time = _calc_trip_time(vehicle_trip_noCS)
    return baseline_trip_time

def _calc_trip_time(vehicle_trip: pd.DataFrame) -> float:
    """CSあり状態の総旅行時間を計算"""
    total_trip_time = vehicle_trip['EndTime'].fillna(86400) - vehicle_trip['StartTime']
    total_trip_time = total_trip_time.sum() / 3600  # 時間単位に変換
    return total_trip_time

def load_vehicle_trip(result_dir: Path) -> pd.DataFrame:
    """走行データの読み込み"""
    vehicle_trip_path = result_dir / "vehicleTrip.txt"
    if not vehicle_trip_path.exists():
        return pd.DataFrame()
    
    df = pd.read_csv(
        vehicle_trip_path, sep=r',',usecols=[0, 2, 3, 4, 5, 8,9,10,11, 14],
        names=['EVID','StartTime', 'EndTime', 'WaitingEntryTime','startChargingTime',
                'startID','goalID','tripLength','CSID', 'InitialSOC'],
        dtype=str
    )
            # 特殊文字の処理
    def clean_numeric_value(value):
        """数値変換前の前処理"""
        if pd.isna(value) or value == '' or value == '******':
            return np.nan
        try:
            return float(value)
        except (ValueError, TypeError):
            return np.nan
    
    # 各列を適切な型に変換
    numeric_columns = ['EVID', 'StartTime', 'EndTime', 'WaitingEntryTime', 
                    'startChargingTime', 'startID', 'goalID', 'tripLength', 
                    'CSID', 'InitialSOC']
    
    for col in numeric_columns:
        if col in df.columns:
            df[col] = df[col].apply(clean_numeric_value)
    
    # 時間をmsから秒に変換
    time_cols = ['StartTime', 'EndTime', 'WaitingEntryTime', 'startChargingTime']
    for col in time_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce') / 1000
    
    return df

def calc_user_costs(vehicle_trip: pd.DataFrame) -> float:
    """ユーザーコストの計算"""
    TIME_VALUE_OF_MONEY = 1118/60  # 時間あたりの価値（円/分）
    trip_summary = _get_od_trip_times(vehicle_trip)
    additional_costs = TIME_VALUE_OF_MONEY * trip_summary['add_time_for_charging'].sum()
    return additional_costs

def _get_od_trip_times(vehicle_trip: pd.DataFrame) -> pd.DataFrame:
    """OD別・時間帯別の平均旅行時間を計算する関数"""
    # 充電した車両と充電しなかった車両を分ける
    charging_trip = vehicle_trip[vehicle_trip['startChargingTime'] > 0]
    no_charging_trip = vehicle_trip[vehicle_trip['startChargingTime'] == 0]
    
    charging_trip, no_charging_trip = _add_vehicle_trip_columns(charging_trip, no_charging_trip)
    # 目的地のリストを取得
    destination_list = vehicle_trip['goalID'].unique().tolist()
    destination_list = [dest for dest in destination_list if dest <= 900000]
    destination_list.sort()
#   # 目的地ごとの旅行時間をOD別にまとめる
    trip_summary = {
                'destination': destination_list,
                'charging': [],
                'no_charging': [],
                'add_time_for_charging': []
                }
    # 目的地ごとに充電ありとなしの旅行時間を計算
    for destination in destination_list:
        od_charging = charging_trip[charging_trip['goalID'] == destination]
        od_no_charging = no_charging_trip[no_charging_trip['goalID'] == destination]
        
        od_charging_summary = od_charging.groupby('time_slot')['trip_time'].mean().reset_index()
        od_no_charging_summary = od_no_charging.groupby('time_slot')['trip_time'].mean().reset_index()
        
        trip_summary['charging'].append(od_charging_summary['trip_time'])
        trip_summary['no_charging'].append(od_no_charging_summary['trip_time'])
        trip_summary['add_time_for_charging'].append(od_charging_summary['trip_time'].mean() - od_no_charging_summary['trip_time'].mean())
    # データフレームに変換
    return pd.DataFrame(trip_summary)

def _add_vehicle_trip_columns(charging_trip: pd.DataFrame, no_charging_trip: pd.DataFrame)-> tuple:
    """充電した車両と充電しなかった車両の旅行時間と時間帯を追加する関数"""
    time = pd.to_datetime(charging_trip['StartTime'], unit='s')
    charging_trip['trip_time'] = (charging_trip['EndTime'] - charging_trip['StartTime'])/ 60  # 分単位に変換
    charging_trip['time_slot'] = pd.cut(time.dt.hour, bins=np.arange(0, 25, 1), right=False)
    
    time_no_charging = pd.to_datetime(no_charging_trip['StartTime'], unit='s')
    no_charging_trip['trip_time'] = (no_charging_trip['EndTime'] - no_charging_trip['StartTime']) / 60  # 分単位に変換
    no_charging_trip['time_slot'] = pd.cut(time_no_charging.dt.hour, bins=np.arange(0, 25, 1), right=False)
    
    return charging_trip, no_charging_trip

# 制約条件の定義
# ==========
def check_cs_placement(cs_config: dict) -> bool:
    installed_locations = [i for i, port in enumerate(cs_config['ports']) if port > 0]
    if len(installed_locations) < 2:  # 最低2箇所は設置
        return False
    
    # ほかに制約があればここに追加
    # ....
    return True


# OptunaでCSのパラメータを設定する関数
# ==========
def set_cs_placement(trial, worker_id = 1) -> dict:
    if worker_id is None:
        paths = get_paths()
    else:
        paths = get_paths(worker_id)
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
                capacity = trial.suggest_categorical(f'capacity_{i}', [50, 100])
            else:
                # 設置しない場合は容量は任意（50に固定）
                capacity = 90
        # ✅ 修正：辞書に追加
        
        cs_config['csids'].append(csid)
        cs_config['ports'].append(ports)
        cs_config['cap_kw'].append(capacity)
    return cs_config

# 故障シナリオを作成する関数
# =========
def create_failure_info_for_worker(cs_config: dict, failure_cs_index: int, worker_id: int, FAILURE_TIME = [12]) -> None:
    """指定されたワーカー用に故障情報を作成"""
    time_interval = 3600  # 1時間ごと
    max_time = 24 * 3600  # 24時間
    failure_time = [3600 * time for time in FAILURE_TIME]  # 12時に故障
    print(failure_time)


    # 指定されたワーカーのパスを取得
    paths = get_paths(worker_id)
    OPENDSS_PATH = f'{paths["result"]}/opendss'
    
    # opendssディレクトリが存在しない場合は作成
    os.makedirs(OPENDSS_PATH, exist_ok=True)
    
    var_names = ["Type", "Node", "Csid", "Chgrid", "kW_0min", 
                "kW_60min", "kW_120min", "Yen_0min", "Yen_60min", "Yen_120min"]
    
    for time in range(0, max_time + time_interval, time_interval):
        rows = []
        
        for cs_idx, (csid, ports, cap_kw) in enumerate(zip(cs_config['csids'], cs_config['ports'], cs_config['cap_kw'])):
            if ports == 0:  # 設置されていないCSはスキップ
                continue
            # csvファイルの行を作成 
            for chgrid in range(ports):
                # 故障時間かつ指定されたCSの場合
                if time in failure_time and cs_idx == failure_cs_index:
                    # 故障CSは出力を0に設定
                    row = [
                        "F",         # Type
                        "Any",       # Node
                        csid,        # Csid
                        chgrid,      # Chgrid
                        0,           # kW_0min (故障のため0)
                        -1,          # kW_60min
                        -1,          # kW_120min
                        -1,          # Yen_0min
                        -1,          # Yen_60min
                        -1           # Yen_120min
                    ]
                else:
                    # 通常の出力設定
                    row = [
                        "F",         # Type
                        "Any",       # Node
                        csid,        # Csid
                        chgrid,      # Chgrid
                        cap_kw,      # kW_0min
                        -1,          # kW_60min
                        -1,          # kW_120min
                        -1,          # Yen_0min
                        -1,          # Yen_60min
                        -1           # Yen_120min
                    ]
                rows.append(row)
        
        # CSVファイルに保存
        E_filename = f"E{time+1:06d}"
        df = pd.DataFrame(rows, columns=var_names)
        save_Efile_path = f"{OPENDSS_PATH}/{E_filename}.csv"
        df.to_csv(save_Efile_path, index=False)

# 95パーセンタイル待ち時間の計算
# ==========
def calculate_95percentile_wait_time(result_file: str) -> float:
    """95パーセンタイル待ち時間を計算"""
    with open(result_file, 'rb') as f:
        emates_result = pickle.load(f)
    
    vehicle_trip = emates_result['vehicle_trip']
    
    # 充電を行ったトリップのみを抽出
    charging_trip = vehicle_trip[vehicle_trip['startChargingTime'] != 0].copy()
    
    if len(charging_trip) == 0:
        return float('inf')  # 充電できなかった場合は無限大
    
    # 完了した充電のみを対象（EndTimeがNaNでない）
    completed_charging = charging_trip[~charging_trip['EndTime'].isna()].copy()
    
    if len(completed_charging) == 0:
        return float('inf')  # 完了した充電がない場合は無限大
    
    # 待ち時間を計算
    waiting_times = (completed_charging['startChargingTime'].values - 
                    completed_charging['WaitingEntryTime'].values)
    
    # 95パーセンタイル待ち時間を計算
    wait_time_95p = np.percentile(waiting_times, 95)
    
    return wait_time_95p

if __name__ == "__main__":
    # テスト用のコード
    # ここにテストコードを追加することができます
    # cs_config = {
    #     'csids': [1, 2, 3],
    #     'ports': [2, 0, 1],
    #     'cap_kw': [50, 0, 100]
    # }
    # create_failure_info_for_worker(cs_config, failure_cs_index=0, worker_id=1)
    
    result_file = r'C:\Users\echiz\00_研究コード\eMATES解析_GA\emates\notebooks\20250820_1819_7PM\trial_137_worker_1.pkl'
    with open(result_file, 'rb') as f:
        data = pickle.load(f)
        vehicle_trip = data['vehicle_trip']
    diff_trip_time, transport_costs_yearly = calc_diff_trnsprt_costs(vehicle_trip)
    print(f"総旅行時間の差分: {diff_trip_time} 時間")
    print(f"年間輸送コスト: {transport_costs_yearly}万円")