#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Discord通知送信CLIスクリプト

bashスクリプトから呼び出してシミュレーション完了・エラーをDiscordに通知

使用方法:
    # 成功時
    python send_notification.py --status success --elapsed 3661 --total 6 --success 6

    # エラー時
    python send_notification.py --status error --elapsed 1800 --total 6 --success 4 --failed-weights 0.4 0.6
"""

import argparse
import sys
from pathlib import Path

# notify_helper.pyをインポート
sys.path.insert(0, str(Path(__file__).parent))
from notify_helper import COLOR_ERROR, COLOR_SUCCESS, send_discord_notification


def format_time(seconds: int) -> str:
    """秒数を「時間分秒」形式に変換

    Args:
        seconds: 経過時間（秒）

    Returns:
        フォーマットされた時間文字列

    Example:
        >>> format_time(3661)
        '1時間1分1秒'
        >>> format_time(125)
        '0時間2分5秒'
    """
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}時間{minutes}分{secs}秒"


def main():
    parser = argparse.ArgumentParser(
        description="シミュレーション実行結果をDiscordに通知"
    )
    parser.add_argument(
        "--status",
        required=True,
        choices=["success", "error"],
        help="実行ステータス: success または error",
    )
    parser.add_argument(
        "--elapsed", type=int, required=True, help="経過時間（秒）"
    )
    parser.add_argument(
        "--total", type=int, required=True, help="実行総数"
    )
    parser.add_argument(
        "--success", type=int, required=True, help="成功数"
    )
    parser.add_argument(
        "--failed-weights",
        nargs="*",
        default=[],
        help="失敗したweightのリスト（エラー時のみ）",
    )

    args = parser.parse_args()

    # 計算
    failed_count = args.total - args.success
    elapsed_str = format_time(args.elapsed)

    # ステータスに応じて通知内容を構築
    if args.status == "success":
        title = "✅ 最適化バッチ実行完了"
        color = COLOR_SUCCESS
        description = "全てのシミュレーションが正常に完了しました"
    else:
        title = "❌ 最適化バッチ実行完了（エラーあり）"
        color = COLOR_ERROR
        if args.failed_weights:
            failed_weights_str = ", ".join(str(w) for w in args.failed_weights)
            description = (
                f"一部のシミュレーションでエラーが発生しました\n"
                f"**失敗したweight**: {failed_weights_str}"
            )
        else:
            description = "一部のシミュレーションでエラーが発生しました"

    # フィールドを構築
    fields = [
        {"name": "⏱️ 実行時間", "value": elapsed_str, "inline": True},
        {"name": "📊 実行数", "value": str(args.total), "inline": True},
        {"name": "✅ 成功", "value": str(args.success), "inline": True},
        {"name": "❌ 失敗", "value": str(failed_count), "inline": True},
    ]

    # Discord通知を送信
    if send_discord_notification(title, description, color, fields):
        print("📱 Discord通知を送信しました")
        return 0
    else:
        print(
            "ℹ️  Discord通知は設定されていません\n"
            "環境変数 DISCORD_WEBHOOK_URL を設定すると通知が有効になります\n"
            "詳細: 03_scripts/DISCORD_SETUP.md を参照"
        )
        return 0  # 通知失敗でもエラーコードは返さない（処理は継続）


if __name__ == "__main__":
    sys.exit(main())
