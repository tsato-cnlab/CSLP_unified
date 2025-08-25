#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eMATES最適化プロジェクト環境テストスクリプト
"""

import sys
import traceback
import warnings

def test_imports():
    """重要なライブラリのインポートテスト"""
    print("=== ライブラリインポートテスト ===")
    
    required_packages = [
        'optuna',
        'pandas', 
        'numpy',
        'matplotlib',
        'seaborn',
        'sqlite3',
        'concurrent.futures',
        'pathlib',
        'pickle',
        'json'
    ]
    
    success_count = 0
    failed_packages = []
    
    for package in required_packages:
        try:
            if package == 'concurrent.futures':
                import concurrent.futures
            elif package == 'pathlib':
                from pathlib import Path
            else:
                __import__(package)
            print(f"✓ {package} - OK")
            success_count += 1
        except ImportError as e:
            print(f"✗ {package} - FAILED: {e}")
            failed_packages.append(package)
    
    print(f"\nインポート結果: {success_count}/{len(required_packages)} 成功")
    return failed_packages

def test_japanese_fonts():
    """日本語フォントのテスト"""
    print("\n=== 日本語フォントテスト ===")
    
    try:
        import matplotlib.pyplot as plt
        import matplotlib.font_manager as fm
        
        # 利用可能なフォントを確認
        available_fonts = [f.name for f in fm.fontManager.ttflist]
        japanese_fonts = [f for f in available_fonts if any(keyword in f for keyword in ['IPA', 'Noto', 'DejaVu'])]
        
        print(f"利用可能な日本語関連フォント: {len(japanese_fonts)}")
        for font in japanese_fonts[:5]:  # 最初の5つを表示
            print(f"  - {font}")
        
        if len(japanese_fonts) > 5:
            print(f"  ... (他 {len(japanese_fonts) - 5} 個)")
        
        # 簡単なテスト描画
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, 'テスト日本語文字', fontsize=14, ha='center', va='center')
        ax.set_title('日本語フォントテスト')
        plt.close(fig)  # 表示せずにクローズ
        
        print("✓ 日本語フォント機能 - OK")
        return True
        
    except Exception as e:
        print(f"✗ 日本語フォント機能 - FAILED: {e}")
        return False

def test_optuna():
    """Optunaの基本機能テスト"""
    print("\n=== Optuna機能テスト ===")
    
    try:
        import optuna
        
        def objective(trial):
            x = trial.suggest_float('x', -10, 10)
            return (x - 2) ** 2
        
        study = optuna.create_study()
        study.optimize(objective, n_trials=5, show_progress_bar=False)
        
        best_value = study.best_value
        best_params = study.best_params
        
        print(f"✓ Optuna最適化テスト - OK")
        print(f"  最適値: {best_value:.6f}")
        print(f"  最適パラメータ: {best_params}")
        return True
        
    except Exception as e:
        print(f"✗ Optuna最適化テスト - FAILED: {e}")
        print(f"エラー詳細: {traceback.format_exc()}")
        return False

def test_data_processing():
    """データ処理機能のテスト"""
    print("\n=== データ処理機能テスト ===")
    
    try:
        import pandas as pd
        import numpy as np
        
        # サンプルデータ作成
        data = {
            'trial': range(10),
            'value': np.random.random(10),
            'param_x': np.random.uniform(-5, 5, 10)
        }
        df = pd.DataFrame(data)
        
        # 基本統計
        stats = df.describe()
        
        print(f"✓ pandas DataFrame操作 - OK")
        print(f"  データサイズ: {df.shape}")
        print(f"  統計情報取得: {len(stats.columns)} 列")
        
        return True
        
    except Exception as e:
        print(f"✗ データ処理機能 - FAILED: {e}")
        return False

def test_file_operations():
    """ファイル操作のテスト"""
    print("\n=== ファイル操作テスト ===")
    
    try:
        from pathlib import Path
        import pickle
        import json
        
        # テストディレクトリ作成
        test_dir = Path("test_env")
        test_dir.mkdir(exist_ok=True)
        
        # JSONファイルテスト
        test_data = {"test": "data", "numbers": [1, 2, 3]}
        json_file = test_dir / "test.json"
        with open(json_file, 'w') as f:
            json.dump(test_data, f)
        
        # Pickleファイルテスト
        pickle_file = test_dir / "test.pkl"
        with open(pickle_file, 'wb') as f:
            pickle.dump(test_data, f)
        
        # ファイル読み込みテスト
        with open(json_file, 'r') as f:
            loaded_json = json.load(f)
        
        with open(pickle_file, 'rb') as f:
            loaded_pickle = pickle.load(f)
        
        # クリーンアップ
        json_file.unlink()
        pickle_file.unlink()
        test_dir.rmdir()
        
        print(f"✓ ファイル操作 - OK")
        print(f"  JSON読み書き: OK")
        print(f"  Pickle読み書き: OK")
        print(f"  パス操作: OK")
        
        return True
        
    except Exception as e:
        print(f"✗ ファイル操作 - FAILED: {e}")
        return False

def main():
    """メインテスト実行"""
    print("eMATES最適化プロジェクト環境テスト開始\n")
    
    tests = [
        ("ライブラリインポート", test_imports),
        ("日本語フォント", test_japanese_fonts),
        ("Optuna機能", test_optuna),
        ("データ処理", test_data_processing),
        ("ファイル操作", test_file_operations)
    ]
    
    results = {}
    for test_name, test_func in tests:
        try:
            if test_name == "ライブラリインポート":
                failed_packages = test_func()
                results[test_name] = len(failed_packages) == 0
            else:
                results[test_name] = test_func()
        except Exception as e:
            print(f"テスト実行エラー ({test_name}): {e}")
            results[test_name] = False
    
    print("\n=== テスト結果サマリー ===")
    success_count = 0
    for test_name, success in results.items():
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{test_name}: {status}")
        if success:
            success_count += 1
    
    print(f"\n総合結果: {success_count}/{len(tests)} テスト成功")
    
    if success_count == len(tests):
        print("\n🎉 すべてのテストが成功しました！環境は正常に構築されています。")
        return True
    else:
        print(f"\n⚠️  {len(tests) - success_count} 個のテストが失敗しました。環境の確認が必要です。")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
