import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import japanize_matplotlib

def logistic_curve(t, K, r, t0):
    """ロジスティック曲線の定義"""
    
    return K / (1 + np.exp(-r * (t - t0)))

def logistic_curve_with_offset(t, K, r, t0, initial_rate=1):
    """
    初期普及率を考慮したロジスティック曲線
    t: 時間（年）
    K: 最大普及率（キャリングキャパシティ）
    r: 成長率パラメータ
    t0: 変曲点（普及率がK/2になる時点）
    initial_rate: 初年度の普及率
    """
    # 標準ロジスティック曲線
    logistic = K / (1 + np.exp(-r * (t - t0)))
    
    # 初年度の値を取得して調整
    initial_logistic = K / (1 + np.exp(-r * (0 - t0)))
    
    # オフセットを計算して初年度を指定値に調整
    offset = initial_rate - initial_logistic
    
    return logistic + offset

def get_adoption_data(start_year=0, end_year=10) -> pd.DataFrame:
    """EV普及率データを取得"""
    years = np.arange(start_year, end_year + 1)
    #（技術革新+政府推進）シナリオ, 成長率・最大値ともに高い
    adopt_scenario_1 = logistic_curve_with_offset(years, K=50, r=1.0, t0=4)
    #（技術革新+政府なし）シナリオ, 成長率は低いが，最大値が高い
    adopt_scenario_2 = logistic_curve_with_offset(years, K=35, r=0.5, t0=6)
    #（技術革新なし+政府推進）シナリオ, 成長率高いが，最大値は低い
    adopt_scenario_3 = logistic_curve_with_offset(years, K=25, r=0.7, t0=4)
    #（技術革新なし+政府なし）シナリオ, 成長率も低く，最大値も低い
    adopt_scenario_4 = logistic_curve_with_offset(years, K=15, r=0.3, t0=7)

    # 統合されたDataFrameを作成
    adoption_all = pd.DataFrame({
        'Year': years,
        'シナリオ1_急速（技術革新+政府推進）': adopt_scenario_1,
        'シナリオ2_緩慢（技術革新+政府なし）': adopt_scenario_2,
        'シナリオ3_急速（技術革新なし+政府推進）': adopt_scenario_3,
        'シナリオ4_緩慢（技術革新なし+政府なし）': adopt_scenario_4
    })
    return adoption_all

def get_adoption_rate(scenario_id: int, year: int) -> float:
    """特定シナリオの特定年の普及率を取得"""
    # シナリオパラメータ
    params = {
        1: {'K': 50, 'r': 1.0, 't0': 4},
        2: {'K': 35, 'r': 0.5, 't0': 6},
        3: {'K': 25, 'r': 0.7, 't0': 4},
        4: {'K': 15, 'r': 0.3, 't0': 7}
    }
    
    if scenario_id not in params:
        raise ValueError(f"シナリオ {scenario_id} は存在しません")
    
    p = params[scenario_id]
    return logistic_curve_with_offset(year, p['K'], p['r'], p['t0'])

if __name__ == "__main__":
    # データ取得
    print(get_adoption_rate(1, 5))  # シナリオ1の5年目の普及率を取得
    adoption_data = get_adoption_data()
    
    # グラフの描画
    plt.figure(figsize=(10, 6))
    for column in adoption_data.columns[1:]:
        plt.plot(adoption_data['Year'], adoption_data[column], label=column)

    plt.title('EV普及率のシナリオ分析')
    plt.xlabel('年')
    plt.ylabel('普及率 (%)')
    plt.xticks(adoption_data['Year'], rotation=45)
    plt.legend()
    plt.grid()
    plt.tight_layout()
    plt.show()