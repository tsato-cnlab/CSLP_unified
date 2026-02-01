#!/bin/bash
# シミュレーション実行後に、結果を別のフォルダーにコピーして実行するスクリプト

set -e  # エラーが起きたら停止

# 実行するweightのリスト
WEIGHTS=(0.0 0.2 0.4 0.6 0.8 1.0)

# ファイル名
CONFIG_NAME="21_input/unified_config.json"

# 開始時刻を記録
START_TIME=$(date +%s)
SUCCESS_COUNT=0
FAILED_WEIGHTS=()

# 環境情報
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/1467518283052744766/LP8c9zTwhntcHixB69QOLtzpZGiORYFQyMksJ77kuaGxzmtA14NPxwBLuwNtCiS82HpZ"
echo "🚀 最適化バッチ開始: $(date '+%Y-%m-%d %H:%M:%S')"
echo "==========================================================="

# 実行するfailure_weightのリスト
for weight in ${WEIGHTS[@]}; do
    echo ""
    echo "-----------------------------------------------------------"
    echo "🔄 実行中: failure_weight = $weight"
    echo "-----------------------------------------------------------"

    # set -eを一時的に無効化してエラーをキャッチ
    set +e
    uv run --active 03_scripts/run_multiple_weights.py --base-config $CONFIG_NAME --weights $weight --skip-existing
    EXIT_CODE=$?
    set -e

    if [ $EXIT_CODE -ne 0 ]; then
        echo "❌ エラー: failure_weight = $weight"
        FAILED_WEIGHTS+=($weight)
    else
        echo "✅ 完了: failure_weight = $weight"
        SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
    fi
done

# 終了時刻と経過時間を計算
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
TOTAL=${#WEIGHTS[@]}
FAILED=${#FAILED_WEIGHTS[@]}

echo ""
echo "==========================================================="
echo "📊 バッチ実行完了"
echo "==========================================================="
echo "⏱️  実行時間: $((ELAPSED / 3600))時間$((ELAPSED % 3600 / 60))分$((ELAPSED % 60))秒"
echo "📈 実行総数: $TOTAL"
echo "✅ 成功: $SUCCESS_COUNT"
echo "❌ 失敗: $FAILED"

if [ $FAILED -gt 0 ]; then
    echo "⚠️  失敗したweight: ${FAILED_WEIGHTS[@]}"
fi

echo "==========================================================="

# Discord通知を送信
echo ""
echo "📱 Discord通知を送信中..."

if [ $FAILED -eq 0 ]; then
    # 全て成功
    uv run --active 03_scripts/send_notification.py \
        --status "success" \
        --elapsed "$ELAPSED" \
        --total "$TOTAL" \
        --success "$SUCCESS_COUNT"
else
    # 一部またはすべて失敗
    uv run --active 03_scripts/send_notification.py \
        --status "error" \
        --elapsed "$ELAPSED" \
        --total "$TOTAL" \
        --success "$SUCCESS_COUNT" \
        --failed-weights "${FAILED_WEIGHTS[@]}"
fi

echo ""
echo "✨ すべての処理が完了しました"

