#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
WSL環境での並列シミュレーション実行スクリプト
"""

import sys
import argparse
import logging
from pathlib import Path
import json

from src.util.log_manager import setup_logging
from src.simulation.run_emates import run_parallel_emates_simulations

def load_solutions(path):
    with open(path, 'r') as f:
        return json.load(f)

def main():
    """
    メイン関数
    """
    parser = argparse.ArgumentParser(description='WSLでeMATESシミュレーションを並列実行')
    parser.add_argument('-p', '--parallel', type=int, default=4,
                        help='並列実行数 (デフォルト: 4)')
    parser.add_argument('-c', '--config', type=str, required=True,
                        help='充電ステーションの設定（JSONファイルのパス）')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='デバッグモードを有効化')
    
    args = parser.parse_args()
    
    # ログ設定
    log_file = setup_logging(args.debug)
    logging.info(f"実行パラメータ: 並列数={args.parallel}, 設定={args.config}")
    
    # 充電ステーション設定を解析
    try:
        solutions = load_solutions(args.config)  # JSONファイルを読み込む
        logging.info(f"充電ステーション設定: {solutions}")
    except (ValueError, FileNotFoundError) as e:
        logging.error(f"エラー: {e}")
        sys.exit(1)
    
    # すべての設定を一度に評価
    logging.info(f"総設定数: {len(solutions)}の評価を開始")
    result = run_parallel_emates_simulations(solutions[0], args.parallel)
    logging.info("評価が完了")

    logging.info(f"プログラム終了 (ステータス: {result})")
    sys.exit(result)
    
if __name__ == "__main__":
    main()