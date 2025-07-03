import pandas as pd
import numpy as np
import os
import json
import logging
import datetime
import h5py
from pathlib import Path
import re
from typing import Dict, List, Any, Optional, Union
from src.util.path_manager import get_paths

# ログ設定
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

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
            try:
                logger.info(f"Worker {worker_id} のデータを収集中...")
                data = load_worker_data(worker_id)
                all_results.append(data)
                logger.info(f"Worker {worker_id} のデータ収集完了")
            except Exception as e:
                logger.error(f"Worker {worker_id} のデータ収集エラー: {e}")
        else:
            # 連番で存在しないworker_idが出たら終了（途中欠番がなければ）
            if len(all_results) > 0:
                break
    
    logger.info(f"合計 {len(all_results)} 個のワーカーデータを収集しました")
    return all_results

def preprocess_time_series(all_results):
    """
    時系列データを前処理して統合
    MATLABのtime_series_data形式に相当するデータ構造を作成
    """
    time_series_data = {}
    
    for i, result in enumerate(all_results):
        # TデータからCSIDsリストを取得
        if not result['T'].empty:
            # ユニークなCSIDを抽出
            cs_ids = result['T']['id'].unique()
            cs_ids = cs_ids[~np.isnan(cs_ids)]  # NaN値を除外
            
            # 時間間隔を取得（1分単位に統一）
            time_values = np.sort(result['T']['ElapsedTime'].unique())
            
            # 充電ステーション数
            n_stations = len(cs_ids)
            
            # 時間系列長
            time_length = len(time_values)
            
            # 初期化
            utilization = np.zeros((time_length, n_stations))
            waiting = np.zeros((time_length, n_stations))
            demand = np.zeros((time_length, n_stations))
            
            # 各時間・各ステーションの値を計算
            for t_idx, t in enumerate(time_values):
                t_data = result['T'][result['T']['ElapsedTime'] == t]
                
                for cs_idx, cs_id in enumerate(cs_ids):
                    # この時刻・このCSのデータ
                    cs_data = t_data[t_data['id'] == cs_id]
                    
                    if not cs_data.empty:
                        # 利用率: 使用中充電口/全充電口
                        if 'port' in cs_data.columns and 'maxport' in cs_data.columns:
                            max_port = cs_data['maxport'].iloc[0]
                            used_port = cs_data['port'].iloc[0]
                            if max_port > 0:
                                utilization[t_idx, cs_idx] = used_port / max_port
                        
                        # 待ち台数
                        if 'queue' in cs_data.columns:
                            waiting[t_idx, cs_idx] = cs_data['queue'].iloc[0]
                        
                        # 充電需要 (kW)
                        if 'power' in cs_data.columns:
                            demand[t_idx, cs_idx] = cs_data['power'].iloc[0]
            
            # 時系列データを辞書に保存
            time_series_data[i] = {
                'time': time_values,
                'utilization': utilization,
                'waiting': waiting,
                'demand': demand,
                'csids': cs_ids
            }
    
    logger.info(f"時系列データの前処理完了: {len(time_series_data)}件")
    return time_series_data

def process_charging_loss(all_results, time_series_data):
    """
    充電ロスデータを処理
    """
    for i, result in enumerate(all_results):
        if i in time_series_data and not result['chargingLoss'].empty:
            # 充電ロスデータを時系列データに追加
            charging_loss = result['chargingLoss'].copy()
            time_series_data[i]['charging_loss'] = charging_loss
    
    return time_series_data

def process_vehicle_trips(all_results, time_series_data):
    """
    車両トリップデータを処理
    """
    for i, result in enumerate(all_results):
        if i in time_series_data and not result['vehicleTrip'].empty:
            # 車両トリップデータを時系列データに追加
            vehicle_trip = result['vehicleTrip'].copy()
            time_series_data[i]['vehicle_trip'] = vehicle_trip
    
    return time_series_data

def save_processed_data(time_series_data, output_dir="processed_data", version="Ver1"):
    """
    処理済みデータを保存
    
    MATLABとの互換性のためにHDF5形式で保存
    """
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True, parents=True)
    
    # バージョンディレクトリ
    version_dir = output_path / version
    version_dir.mkdir(exist_ok=True)
    
    # タイムスタンプ
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 保存ファイル名
    filename = f"time_series_data_{version}_{timestamp}.h5"
    filepath = version_dir / filename
    
    # HDF5ファイルとして保存
    with h5py.File(filepath, 'w') as f:
        # メタデータ
        f.attrs['version'] = version
        f.attrs['created'] = timestamp
        f.attrs['n_combinations'] = len(time_series_data)
        
        # 各配置パターンのデータを保存
        for comb_id, data in time_series_data.items():
            # 配置パターンのグループ
            comb_group = f.create_group(f"combination_{comb_id}")
            
            # データを保存
            for key, value in data.items():
                if isinstance(value, np.ndarray):
                    comb_group.create_dataset(key, data=value)
                elif isinstance(value, pd.DataFrame):
                    # DataFrameをグループとして保存
                    df_group = comb_group.create_group(key)
                    for col in value.columns:
                        df_group.create_dataset(col, data=value[col].values)
                    # 列名を属性として保存
                    df_group.attrs['columns'] = list(value.columns)
                    df_group.attrs['shape'] = value.shape
                else:
                    # スカラー値や他のオブジェクト
                    try:
                        comb_group.attrs[key] = value
                    except Exception:
                        logger.warning(f"キー {key} のデータは保存できませんでした")
    
    logger.info(f"処理済みデータを保存しました: {filepath}")
    return filepath

def create_metadata_file(input_config, time_series_data, output_path):
    """
    メタデータファイルを作成
    """
    metadata = {
        "creation_timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "input_config": input_config,
        "data_summary": {
            "n_combinations": len(time_series_data),
            "combinations": {}
        }
    }
    
    # 各組み合わせのサマリーを追加
    for comb_id, data in time_series_data.items():
        comb_summary = {
            "time_length": len(data['time']) if 'time' in data else 0,
            "n_stations": data['utilization'].shape[1] if 'utilization' in data else 0
        }
        
        # CSIDsがあれば追加
        if 'csids' in data:
            comb_summary["csids"] = data['csids'].tolist() if isinstance(data['csids'], np.ndarray) else data['csids']
        
        metadata["data_summary"]["combinations"][str(comb_id)] = comb_summary
    
    # JSONファイルとして保存
    with open(output_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    logger.info(f"メタデータを保存しました: {output_path}")
    return metadata

def load_processed_data(filepath):
    """
    処理済みデータを読み込む
    """
    if not os.path.exists(filepath):
        logger.error(f"ファイル {filepath} が見つかりません")
        return None
    
    try:
        data = {}
        with h5py.File(filepath, 'r') as f:
            # メタデータを取得
            version = f.attrs.get('version')
            created = f.attrs.get('created')
            
            logger.info(f"データ読み込み: バージョン={version}, 作成日時={created}")
            
            # 各配置パターンのデータを読み込み
            for comb_name in f.keys():
                comb_id = int(comb_name.split('_')[-1])
                comb_group = f[comb_name]
                
                # データ辞書を初期化
                data[comb_id] = {}
                
                # グループ内のデータセットとアトリビュートを読み込み
                for key in comb_group.keys():
                    if isinstance(comb_group[key], h5py.Group):
                        # DataFrameを再構築
                        df_group = comb_group[key]
                        columns = list(df_group.attrs['columns'])
                        df_dict = {col: df_group[col][()] for col in df_group.keys()}
                        data[comb_id][key] = pd.DataFrame(df_dict)
                    else:
                        # 通常のデータセット
                        data[comb_id][key] = comb_group[key][()]
                
                # 属性を読み込み
                for key, value in comb_group.attrs.items():
                    data[comb_id][key] = value
        
        logger.info(f"データ読み込み完了: {len(data)}件の配置パターン")
        return data
    
    except Exception as e:
        logger.error(f"データ読み込みエラー: {e}")
        return None

def main():
    """
    メイン処理
    """
    # 設定
    output_dir = "processed_data"
    version = "Ver1"
    
    # 1. シミュレーション結果の収集
    logger.info("ステップ1: シミュレーション結果の収集")
    all_results = collect_all_results()
    
    if not all_results:
        logger.error("シミュレーション結果が見つかりませんでした")
        return
    
    # 2. 時系列データの前処理
    logger.info("ステップ2: 時系列データの前処理")
    time_series_data = preprocess_time_series(all_results)
    
    # 3. 充電ロスデータの処理
    logger.info("ステップ3: 充電ロスデータの処理")
    time_series_data = process_charging_loss(all_results, time_series_data)
    
    # 4. 車両トリップデータの処理
    logger.info("ステップ4: 車両トリップデータの処理")
    time_series_data = process_vehicle_trips(all_results, time_series_data)
    
    # 5. 処理済みデータの保存
    logger.info("ステップ5: 処理済みデータの保存")
    h5_filepath = save_processed_data(time_series_data, output_dir, version)
    
    # 6. メタデータの作成
    logger.info("ステップ6: メタデータの作成")
    metadata_path = Path(output_dir) / version / "metadata.json"
    create_metadata_file({}, time_series_data, metadata_path)
    
    # 7. データのロード確認（テスト）
    logger.info("ステップ7: データのロード確認")
    loaded_data = load_processed_data(h5_filepath)
    
    if loaded_data:
        logger.info("データ処理パイプラインが正常に完了しました")
    else:
        logger.error("データ処理に問題が発生しました")

if __name__ == "__main__":
    main()
