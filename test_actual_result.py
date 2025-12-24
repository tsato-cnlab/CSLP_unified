#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""実際のシミュレーション結果を使ったコスト計算テスト

実際のeMATESシミュレーション結果（pickle）を読み込んで
各コスト項目を計算・検証する
"""

import pickle
import sys
from pathlib import Path

from src.util.cost_calculator import (
    calc_initial_costs,
    calc_running_costs,
    calc_diff_trnsprt_costs,
    evaluation_total_costs,
    calculate_95percentile_wait_time,
    YEAR,
    DISCOUNT_RATE,
    CHARGER_COST,
    SUBSTATION_COST_PER_KW,
    INSTALLATION_COST,
    MAINTENANCE_COST_PER_YEAR,
    CONTRACT_COST_PER_KW_MONTH,
    USAGE_COST_PER_KWH,
    CHARGING_PRICE_PER_KWH,
    TIME_VALUE_OF_MONEY,
    BASELINE_TRIP_TIME,
)


def test_actual_simulation_result(result_file: str):
    """実際のシミュレーション結果でコスト計算をテスト"""

    result_path = Path(result_file)

    if not result_path.exists():
        print(f"❌ ファイルが見つかりません: {result_file}")
        return

    print("="*80)
    print(f"【実際のシミュレーション結果でのコスト計算テスト】")
    print("="*80)
    print(f"📁 ファイル: {result_file}")
    print(f"📏 ファイルサイズ: {result_path.stat().st_size / 1024:.1f} KB")

    # pickleファイルを読み込み
    try:
        with open(result_file, 'rb') as f:
            emates_result = pickle.load(f)
        print("✅ pickleファイル読み込み成功")
    except Exception as e:
        print(f"❌ pickleファイル読み込みエラー: {e}")
        return

    # データ構造を確認
    print("\n" + "="*80)
    print("【データ構造確認】")
    print("="*80)

    print(f"結果オブジェクトの型: {type(emates_result)}")

    # 辞書型の場合はキーを表示
    if isinstance(emates_result, dict):
        print(f"\n利用可能なキー:")
        for key in emates_result.keys():
            print(f"  - {key}")
    # 属性一覧
    elif hasattr(emates_result, '__dict__'):
        print(f"\n利用可能な属性:")
        for attr in dir(emates_result):
            if not attr.startswith('_'):
                print(f"  - {attr}")

    # CS設定
    try:
        # 辞書型とオブジェクト型の両方に対応
        if isinstance(emates_result, dict):
            cs_config = emates_result.get('cs_config')
        else:
            cs_config = emates_result.cs_config
        print(f"\n📊 CS設定:")
        print(f"  CSIDリスト: {cs_config.get('csids', [])}")
        print(f"  ポート数: {cs_config.get('ports', [])}")
        print(f"  容量 (kW): {cs_config.get('cap_kw', [])}")

        # 有効なCSのみ抽出
        active_cs = [(csid, port, cap)
                     for csid, port, cap in zip(
                         cs_config.get('csids', []),
                         cs_config.get('ports', []),
                         cs_config.get('cap_kw', [])
                     ) if port > 0]

        print(f"\n  設置CS数: {len(active_cs)}")
        print(f"  合計ポート数: {sum(p for _, p, _ in active_cs)}")

        for csid, port, cap in active_cs:
            print(f"    CS#{csid}: {port}ポート x {cap}kW = 最大{port*cap}kW")

    except Exception as e:
        print(f"⚠️ CS設定の読み込みエラー: {e}")

    # 時系列データ
    try:
        # 辞書型とオブジェクト型の両方に対応
        if isinstance(emates_result, dict):
            timeseries_kw = emates_result.get('time_series_kw')
        else:
            timeseries_kw = emates_result.time_series_kw
        print(f"\n📈 時系列データ:")
        print(f"  データ形状: {timeseries_kw.shape}")
        print(f"  タイムステップ数: {len(timeseries_kw)}")
        print(f"  CS数: {timeseries_kw.shape[1]}")

        # 統計情報
        print(f"\n  各CSの充電量統計:")
        for col_idx, col_name in enumerate(timeseries_kw.columns):
            daily_kwh = timeseries_kw[col_name].sum() /60
            avg_kw = timeseries_kw[col_name].mean()
            max_kw = timeseries_kw[col_name].max()
            print(f"    CS{col_idx} (列{col_name}): 合計{daily_kwh:,.0f}kWh/日, 平均{avg_kw:.1f}kW, 最大{max_kw:.1f}kW")

    except Exception as e:
        print(f"⚠️ 時系列データの読み込みエラー: {e}")

    # 車両トリップデータ
    try:
        # 辞書型とオブジェクト型の両方に対応
        if isinstance(emates_result, dict):
            vehicle_trip = emates_result.get('vehicle_trip')
        else:
            vehicle_trip = emates_result.vehicle_trip
        print(f"\n🚗 車両トリップデータ:")
        print(f"  総車両数: {len(vehicle_trip)}")
        print(f"  カラム: {list(vehicle_trip.columns)}")

        # 充電した車両
        charging_vehicles = vehicle_trip[vehicle_trip['startChargingTime'] > 0]
        print(f"  充電車両数: {len(charging_vehicles)} ({len(charging_vehicles)/len(vehicle_trip)*100:.1f}%)")

        # 完了した車両
        completed = vehicle_trip[~vehicle_trip['EndTime'].isna()]
        print(f"  完了車両数: {len(completed)} ({len(completed)/len(vehicle_trip)*100:.1f}%)")

    except Exception as e:
        print(f"⚠️ 車両トリップデータの読み込みエラー: {e}")

    # ====== コスト計算 ======
    print("\n" + "="*80)
    print("【初期コスト計算】")
    print("="*80)

    try:
        initial_costs = calc_initial_costs(cs_config, timeseries_kw)

        print(f"\n計算内訳:")
        for i, (csid, port, cap) in enumerate(active_cs):
            charger_cost = CHARGER_COST[str(int(cap))] * port
            substation_cost = SUBSTATION_COST_PER_KW * cap * port
            installation_cost = INSTALLATION_COST
            total = charger_cost + substation_cost + installation_cost

            print(f"  CS#{csid}:")
            print(f"    充電器: {CHARGER_COST[str(int(cap))]}万円 x {port}ポート = {charger_cost:,.0f}万円")
            print(f"    変電所: {SUBSTATION_COST_PER_KW}万円/kW x {cap*port}kW = {substation_cost:,.0f}万円")
            print(f"    設置: {installation_cost:,.0f}万円")
            print(f"    小計: {total:,.0f}万円")

        print(f"\n初期コスト合計: {initial_costs:,.1f}万円")
        print(f"          約: {initial_costs/10000:.2f}億円")

    except Exception as e:
        print(f"❌ 初期コスト計算エラー: {e}")
        import traceback
        traceback.print_exc()

    # ====== 運用コスト ======
    print("\n" + "="*80)
    print("【運用コスト計算（年間）】")
    print("="*80)

    try:
        running_costs = calc_running_costs(cs_config, timeseries_kw)

        print(f"\n計算内訳:")

        # 各CSごとの計算
        maintenance_total = 0
        contract_total = 0
        revenue_total = 0

        for cs_idx, (csid, port, cap) in enumerate(active_cs):
            max_capacity = cap * port

            # 時系列データから対応するカラムを見つける
            # cs_configのインデックスと時系列データのカラムが対応
            cs_indices = [i for i, p in enumerate(cs_config.get('ports', [])) if p > 0]
            if cs_idx < len(timeseries_kw.columns):
                col_name = timeseries_kw.columns[cs_indices[cs_idx]]
                daily_kwh = timeseries_kw[col_name].sum()/60  # 日あたりのkWhに変換
            else:
                daily_kwh = 0

            maintenance = MAINTENANCE_COST_PER_YEAR
            contract = CONTRACT_COST_PER_KW_MONTH * max_capacity * 12
            revenue = (CHARGING_PRICE_PER_KWH - USAGE_COST_PER_KWH) * daily_kwh * 365

            maintenance_total += maintenance
            contract_total += contract
            revenue_total += revenue

            print(f"  CS#{csid}:")
            print(f"    保守コスト: {maintenance:,.1f}万円/年")
            print(f"    契約コスト: {contract:,.1f}万円/年")
            print(f"    充電量: {daily_kwh:,.0f}kWh/日")
            print(f"    純収益: {revenue:,.1f}万円/年 (価格{CHARGING_PRICE_PER_KWH*10000:.0f}円 - 使用{USAGE_COST_PER_KWH*10000:.0f}円)")
            print(f"    純コスト: {maintenance + contract - revenue:,.1f}万円/年")

        print(f"\n年間運用コスト:")
        print(f"  保守コスト合計: {maintenance_total:,.1f}万円")
        print(f"  契約コスト合計: {contract_total:,.1f}万円")
        print(f"  純収益合計: {revenue_total:,.1f}万円")
        print(f"  ─────────────")
        print(f"  純コスト: {running_costs:,.1f}万円/年")

        if running_costs > 0:
            print(f"  ⚠️  運用赤字（コスト > 収益）")
        else:
            print(f"  ✅ 運用黒字（収益 > コスト）")

    except Exception as e:
        print(f"❌ 運用コスト計算エラー: {e}")
        import traceback
        traceback.print_exc()

    # ====== ユーザーコスト ======
    print("\n" + "="*80)
    print("【ユーザーコスト計算（年間）】")
    print("="*80)

    try:
        diff_time, user_costs = calc_diff_trnsprt_costs(vehicle_trip)

        print(f"\n計算内訳:")
        print(f"  ベースライン旅行時間: {BASELINE_TRIP_TIME:,.1f}時間")
        print(f"  差分旅行時間: {diff_time:,.1f}時間")
        print(f"  時間価値: {TIME_VALUE_OF_MONEY*10000:.0f}円/時")
        print(f"\n年間ユーザーコスト: {user_costs:,.1f}万円")
        print(f"1日あたり: {user_costs/365:,.1f}万円")

        if user_costs > 0:
            print(f"  ⚠️  ユーザー負担増加（旅行時間が増加）")
        else:
            print(f"  ✅ ユーザー負担減少（旅行時間が減少）")

    except Exception as e:
        print(f"❌ ユーザーコスト計算エラー: {e}")
        import traceback
        traceback.print_exc()

    # ====== 統合コスト ======
    print("\n" + "="*80)
    print("【統合コスト計算（5年評価）】")
    print("="*80)

    try:
        total_cost, _ = evaluation_total_costs(result_file)

        # 割引計算の内訳
        running_discounted = sum(running_costs / ((1 + DISCOUNT_RATE) ** i)
                                for i in range(1, YEAR + 1))
        user_discounted = sum(user_costs / ((1 + DISCOUNT_RATE) ** i)
                             for i in range(1, YEAR + 1))

        print(f"\n初期コスト: {initial_costs:,.1f}万円")
        print(f"運用コスト（5年割引後）: {running_discounted:,.1f}万円")
        print(f"ユーザーコスト（5年割引後）: {user_discounted:,.1f}万円")
        print(f"─────────────────────")
        print(f"総コスト: {total_cost:,.1f}万円")
        print(f"    約: {total_cost/10000:.2f}億円")

        print(f"\nコスト構成比:")
        if total_cost != 0:
            print(f"  初期コスト: {abs(initial_costs)/abs(total_cost)*100:.1f}%")
            print(f"  運用コスト: {abs(running_discounted)/abs(total_cost)*100:.1f}%")
            print(f"  ユーザーコスト: {abs(user_discounted)/abs(total_cost)*100:.1f}%")

    except Exception as e:
        print(f"❌ 統合コスト計算エラー: {e}")
        import traceback
        traceback.print_exc()

    # ====== 待ち時間 ======
    print("\n" + "="*80)
    print("【95パーセンタイル待ち時間】")
    print("="*80)

    try:
        wait_time_95p = calculate_95percentile_wait_time(result_file)

        if wait_time_95p == float('inf'):
            print("⚠️ 充電できた車両がありません")
        else:
            print(f"95パーセンタイル待ち時間: {wait_time_95p:.1f}秒 = {wait_time_95p/60:.1f}分")

    except Exception as e:
        print(f"❌ 待ち時間計算エラー: {e}")

    # ====== サマリー ======
    print("\n" + "="*80)
    print("【テスト結果サマリー】")
    print("="*80)

    try:
        print(f"✅ pickleファイル読み込み: 成功")
        print(f"✅ 初期コスト計算: {initial_costs:,.1f}万円")
        print(f"✅ 運用コスト計算: {running_costs:,.1f}万円/年")
        print(f"✅ ユーザーコスト計算: {user_costs:,.1f}万円/年")
        print(f"✅ 統合コスト計算: {total_cost:,.1f}万円")
        print(f"✅ 待ち時間計算: {wait_time_95p:.1f}秒")

        print(f"\n📊 実データでのコスト計算: 正常動作確認")

    except:
        print(f"⚠️ 一部のコスト計算でエラーが発生")


if __name__ == "__main__":
    # コマンドライン引数からファイルパスを取得
    if len(sys.argv) > 1:
        result_file = sys.argv[1]
    else:
        # デフォルトのファイルパス
        result_file = "Z:\\output\\unified_P10_P10\\trial_1_combo_1_failure_3.pkl"

    test_actual_simulation_result(result_file)
