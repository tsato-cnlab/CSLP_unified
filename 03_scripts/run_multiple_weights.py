#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""複数のfailure_weightで最適化を自動実行するスクリプト

使用方法:
    python scripts/run_multiple_weights.py --base-config unified_config.json
    python scripts/run_multiple_weights.py --base-config unified_config.json --weights 0.0 0.3 0.5 1.0
    python scripts/run_multiple_weights.py --base-config unified_config.json --skip-existing
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional
import requests
from datetime import datetime


def send_line_message(message: str, access_token: Optional[str] = None, user_id: Optional[str] = None) -> bool:
    """LINE Messaging APIで通知を送信

    Args:
        message: 送信するメッセージ
        access_token: LINE Messaging APIのChannel Access Token（省略時は環境変数から取得）
        user_id: 送信先のユーザーIDまたはグループID（省略時は環境変数から取得）

    Returns:
        送信に成功したかどうか
    """
    if access_token is None:
        access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')

    if user_id is None:
        user_id = os.environ.get('LINE_USER_ID')

    if not access_token or not user_id:
        return False

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    data = {
        "to": user_id,
        "messages": [
            {
                "type": "text",
                "text": message
            }
        ]
    }

    try:
        response = requests.post(url, headers=headers, json=data)
        return response.status_code == 200
    except Exception as e:
        print(f"⚠️  LINE通知の送信に失敗: {e}")
        return False


def run_optimization_with_weight(base_config_path: Path, weight: float) -> bool:
    """指定されたweightで最適化を実行"""
    # 設定ファイルを読み込み
    with open(base_config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    # failure_weightを変更
    config['failure_weight'] = weight

    # 実験名にweightを追加
    original_name = config.get('experiment_name', 'unified')
    config['experiment_name'] = f"{original_name}_P{int(weight*100):02d}"

    # 一時設定ファイルを作成
    temp_config_path = base_config_path.parent / f"temp_config_P{int(weight*100):02d}.json"
    with open(temp_config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}")
    print(f"🚀 最適化開始: failure_weight = {weight:.2f}")
    print(f"📝 設定ファイル: {temp_config_path}")
    print(f"📊 実験名: {config['experiment_name']}")
    print(f"{'='*60}\n")

    # 最適化を実行
    try:
        result = subprocess.run(
            ["python", "cs_optim_unified.py", "--config", str(temp_config_path)],
            check=True,
            cwd=base_config_path.parent  # プロジェクトルート
        )

        print(f"\n✅ 完了: failure_weight = {weight:.2f}")

        # 一時ファイルを削除
        temp_config_path.unlink()

        return True

    except subprocess.CalledProcessError as e:
        print(f"\n❌ エラー: failure_weight = {weight:.2f}")
        print(f"終了コード: {e.returncode}")

        # 一時ファイルを削除
        if temp_config_path.exists():
            temp_config_path.unlink()

        return False
    except KeyboardInterrupt:
        print(f"\n⚠️  中断: failure_weight = {weight:.2f}")

        # 一時ファイルを削除
        if temp_config_path.exists():
            temp_config_path.unlink()

        raise


def main():
    parser = argparse.ArgumentParser(
        description="複数のfailure_weightで最適化を自動実行"
    )
    parser.add_argument(
        "--base-config",
        type=str,
        required=True,
        help="ベースとなる設定JSONファイル"
    )
    parser.add_argument(
        "--weights",
        type=float,
        nargs="+",
        default=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
        help="実行するfailure_weightのリスト（デフォルト: 0.0〜1.0を0.1刻み）"
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="既に結果が存在する場合はスキップ"
    )

    args = parser.parse_args()

    base_config_path = Path(args.base_config)
    if not base_config_path.exists():
        print(f"❌ 設定ファイルが見つかりません: {base_config_path}")
        sys.exit(1)

    weights = sorted(args.weights)

    print("\n" + "="*60)
    print("🔄 複数weight最適化バッチ実行")
    print("="*60)
    print(f"📁 ベース設定: {base_config_path}")
    print(f"📊 実行するweight: {weights}")
    print(f"🔢 実行数: {len(weights)}")
    print("="*60 + "\n")

    # 開始時刻を記録
    start_time = datetime.now()

    # 既存結果の確認
    if args.skip_existing:
        with open(base_config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        save_dir_base = Path(config.get('save_dir_base', '/srv/samba/share/output'))
        original_name = config.get('experiment_name', 'unified')

        weights_to_run = []
        for weight in weights:
            exp_name = f"{original_name}_P{int(weight*100):02d}"
            # タイムスタンプが付くので、パターンマッチで検索
            matching_dirs = list(save_dir_base.glob(f"*_{exp_name}"))

            has_result = False
            for result_dir in matching_dirs:
                if (result_dir / "best_result.json").exists():
                    has_result = True
                    break

            if has_result:
                print(f"⏭️  スキップ: P={weight:.2f} (既に実行済み)")
            else:
                weights_to_run.append(weight)

        weights = weights_to_run

        if not weights:
            print("\n✅ 全てのweightが実行済みです")
            return

        print(f"\n📊 実行するweight: {weights} ({len(weights)}個)\n")

    # 各weightで最適化を実行
    results = {}
    try:
        for i, weight in enumerate(weights, 1):
            print(f"\n{'#'*60}")
            print(f"# 進捗: {i}/{len(weights)}")
            print(f"{'#'*60}")

            success = run_optimization_with_weight(base_config_path, weight)
            results[weight] = success

    except KeyboardInterrupt:
        print("\n\n⚠️  ユーザーによる中断")

    # 結果サマリー
    print("\n" + "="*60)
    print("📊 実行結果サマリー")
    print("="*60)

    success_count = sum(1 for v in results.values() if v)
    total_count = len(results)

    for weight, success in sorted(results.items()):
        status = "✅ 成功" if success else "❌ 失敗"
        print(f"  P={weight:.2f}: {status}")

    print(f"\n成功: {success_count}/{total_count}")
    print("="*60 + "\n")

    # LINE通知を送信
    end_time = datetime.now()
    elapsed_time = end_time - start_time
    hours, remainder = divmod(int(elapsed_time.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)

    notification_message = (
        f"🔔 最適化バッチ実行完了\n"
        f"終了時刻: {end_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"経過時間: {hours}時間{minutes}分{seconds}秒\n"
        f"実行数: {total_count}\n"
        f"成功: {success_count}\n"
        f"失敗: {total_count - success_count}"
    )

    if send_line_message(notification_message):
        print("📱 LINE通知を送信しました")
    else:
        print("ℹ️  LINE通知は設定されていません（環境変数 LINE_CHANNEL_ACCESS_TOKEN と LINE_USER_ID を設定すると通知が有効になります）")


if __name__ == "__main__":
    main()
