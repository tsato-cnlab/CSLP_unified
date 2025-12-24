#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
eMATES結果読み込みと分析ユーティリティ
"""

import h5py
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from typing import Dict, List, Optional
import japanize_matplotlib

class EMATESAnalyzer:
    """eMATES結果の分析クラス"""
    
    def __init__(self, h5_file_path: str):
        self.h5_file_path = Path(h5_file_path)
        self.data = None
        self.summary = None
        
    def load_data(self) -> Dict:
        """HDF5ファイルからデータを読み込み"""
        if not self.h5_file_path.exists():
            raise FileNotFoundError(f"ファイルが見つかりません: {self.h5_file_path}")
        
        with pd.HDFStore(str(self.h5_file_path), mode='r') as store:
            # 評価サマリーを読み込み
            if '/evaluation_summary' in store:
                self.summary = store['evaluation_summary']
            
            # 個別ワーカーデータを読み込み
            data = {}
            for key in store.keys():
                if key.startswith('/worker_'):
                    worker_name = key.split('/')[1]
                    if worker_name not in data:
                        data[worker_name] = {}
                    
                    data_type = key.split('/')[-1]
                    data[worker_name][data_type] = store[key]
            
            self.data = data
        
        print(f"データ読み込み完了: {len(self.data)} ワーカー")
        return self.data
    
    def get_summary_statistics(self) -> pd.DataFrame:
        """サマリー統計を取得"""
        if self.summary is None:
            self.load_data()
        
        if self.summary is not None:
            stats = self.summary.describe()
            print("=== 評価統計 ===")
            print(stats)
            return stats
        else:
            print("サマリーデータが見つかりません")
            return pd.DataFrame()
    
    def get_top_configurations(self, n: int = 10) -> pd.DataFrame:
        """上位n個の配置を取得"""
        if self.summary is None:
            self.load_data()
        
        if self.summary is not None:
            top_configs = self.summary.nlargest(n, 'overall_score')
            print(f"=== 上位{n}配置 ===")
            for i, (_, row) in enumerate(top_configs.iterrows(), 1):
                print(f"{i:2d}. Worker {row['worker_id']:2d}: "
                      f"スコア {row['overall_score']:6.1f} | "
                      f"CS数 {row['total_cs_count']:2d} | "
                      f"利用率 {row['avg_utilization']:5.1%}")
            return top_configs
        else:
            return pd.DataFrame()
    
    def analyze_cs_configuration(self, worker_id: int) -> Dict:
        """特定の配置の詳細分析"""
        if self.data is None:
            self.load_data()
        
        worker_key = f"worker_{worker_id}"
        if worker_key not in self.data:
            print(f"Worker {worker_id} のデータが見つかりません")
            return {}
        
        worker_data = self.data[worker_key]
        analysis = {}
        
        # 時系列分析
        if 'timeseries' in worker_data:
            ts_data = worker_data['timeseries']
            
            if 'ElapsedTime' in ts_data.columns:
                time_analysis = {
                    'duration': ts_data['ElapsedTime'].max(),
                    'time_points': len(ts_data['ElapsedTime'].unique())
                }
                
                if 'waitingLine' in ts_data.columns:
                    time_analysis.update({
                        'avg_waiting': ts_data['waitingLine'].mean(),
                        'max_waiting': ts_data['waitingLine'].max(),
                        'waiting_over_time': ts_data.groupby('ElapsedTime')['waitingLine'].sum().to_dict()
                    })
                
                if 'Csid' in ts_data.columns:
                    cs_usage = ts_data['Csid'].value_counts().to_dict()
                    time_analysis['cs_usage_distribution'] = cs_usage
                
                analysis['time_series'] = time_analysis
        
        # 充電損失分析
        if 'charging_loss' in worker_data:
            loss_data = worker_data['charging_loss']
            if not loss_data.empty:
                loss_analysis = {
                    'total_losses': len(loss_data),
                    'avg_soc_at_loss': loss_data['SOC'].mean() if 'SOC' in loss_data.columns else 0,
                    'loss_by_time': loss_data.groupby('Time').size().to_dict() if 'Time' in loss_data.columns else {}
                }
                analysis['charging_loss'] = loss_analysis
        
        # 走行データ分析
        if 'vehicle_trip' in worker_data:
            trip_data = worker_data['vehicle_trip']
            if not trip_data.empty:
                trip_analysis = {
                    'total_trips': len(trip_data),
                    'avg_initial_soc': trip_data['InitialSOC'].mean() if 'InitialSOC' in trip_data.columns else 0
                }
                
                if 'CSID' in trip_data.columns:
                    charging_trips = trip_data[trip_data['CSID'].notna()]
                    trip_analysis['charging_trip_ratio'] = len(charging_trips) / len(trip_data)
                
                analysis['vehicle_trip'] = trip_analysis
        
        print(f"=== Worker {worker_id} 詳細分析 ===")
        for category, data in analysis.items():
            print(f"\n{category}:")
            for key, value in data.items():
                if isinstance(value, dict) and len(value) > 5:
                    print(f"  {key}: {len(value)} 項目")
                else:
                    print(f"  {key}: {value}")
        
        return analysis
    
    def plot_performance_comparison(self, figsize: tuple = (15, 10)) -> None:
        """性能比較グラフを作成"""
        if self.summary is None:
            self.load_data()
        
        if self.summary is None or self.summary.empty:
            print("プロット用データがありません")
            return
        
        fig, axes = plt.subplots(2, 3, figsize=figsize)
        
        # 1. 総合スコア分布
        axes[0, 0].hist(self.summary['overall_score'], bins=20, alpha=0.7, color='skyblue')
        axes[0, 0].set_title('総合スコア分布')
        axes[0, 0].set_xlabel('スコア')
        axes[0, 0].set_ylabel('頻度')
        
        # 2. CS数 vs スコア
        axes[0, 1].scatter(self.summary['total_cs_count'], self.summary['overall_score'], alpha=0.6)
        axes[0, 1].set_title('CS数 vs 総合スコア')
        axes[0, 1].set_xlabel('CS数')
        axes[0, 1].set_ylabel('総合スコア')
        
        # 3. 利用率 vs スコア
        axes[0, 2].scatter(self.summary['avg_utilization'], self.summary['overall_score'], alpha=0.6, color='green')
        axes[0, 2].set_title('利用率 vs 総合スコア')
        axes[0, 2].set_xlabel('平均利用率')
        axes[0, 2].set_ylabel('総合スコア')
        
        # 4. 待ち時間分布
        axes[1, 0].hist(self.summary['avg_waiting'], bins=20, alpha=0.7, color='orange')
        axes[1, 0].set_title('平均待ち時間分布')
        axes[1, 0].set_xlabel('平均待ち時間')
        axes[1, 0].set_ylabel('頻度')
        
        # 5. 充電損失分布
        axes[1, 1].hist(self.summary['total_charging_loss'], bins=20, alpha=0.7, color='red')
        axes[1, 1].set_title('充電損失分布')
        axes[1, 1].set_xlabel('総充電損失')
        axes[1, 1].set_ylabel('頻度')
        
        # 6. 効率性マトリックス（利用率 vs 待ち時間）
        scatter = axes[1, 2].scatter(self.summary['avg_utilization'], self.summary['avg_waiting'], 
                                   c=self.summary['overall_score'], cmap='RdYlBu_r', alpha=0.7)
        axes[1, 2].set_title('効率性マトリックス')
        axes[1, 2].set_xlabel('平均利用率')
        axes[1, 2].set_ylabel('平均待ち時間')
        plt.colorbar(scatter, ax=axes[1, 2], label='総合スコア')
        
        plt.tight_layout()
        plt.show()
    
    def plot_time_series(self, worker_id: int, figsize: tuple = (12, 8)) -> None:
        """特定配置の時系列プロット"""
        if self.data is None:
            self.load_data()
        
        worker_key = f"worker_{worker_id}"
        if worker_key not in self.data or 'timeseries' not in self.data[worker_key]:
            print(f"Worker {worker_id} の時系列データが見つかりません")
            return
        
        ts_data = self.data[worker_key]['timeseries']
        
        if 'ElapsedTime' not in ts_data.columns:
            print("時系列データに時間情報がありません")
            return
        
        fig, axes = plt.subplots(2, 2, figsize=figsize)
        
        # 時間別待ち台数
        if 'waitingLine' in ts_data.columns:
            waiting_by_time = ts_data.groupby('ElapsedTime')['waitingLine'].sum()
            axes[0, 0].plot(waiting_by_time.index, waiting_by_time.values)
            axes[0, 0].set_title(f'Worker {worker_id}: 時間別総待ち台数')
            axes[0, 0].set_xlabel('経過時間')
            axes[0, 0].set_ylabel('待ち台数')
        
        # CS別利用状況
        if 'Csid' in ts_data.columns:
            cs_usage = ts_data['Csid'].value_counts()
            axes[0, 1].bar(range(len(cs_usage)), cs_usage.values)
            axes[0, 1].set_title(f'Worker {worker_id}: CS別利用回数')
            axes[0, 1].set_xlabel('CS ID')
            axes[0, 1].set_ylabel('利用回数')
        
        # 時間別容量利用
        if 'Cap_kW' in ts_data.columns:
            capacity_by_time = ts_data.groupby('ElapsedTime')['Cap_kW'].sum()
            axes[1, 0].plot(capacity_by_time.index, capacity_by_time.values, color='green')
            axes[1, 0].set_title(f'Worker {worker_id}: 時間別総容量')
            axes[1, 0].set_xlabel('経過時間')
            axes[1, 0].set_ylabel('容量 (kW)')
        
        # 利用率推移
        if 'waitingLine' in ts_data.columns and 'Cap_kW' in ts_data.columns:
            waiting_by_time = ts_data.groupby('ElapsedTime')['waitingLine'].sum()
            capacity_by_time = ts_data.groupby('ElapsedTime')['Cap_kW'].sum()
            utilization = waiting_by_time / capacity_by_time.replace(0, 1)
            axes[1, 1].plot(utilization.index, utilization.values, color='purple')
            axes[1, 1].set_title(f'Worker {worker_id}: 利用率推移')
            axes[1, 1].set_xlabel('経過時間')
            axes[1, 1].set_ylabel('利用率')
        
        plt.tight_layout()
        plt.show()

def main():
    """使用例"""
    # アナライザーの初期化
    analyzer = EMATESAnalyzer('emates_results.h5')
    
    # データ読み込み
    data = analyzer.load_data()
    
    # 統計情報表示
    stats = analyzer.get_summary_statistics()
    
    # 上位配置表示
    top_configs = analyzer.get_top_configurations(5)
    
    # 性能比較グラフ
    analyzer.plot_performance_comparison()
    
    # 上位配置の詳細分析
    if not top_configs.empty:
        best_worker_id = int(top_configs.iloc[0]['worker_id'])
        analysis = analyzer.analyze_cs_configuration(best_worker_id)
        analyzer.plot_time_series(best_worker_id)

if __name__ == "__main__":
    main()
