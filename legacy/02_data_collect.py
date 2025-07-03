import pandas as pd
from pathlib import Path
import re
from src.util.path_manager import get_paths

def load_T_files(emates_dir):
    """
    ematesディレクトリ内のTファイル（T000060.csvなど）をすべて読み込んで連結する
    """
    t_files = sorted(
        emates_dir.glob("T*.csv"),
        key=lambda x: int(re.search(r"T(\d{6})", x.stem).group(1))
    )
    t_dfs = []
    for f in t_files:
        elapsed = int(re.search(r"T(\d{6})", f.stem).group(1))
        df = pd.read_csv(f)
        df['ElapsedTime'] = elapsed
        t_dfs.append(df)
    if t_dfs:
        return pd.concat(t_dfs, ignore_index=True)
    else:
        return pd.DataFrame()

def load_worker_data(worker_id):
    """
    worker_idを指定してシミュレーション結果を収集
    """
    paths = get_paths(worker_id)
    result_dir = Path(paths["res"])
    emates_dir = result_dir / "emates"
    t_data = load_T_files(emates_dir)
    
    # chargingLoss
    charging_loss_path = result_dir / "chargingLoss.txt"
    charging_loss = pd.read_csv(
        charging_loss_path, sep=r'\s+',
        names=['Time', 'EVID', 'CSID', 'WaitingNum', 'NumPorts', 'SOC']
    )
    
    # vehicleTrip
    vehicle_trip_path = result_dir / "vehicleTrip.txt"
    vehicle_trip = pd.read_csv(
        vehicle_trip_path, sep=r'\s+',
        names=['StartTime', 'EndTime', 'CSID', 'InitialSOC']
    )
    
    return {
        "worker_id": worker_id,
        "result_dir": result_dir,
        "T": t_data,
        "chargingLoss": charging_loss,
        "vehicleTrip": vehicle_trip
    }

def collect_all_results(max_workers=100):
    """
    worker_id=1からmax_workersまで順にget_pathsでパスを取得し、存在するものだけデータ収集
    """
    all_results = []
    for worker_id in range(1, max_workers+1):
        paths = get_paths(worker_id)
        result_dir = Path(paths["res"])
        if result_dir.exists():
            data = load_worker_data(worker_id)
            all_results.append(data)
        else:
            # 連番で存在しないworker_idが出たら終了（途中欠番がなければ）
            break
    return all_results

def save_results_to_csv(all_results, output_dir='results'):
    """
    収集したデータをCSVファイルとして保存
    
    Parameters:
        all_results (list): collect_all_results()で収集したデータのリスト
        output_dir (str): 出力ディレクトリ
    """
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    # T（時系列）データの結合と保存
    t_dfs = []
    for result in all_results:
        df = result['T']
        df['worker_id'] = result['worker_id']
        t_dfs.append(df)
    
    if t_dfs:
        pd.concat(t_dfs, ignore_index=True).to_csv(
            output_path / 'time_series_data.csv', index=False
        )
    
    # 充電ロスデータの結合と保存
    charging_dfs = []
    for result in all_results:
        df = result['chargingLoss']
        df['worker_id'] = result['worker_id']
        charging_dfs.append(df)
    
    if charging_dfs:
        pd.concat(charging_dfs, ignore_index=True).to_csv(
            output_path / 'charging_loss_data.csv', index=False
        )
    
    # 走行データの結合と保存
    trip_dfs = []
    for result in all_results:
        df = result['vehicleTrip']
        df['worker_id'] = result['worker_id']
        trip_dfs.append(df)
    
    if trip_dfs:
        pd.concat(trip_dfs, ignore_index=True).to_csv(
            output_path / 'vehicle_trip_data.csv', index=False
        )

if __name__ == "__main__":
    all_results = collect_all_results()
    print(f"取得したワーカー数: {len(all_results)}")
    
    # データをCSVファイルとして保存
    save_results_to_csv(all_results)
    print("データの保存が完了しました")
