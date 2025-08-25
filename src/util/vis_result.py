import os
import pandas as pd
import sys
from pathlib import Path
from tqdm import tqdm
import pickle
import numpy as np
from pathlib import Path
import matplotlib.pyplot as plt
import japanize_matplotlib
import warnings
warnings.filterwarnings('ignore')

import optuna
import optuna.visualization as vis

# 修正されたplot_waiting_times関数（軸範囲を指定可能）
def plot_waiting_times_unified(result_file, title, xlim_range, ylim_range, bins=20):
    waiting_times_minute = get_waiting_times(result_file)
    
    plt.hist(waiting_times_minute, bins=bins, range=xlim_range, 
             color='skyblue', edgecolor='black', alpha=0.7)
    
    # 95パーセンタイルの表示
    p95 = np.percentile(waiting_times_minute, 95)
    plt.axvline(p95, color='red', linestyle='dashed', linewidth=2, 
                label=f'95%tile: {p95:.1f}分')
    
    plt.title(title, fontsize=14)
    plt.xlabel('待ち時間 (分)', fontsize=12)
    plt.ylabel('台数', fontsize=12)
    plt.xlim(xlim_range)
    plt.ylim(ylim_range)
    plt.grid(axis='y', alpha=0.3)
    plt.legend()
    
    # 統計情報を表示
    mean_wait = np.mean(waiting_times_minute)
    total_wait = np.sum(waiting_times_minute)
    print(f"95%tile: {p95:.2f}分, 平均: {mean_wait:.2f}分, 総待ち時間: {total_wait:.2f}分")

def get_waiting_times(result_file)->pd.Series:
    with open(result_file, 'rb') as f:
        data = pickle.load(f)
    vehicle_trip = data['vehicle_trip']
    charging_trip = vehicle_trip[vehicle_trip['startChargingTime'] > 0]
    waiting_times_minute = (charging_trip['startChargingTime'] - charging_trip['WaitingEntryTime']) / 60  # 分単位に変換
    return waiting_times_minute

def plot_kwh_timeseries(result_file, case):
    with open(result_file, 'rb') as f:
        data = pickle.load(f)
    timeseries_kw = data['time_series_kw']
    cs_config = data['cs_config']
    timeseries_kw.index = pd.to_datetime(timeseries_kw.index, unit='s')
    # Nanの列を削除
    timeseries_kw = timeseries_kw.dropna(axis=1, how='all')
    # cs_configをDataFrameに変換
    cs_df = pd.DataFrame({
        'csids': cs_config['csids'],
        'ports': cs_config['ports'],
        'cap_kw': cs_config['cap_kw']
    })

    # ポート数が0より大きく、時系列データに存在する充電ステーションのみ抽出
    valid_cs = cs_df[(cs_df['ports'] > 0)]
    plt.figure(figsize=(12, 6))
    # 
    # 累積和を計算
    cumulative_kwh = timeseries_kw.cumsum() / 60
    plt.subplot(2, 1, 1)
    for col, port, cap in zip(cumulative_kwh.columns, valid_cs['ports'], valid_cs['cap_kw']):
        plt.plot(cumulative_kwh[col], label=f'ID{int(col)%900000}_Port{port}_{cap}kW',)
        plt.title(f'累積充電量({case})')
        plt.xlabel('Time')
    plt.ylabel('Cumulative Power (kWh)')
    plt.legend()
    plt.grid()
    plt.show()


    
def crt_cost_df(base_path):
    # 必要なインポートを事前に行う
    current_path = Path.cwd()
    sys.path.append(str(current_path.parent))
    from src.util.optimization import evaluation_total_costs, calc_initial_costs, calc_running_costs, calc_diff_trnsprt_costs

    # パラメータ設定
    DISCOUNT_RATE = 0.03
    YEAR = 5
    # base_path = '../20250808_0234'
    pkl_files = [f for f in os.listdir(base_path) if f.endswith('.pkl')]

    print(f"Processing {len(pkl_files)} files sequentially...")

    results_list = []

    # 順次処理でファイルを処理
    for i, pkl_file in enumerate(tqdm(pkl_files, desc="Processing files")):
        try:
            file_path = f'{base_path}/{pkl_file}'
            total_costs, emates_result = evaluation_total_costs(file_path)
            cs_config = emates_result['cs_config']
            timeseries_kw = emates_result['time_series_kw']
            
            initial_costs = calc_initial_costs(cs_config, timeseries_kw)
            running_costs = calc_running_costs(cs_config, timeseries_kw)
            _, transport_costs = calc_diff_trnsprt_costs(emates_result['vehicle_trip'])
            total_kwh = timeseries_kw.sum().sum() / 60

            # 年間コストの割引計算
            running_costs_discounted = sum(
                (running_costs / ((1 + DISCOUNT_RATE) ** i)) for i in range(1, YEAR + 1)
            )
            
            # ユーザーコストの割引計算
            transport_costs_discounted = sum(
                (transport_costs / ((1 + DISCOUNT_RATE) ** i)) for i in range(1, YEAR + 1)
            )
            
            results_list.append({
                'trial': pkl_file,
                'initial_cost': initial_costs,
                'operational_cost': running_costs_discounted,
                'user_cost': transport_costs_discounted,
                'total_kwh': total_kwh
            })
                
        except Exception as e:
            print(f"Error processing {pkl_file}: {e}")

    # DataFrameに変換
    results_df = pd.DataFrame(results_list)
    print(f"Successfully processed {len(results_df)} files")
    return results_df

def plot_costs(best_trial_df, case):
    # 各コストの値を取得
    initial_cost = best_trial_df['initial_cost']
    operational_cost = best_trial_df['operational_cost']
    user_cost = best_trial_df['user_cost']
    total_cost = initial_cost + operational_cost + user_cost

    # 積み上げ棒グラフで可視化
    # plt.figure(figsize=(10, 6))

    # 正の値と負の値を分けて処理
    positive_costs = []
    negative_costs = []
    labels = ['初期コスト', '運用コスト', 'ユーザーコスト']
    costs_values = [initial_cost, operational_cost, user_cost]

    for cost in costs_values:
        if cost >= 0:
            positive_costs.append(cost)
            negative_costs.append(0)
        else:
            positive_costs.append(0)
            negative_costs.append(cost)

    # 積み上げ棒グラフを作成
    width = 0.6
    x = [0]  # 一つの棒グラフ

    # 正の値の積み上げ
    bottom_pos = 0
    colors_pos = ['skyblue', 'orange', 'green']
    for i, (cost, label) in enumerate(zip(positive_costs, labels)):
        if cost > 0:
            plt.bar(x, cost, bottom=bottom_pos, width=width, label=label, 
                    color=colors_pos[i], alpha=0.7)
            # 値をバーの中央に表示
            plt.text(0, bottom_pos + cost/2, f'{cost:.0f}', 
                    ha='center', va='center', fontweight='bold')
            bottom_pos += cost

    # 負の値の積み上げ
    bottom_neg = 0
    for i, (cost, label) in enumerate(zip(negative_costs, labels)):
        if cost < 0:
            plt.bar(x, cost, bottom=bottom_neg, width=width, label=label, 
                    color=colors_pos[i], alpha=0.7)
            # 値をバーの中央に表示
            plt.text(0, bottom_neg + cost/2, f'{cost:.0f}', 
                    ha='center', va='center', fontweight='bold')
            bottom_neg += cost

    # 総コストを示す線
    plt.axhline(y=total_cost, color='red', linestyle='--', linewidth=2, 
                label=f'総コスト: {total_cost:.0f}万円')
    plt.text(0.3, total_cost, f'総コスト\n{total_cost:.0f}万円', 
            va='center', ha='left', fontweight='bold', color='red')

    plt.title(f'コスト内訳({case})', fontsize=14)
    plt.ylabel('コスト (万円)', fontsize=12)
    plt.axhline(y=0, color='black', linestyle='-', alpha=0.3)
    plt.xlim(-0.5, 0.5)
    plt.xticks([0], ['Best Trial'])
    plt.legend(loc='upper right')
    plt.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    # plt.show()
    
def plot_optimization_history(STUDY_NAME, db_path):
    # STUDY_NAME = "cs_optimization"
    STORAGE_URL = f"sqlite:///{db_path}"

    # データベースからStudyオブジェクトを読み込む
    study = optuna.load_study(study_name=STUDY_NAME, storage=STORAGE_URL)

    # --- ベストパラメータの表示 ---
    print("--- Best Trial ---")
    trial = study.best_trial
    print(f"  Trial number: {trial.number}")
    print(f"  Value (最小値): {trial.value}")

    # --- 最適化推移の可視化 ---
    # グラフを生成
    fig = vis.plot_optimization_history(study)

    # グラフを表示 (Jupyter NotebookやGoogle Colabなどではこれだけで表示されます)
    fig.show()
    
def plot_network_structure(result_path:Path, title= '充電ステーション候補地'):
    # データの読み込み
    map_path = r'\\wsl.localhost\Ubuntu-22.04\home\tsato-cnlab\Emates\eMATES_2308\network\simple_shikata\mapPosition.txt'
    map_df = pd.read_csv(map_path, sep=',', header=None, names=['ID', 'X', 'Y', 'Z'])

    network_path = r'\\wsl.localhost\Ubuntu-22.04\home\tsato-cnlab\Emates\eMATES_2308\network\simple_shikata\network.txt'
    network_df = pd.read_csv(network_path, sep=',', header=None, names=['from', 'link', 'to_1', 'to_2', 'to_3', 'to_4'])
    
    cslist_path = r'\\wsl.localhost\Ubuntu-22.04\home\tsato-cnlab\Emates\eMATES_2308\network\simple_shikata\csList.txt'
    cslist_df = pd.read_csv(cslist_path, sep=',', header=None, names=['ID', 'port', 'kw'])
    
    # ネットワーク図の可視化
    # plt.figure(figsize=(15, 12))

    # ノードの描画
    plt.scatter(map_df['X'], map_df['Y'], c='lightblue', s=10, alpha=0.5, label='ノード')

    # リンクの描画
    for _, row in network_df.iterrows():
        from_node = map_df[map_df['ID'] == row['from']]
        
        # to_1からto_4までの接続先を描画
        for to_col in ['to_1', 'to_2', 'to_3', 'to_4']:
            if pd.notna(row[to_col]) and row[to_col] != 0:
                to_node = map_df[map_df['ID'] == row[to_col]]
                
                if not from_node.empty and not to_node.empty:
                    plt.plot([from_node['X'].iloc[0], to_node['X'].iloc[0]], 
                            [from_node['Y'].iloc[0], to_node['Y'].iloc[0]], 
                            'gray', alpha=0.3, linewidth=0.3)

    # 充電ステーション候補地を表示
    csids = cslist_df['ID']
    charging_stations = map_df[map_df['ID'].isin(csids)]
    plt.scatter(charging_stations['X'], charging_stations['Y'], c='gray', 
               s=100, label='充電ステーション候補地')
    
    def _plot_charging_stations(result_path, title, map_df):
    # 充電ステーションの実際の配置を表示（Optunaで採用された配置）
    
        if result_path:
            with open(result_path, 'rb') as f:
                data = pickle.load(f)
            cs_config = data['cs_config']
            
            # 充電ステーション設定データフレーム作成
            cs_df = pd.DataFrame({
                'csids': cs_config['csids'],
                'ports': cs_config['ports'],
                'cap_kw': cs_config['cap_kw']
            })
            
            # ポート数が0より大きい充電ステーションのみを表示
            setting_cs = cs_df[cs_df['ports'] > 0]
            
            if len(setting_cs) > 0:
                # 座標情報をマージ
                setting_cs_with_pos = pd.merge(setting_cs, map_df, 
                                            left_on='csids', right_on='ID', how='inner')
                
                # カラーマップの設定（充電出力用）
                from matplotlib import cm
                colors = setting_cs_with_pos['cap_kw']
                sizes = setting_cs_with_pos['ports'] * 400  # ポート数をサイズに変換（100倍で見やすく）

                # 離散値でのカラーマッピング
                unique_kw = sorted(setting_cs_with_pos['cap_kw'].unique())
                colors_discrete = plt.cm.viridis(np.linspace(0, 1, len(unique_kw)))
                color_map = {kw: colors_discrete[i] for i, kw in enumerate(unique_kw)}
                colors = [color_map[kw] for kw in setting_cs_with_pos['cap_kw']]
                
                # 散布図の作成（離散色で）
                scatter = plt.scatter(setting_cs_with_pos['X'], setting_cs_with_pos['Y'], 
                                    c=colors, s=sizes, alpha=1.0, 
                                    edgecolors='black', linewidths=1, label='設置充電ステーション')
                
                # 離散カラーバーの作成
                import matplotlib.patches as mpatches
                legend_elements = [mpatches.Patch(color=color_map[kw], label=f'{kw}kW') 
                                for kw in unique_kw]
                plt.legend(handles=legend_elements, loc='upper left', title='充電出力')
                
                # 充電ステーション情報を表示
                for _, row in setting_cs_with_pos.iterrows():
                    plt.annotate(f'ID:{int(row["csids"]) % 900000}\n{int(row["ports"])}口\n{int(row["cap_kw"])}kW', 
                            (row['X'], row['Y']), 
                            xytext=(5, 5), textcoords='offset points',
                            fontsize=10, ha='left', va='bottom',
                            bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.8))

        plt.title(title, fontsize=16)
        plt.xlabel('X座標', fontsize=12)
        plt.ylabel('Y座標', fontsize=12)
        plt.grid(True, alpha=0.3)
        plt.legend(loc='upper right')
        
        plt.axis('equal')
        plt.tight_layout()
        plt.show()

    _plot_charging_stations(result_path, title, map_df)
    
def get_total_kw(result_path):
    if result_path:
        with open(result_path, 'rb') as f:
            data = pickle.load(f)
        time_series_kw = data['time_series_kw']
        total_kw = time_series_kw.sum().sum() /60
        return total_kw
    return 0

def get_initial_cost(result_path):
    if result_path:
        with open(result_path, 'rb') as f:
            data = pickle.load(f)
        cs_config = data['cs_config']
        time_series_kw = data['time_series_kw']
        initial_cost = calc_initial_costs(cs_config, time_series_kw)
        return initial_cost
    return 0

def aggregate_results(result_file):
    initial_cost = get_initial_cost(result_file)
    waiting_times = get_waiting_times(result_file)
    total_waiting_times = sum(waiting_times)
    waiting_times_95 = np.percentile(waiting_times, 95)
    demand = get_total_kw(result_file)
    with open(result_file, 'rb') as f:
        data = pickle.load(f)
        vehicle_trip = data['vehicle_trip']
    total_trip_time_normal, _ = calc_diff_trnsprt_costs(vehicle_trip=vehicle_trip)
    return {
        "InitialCost": initial_cost,
        "TotalDemand": demand,
        "WaitingTimes": total_waiting_times,
        "95percentileWait": waiting_times_95,
        "TotalTripTime": total_trip_time_normal
    }
    
