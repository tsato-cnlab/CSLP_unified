#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Discord Webhook通知ヘルパーモジュール

シミュレーション実行完了・エラーをDiscordで通知するための共通モジュール
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests


def send_discord_notification(
    title: str,
    description: str = "",
    color: int = 0x7289DA,  # Discord Blue
    fields: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """Discord Webhookで通知を送信

    Args:
        title: 通知のタイトル
        description: 通知の説明文
        color: Embedの色（16進数）
            - 0x43B581: Green（成功）
            - 0xF04747: Red（エラー）
            - 0x7289DA: Blue（情報）
        fields: 追加フィールドのリスト
            例: [{"name": "フィールド名", "value": "値", "inline": True}, ...]

    Returns:
        送信に成功したかどうか

    Example:
        >>> send_discord_notification(
        ...     title="✅ シミュレーション完了",
        ...     description="全てのシミュレーションが成功しました",
        ...     color=0x43B581,
        ...     fields=[
        ...         {"name": "実行時間", "value": "2時間15分", "inline": True},
        ...         {"name": "成功数", "value": "6/6", "inline": True},
        ...     ]
        ... )
        True
    """
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")

    if not webhook_url:
        # 環境変数が設定されていない場合は警告を表示して終了
        return False

    # Discord Embed形式でメッセージを構築
    embed = {
        "title": title,
        "description": description,
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # フィールドがあれば追加
    if fields:
        embed["fields"] = fields

    payload = {"embeds": [embed]}

    try:
        response = requests.post(webhook_url, json=payload, timeout=10)
        # Discord Webhookは成功時に204 No Contentを返す
        return response.status_code == 204
    except requests.exceptions.RequestException as e:
        print(f"⚠️  Discord通知の送信に失敗: {e}")
        return False


# よく使う色の定数
COLOR_SUCCESS = 0x43B581  # 緑色（成功）
COLOR_ERROR = 0xF04747  # 赤色（エラー）
COLOR_WARNING = 0xFAA61A  # 黄色（警告）
COLOR_INFO = 0x7289DA  # 青色（情報）


if __name__ == "__main__":
    # テスト実行
    print("Discord通知テスト...")

    success = send_discord_notification(
        title="🔔 テスト通知",
        description="notify_helper.pyからのテスト通知です",
        color=COLOR_INFO,
        fields=[
            {"name": "送信元", "value": "notify_helper.py", "inline": True},
            {"name": "ステータス", "value": "正常", "inline": True},
        ],
    )

    if success:
        print("✅ 通知送信成功！Discordを確認してください")
    else:
        print(
            "❌ 通知送信失敗\n"
            "環境変数 DISCORD_WEBHOOK_URL が設定されているか確認してください\n"
            "例: export DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/...'"
        )
