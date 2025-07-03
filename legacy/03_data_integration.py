import pandas as pd
import numpy as np
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import logging
from tqdm import tqdm
from typing import List, Dict
from src.util.path_manager import get_paths

def get_project_root() -> Path:
    """プロジェクトのルートディレクトリを取得"""
    return Path(__file__).parent

def process_time_series(dir_path: Path, charging_locations: List[int]) -> Dict:
    """時系列データの処理"""
    t_files = sorted(dir_path.glob('T*.csv'))
    
    # 最初のファイルからCSIDを取得
    first_df = pd.read_csv(t_files[0])
    unique_csids = first_df['Csid'].unique()
    charging_locations = sorted(set([csid // 100 for csid in unique_csids]))
    
    # 結果格納用の辞書
    result = {
        'time': [],
        'waiting': [],
        'demand': [],
        'utilization': [],
        'csids': unique_csids,
        'charging_locations': charging_locations,
        'total_ports': len(unique_csids)
    }
    
    for t_file in tqdm(t_files, desc="Processing time series"):
        time = int(t_file.stem[1:])  # T000060 -> 60
        df = pd.read_csv(t_file)
        
        waiting = []
        demand = []
        utilization = []
        
        for loc in charging_locations:
            loc_mask = df['Csid'] // 100 == loc
            loc_data = df[loc_mask]
            
            # 待ち台数
            waiting.append(loc_data['waitingLine'].sum())
            
            # 充電需要
            current_demand = loc_data['Cap_kW'].sum()
            demand.append(current_demand)
            
            # 利用率
            max_cap = loc_data['Cap_kW'].iloc[0] * len(loc_data) if len(loc_data) > 0 else 1
            utilization.append(current_demand / max_cap if max_cap > 0 else 0)
        
        result['time'].append(time)
        result['waiting'].append(waiting)
        result['demand'].append(demand)
        result['utilization'].append(utilization)
    
    # NumPy配列に変換
    result['time'] = np.array(result['time'])
    result['waiting'] = np.array(result['waiting'])
    result['demand'] = np.array(result['demand'])
    result['utilization'] = np.array(result['utilization'])
    
    return result

def process_charging_loss(result_dir: Path) -> pd.DataFrame:
    """充電損失データの処理"""
    charging_loss_path = result_dir / "chargingLoss.txt"
    
    # MATLABの定義に合わせたカラム名と型
    columns = ['Time', 'EVID', 'CSID', 'WaitingNum', 'NumPorts', 'SOC']
    dtypes = {col: 'float64' for col in columns}
    
    try:
        df = pd.read_csv(
            charging_loss_path,
            sep=r',',
            names=columns,
            dtype=dtypes
        )
        return df
    except Exception as e:
        logging.error(f"充電損失データの読み込みエラー: {str(e)}")
        return pd.DataFrame(columns=columns)

def process_vehicle_trip(result_dir: Path) -> pd.DataFrame:
    """車両走行データの処理
    入力データ例：
    非充電: 000011,81,31100,267800,0,0,0,236700,001437,000169,5170.17,,0.797804,000169,0.8,0
    充電済: 006904,81,26488200,28880100,26765700,26765700,28212000,945600,005003,001123,9112.43,900002,0.793819,001123,0.2,0
    
    列の定義:
    - EVID: 1列目 (例: 000011)
    - StartTime: 4列目 (例: 267800)
    - EndTime: 5列目 (例: 0)
    - CSID: 12列目 (例: 空白 or 900002)
    - InitialSOC: 15列目 (例: 0.8)
    """
    vehicle_trip_path = result_dir / "vehicleTrip.txt"
    
    try:
        # まずファイルの内容を確認
        with open(vehicle_trip_path, 'r') as f:
            first_lines = [next(f) for _ in range(3)]
            logging.info(f"ファイルの先頭3行:\n{''.join(first_lines)}")

    
        # 全列を文字列として読み込む
        raw_df = pd.read_csv(
            vehicle_trip_path,
            sep=',',
            header=None,
            dtype=str,
        )
        
        # 必要な列を抽出して処理
        df = pd.DataFrame({
            'EVID': pd.to_numeric(raw_df[0].str.replace(',', ''), errors='coerce'),
            'StartTime': pd.to_numeric(raw_df[2].str.replace(',', ''), errors='coerce') / 1000,
            'EndTime': pd.to_numeric(raw_df[3].str.replace(',', ''), errors='coerce') / 1000,
            'InitialSOC': pd.to_numeric(raw_df[14].str.replace(',', ''), errors='coerce')
        })
        
        # データ型の設定
        df = df.astype({
            'EVID': 'int64',
            'StartTime': 'float64',
            'EndTime': 'float64',
            'InitialSOC': 'float64'
        })
        
        logging.info(f"車両走行データ: 全{len(raw_df)}件中{len(df)}件が条件に合致")
        logging.info(f"サンプルデータ:\n{df.head()}")
        
        return df
        
    except Exception as e:
        logging.error(f"走行データの読み込みエラー: {str(e)}")
        return pd.DataFrame(columns=['EVID', 'StartTime', 'EndTime', 'InitialSOC'])

def process_combination(worker_id: int) -> dict:
    """各組み合わせの処理"""
    paths = get_paths(worker_id)
    result_dir = Path(paths["res"])
    emates_dir = result_dir / "emates"
    
    try:
        # 時系列データの処理
        time_series_result = process_time_series(emates_dir, [])
        
        # 充電損失データの処理
        charging_loss_df = process_charging_loss(result_dir)
        
        # 走行データの処理
        vehicle_trip_df = process_vehicle_trip(result_dir)
        
        result = {
            **time_series_result,
            'charging_loss': charging_loss_df,
            'vehicle_trip': vehicle_trip_df
        }
        
        logging.info(f"組み合わせ{worker_id}個目の処理が完了")
        return result
    except Exception as e:
        logging.error(f"組み合わせ{worker_id}の処理中にエラー: {str(e)}")
        return None

def main():
    """メイン処理"""
    logging.basicConfig(level=logging.INFO)
    
    # 並列処理の設定
    num_workers = 4  # 並列数
    num_combinations = 100  # 処理する組み合わせの数
    
    results = []
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = [
            executor.submit(process_combination, i)  # pathsパラメータを削除
            for i in range(1, num_workers + 1)
        ]
        
        for future in tqdm(futures, desc="Processing combinations"):
            try:
                result = future.result()
                if result is not None:
                    results.append(result)
            except Exception as e:
                logging.error(f"処理中にエラー: {str(e)}")
    
    # 結果の保存
    output_dir = get_project_root() / 'results'
    logging.info(f"結果を保存: {output_dir}")
    output_dir.mkdir(exist_ok=True)
    
    import h5py
    with h5py.File(output_dir / 'simulation_data.h5', 'w') as f:
        for i, result in enumerate(results):
            if result is None:
                continue
                
            grp = f.create_group(f'combination_{i}')
            
            # 時系列データの保存
            for key in ['time', 'waiting', 'demand', 'utilization']:
                if isinstance(result[key], np.ndarray):
                    grp.create_dataset(key, data=result[key])
            
            # 充電損失データの保存
            if not result['charging_loss'].empty:
                charging_loss_grp = grp.create_group('charging_loss')
                for col in result['charging_loss'].columns:
                    charging_loss_grp.create_dataset(
                        col, 
                        data=result['charging_loss'][col].values
                    )
            
            # 走行データの保存
            if not result['vehicle_trip'].empty:
                vehicle_trip_grp = grp.create_group('vehicle_trip')
                for col in result['vehicle_trip'].columns:
                    vehicle_trip_grp.create_dataset(
                        col, 
                        data=result['vehicle_trip'][col].values
                    )
            
            # その他の属性の保存
            for key, value in result.items():
                if not isinstance(value, (np.ndarray, pd.DataFrame)):
                    grp.attrs[key] = value

if __name__ == "__main__":
    main()