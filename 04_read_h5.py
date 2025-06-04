import h5py
import numpy as np
import pandas as pd
from pathlib import Path

def get_project_root() -> Path:
    """プロジェクトのルートディレクトリを取得"""
    return Path(__file__).parent

def read_h5_data(file_path: str = get_project_root() / 'results/simulation_data.h5'):
    """HDF5ファイルからデータを読み込む"""
    with h5py.File(file_path, 'r') as f:
        data = {}
        # 各組み合わせのデータを読み込む
        for combination_name in f.keys():
            combination_data = {}
            group = f[combination_name]
            
            # 基本的な時系列データの読み込み
            for key in ['time', 'waiting', 'demand', 'utilization']:
                if key in group:
                    combination_data[key] = np.array(group[key])
            
            # 充電損失データの読み込み
            if 'charging_loss' in group:
                charging_loss_data = {}
                for col in group['charging_loss'].keys():
                    charging_loss_data[col] = np.array(group['charging_loss'][col])
                combination_data['charging_loss'] = pd.DataFrame(charging_loss_data)
            
            # 走行データの読み込み
            if 'vehicle_trip' in group:
                vehicle_trip_data = {}
                for col in group['vehicle_trip'].keys():
                    vehicle_trip_data[col] = np.array(group['vehicle_trip'][col])
                combination_data['vehicle_trip'] = pd.DataFrame(vehicle_trip_data)
            
            # 属性の読み込み
            for attr_name in group.attrs:
                combination_data[attr_name] = group.attrs[attr_name]
            
            data[combination_name] = combination_data
    
    return data

def convert_to_dataframe(h5_data: dict) -> dict:
    """
    HDF5データをDataFrameに変換
    """
    dataframes = {}
    
    for comb_name, comb_data in h5_data.items():
        result_dict = {}
        
        # 基本的な時系列データの作成
        time_series_df = pd.DataFrame({
            'time': comb_data['time'],
            'waiting_total': np.sum(comb_data['waiting'], axis=1),
            'demand_total': np.sum(comb_data['demand'], axis=1),
            'utilization_mean': np.mean(comb_data['utilization'], axis=1)
        })
        
        # CSごとのデータを追加
        for cs_idx in range(comb_data['waiting'].shape[1]):
            time_series_df[f'waiting_cs_{cs_idx}'] = comb_data['waiting'][:, cs_idx]
            time_series_df[f'demand_cs_{cs_idx}'] = comb_data['demand'][:, cs_idx]
            time_series_df[f'utilization_cs_{cs_idx}'] = comb_data['utilization'][:, cs_idx]
        
        # 時間を読みやすい形式に変換
        time_series_df['hour'] = time_series_df['time'] // 60
        time_series_df['minute'] = time_series_df['time'] % 60
        
        result_dict['time_series'] = time_series_df
        
        # 充電損失データを追加
        if 'charging_loss' in comb_data:
            result_dict['charging_loss'] = comb_data['charging_loss']
        
        # 走行データを追加
        if 'vehicle_trip' in comb_data:
            result_dict['vehicle_trip'] = comb_data['vehicle_trip']
        
        dataframes[comb_name] = result_dict
    
    return dataframes

# 使用例
if __name__ == "__main__":
    raw_data = read_h5_data()
    df_dict = convert_to_dataframe(raw_data)
    
    # データフレームの使用例
    for comb_name, data_dict in df_dict.items():
        print(f"\n=== {comb_name} ===")
        
        # 時系列データの基本統計量
        time_series_df = data_dict['time_series']
        print("\n時系列データの基本統計量:")
        print(time_series_df[['waiting_total', 'demand_total', 'utilization_mean']].describe())
        
        # 充電損失データの要約
        if 'charging_loss' in data_dict:
            charging_loss_df = data_dict['charging_loss']
            print("\n充電損失データの要約:")
            print(f"総レコード数: {len(charging_loss_df)}")
            print("SOCの分布:")
            print(charging_loss_df['SOC'].describe())
        
        # 走行データの要約
        if 'vehicle_trip' in data_dict:
            vehicle_trip_df = data_dict['vehicle_trip']
            print("\n走行データの要約:")
            print(f"総トリップ数: {len(vehicle_trip_df)}")
            print("初期SOCの分布:")
            print(vehicle_trip_df['InitialSOC'].describe())