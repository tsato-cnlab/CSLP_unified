import h5py
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from typing import Dict

def plot_time_series(data: Dict, save_dir: Path):
    """時系列データのプロット"""
    save_dir.mkdir(exist_ok=True)
    
    # フォントの設定
    plt.rcParams['font.family'] = 'MS Gothic'
    
    # 1. 充電需要の時系列プロット
    plt.figure(figsize=(12, 6))
    plt.plot(data['time'] / 60, np.sum(data['demand'], axis=1))
    plt.title('充電需要の時間変化')
    plt.xlabel('経過時間 (時間)')
    plt.ylabel('充電需要 (kW)')
    plt.grid(True)
    plt.savefig(save_dir / 'demand_timeseries.png')
    plt.close()
    
    # 2. CS別の利用率ヒートマップ
    plt.figure(figsize=(15, 8))
    sns.heatmap(data['utilization'].T, 
                cmap='YlOrRd',
                xticklabels=data['time'][::60] // 60,  # 1時間ごと
                yticklabels=[f'CS{i+1}' for i in range(data['utilization'].shape[1])],
                cbar_kws={'label': '利用率'})
    plt.title('充電ステーション利用率の時間変化')
    plt.xlabel('経過時間 (時間)')
    plt.ylabel('充電ステーション')
    plt.tight_layout()
    plt.savefig(save_dir / 'utilization_heatmap.png')
    plt.close()
    
    # 3. 待ち台数の箱ひげ図
    plt.figure(figsize=(10, 6))
    box_data = [data['waiting'][:, i] for i in range(data['waiting'].shape[1])]
    plt.boxplot(box_data, labels=[f'CS{i+1}' for i in range(len(box_data))])
    plt.title('CS別待ち台数の分布')
    plt.xlabel('充電ステーション')
    plt.ylabel('待ち台数')
    plt.grid(True)
    plt.savefig(save_dir / 'waiting_boxplot.png')
    plt.close()

def main():
    """メイン処理"""
    # HDF5ファイルからデータを読み込み
    with h5py.File('results/time_series_data.h5', 'r') as f:
        for combination_name in f.keys():
            # 各組み合わせのデータを読み込み
            data = {}
            group = f[combination_name]
            
            # データセットの読み込み
            for key in group.keys():
                data[key] = np.array(group[key])
            
            # 属性の読み込み
            for attr_name in group.attrs:
                data[attr_name] = group.attrs[attr_name]
            
            # プロットの保存先
            plot_dir = Path('results') /  combination_name
            plot_time_series(data, plot_dir)
            print(f'{combination_name}のプロットを保存しました')

if __name__ == "__main__":
    main()