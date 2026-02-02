# フラット並列処理 テストガイド

## 🎯 テスト目的

フラット並列処理への移行が正しく実装され、期待通り動作することを検証する。

---

## 📝 テスト手順

### テスト1: 最小構成（1トライアル、2シナリオ）

**目的:** 基本動作の確認

```bash
# テスト実行
cd /home/oums/Desktop/emates
python cs_optim_unified.py --config 21_input/test_flat_small.json
```

**期待される動作:**
1. ✅ 「統合最適化バッチ処理開始（フラット並列）」が表示される
2. ✅ 「合計Xタスクをフラット並列実行」が表示される
3. ✅ 各シナリオが「Trial X (ID:Y)」形式でログ出力される
4. ✅ 「Trial X (ID:Y) 集約」が表示される
5. ✅ エラーなく完了する

**確認項目:**
- [ ] 実行時エラーが発生しないか
- [ ] ログに「フラット並列」の文字が含まれるか
- [ ] trial_id形式のログが出力されるか
- [ ] Optunaへの登録が成功するか

---

### テスト2: CPU使用率の確認

**目的:** 並列度の確認

**準備:**
```bash
# 別のターミナルでhtopを起動
htop
```

**実行:**
```bash
# 中規模テスト（2並列、約18シナリオ）
python cs_optim_unified.py --config 21_input/test_flat_medium.json
```

**期待される結果:**
- CPU使用率: **30-50%** (並列度18-20コア想定)
- 旧実装（15-30%）より改善していること

**確認項目:**
- [ ] htopで稼働中のWorkerプロセス数
- [ ] CPU使用率が50%前後か
- [ ] プロセスが段階的ではなく一斉に起動するか

---

### テスト3: 結果の整合性確認

**目的:** 計算結果が正しいか

**確認方法:**
```bash
# Optunaデータベースを確認
python -c "
import optuna
study = optuna.load_study(
    study_name='test_flat_small',
    storage='sqlite:///xx_result/test_flat_small/optuna_study.db'
)
for trial in study.trials:
    print(f'Trial {trial.number}: {trial.value:.2f}万円')
    print(f'  normal_cost: {trial.user_attrs.get(\"normal_cost\", 0):.2f}')
    print(f'  worst_failure_cost: {trial.user_attrs.get(\"worst_failure_cost\", 0):.2f}')
"
```

**確認項目:**
- [ ] unified_costが計算されているか
- [ ] normal_costとworst_failure_costが記録されているか
- [ ] 値が妥当な範囲内か（例: 1000-5000万円）

---

## 🔍 デバッグ

### エラーが発生した場合

**1. import エラー**
```bash
# 必要なモジュールを確認
python -c "import concurrent.futures; print('OK')"
```

**2. Worker ID競合**
- ログで同じWorker IDが複数表示される場合
- `create_all_tasks_flat()`のWorker ID割り当てロジックを確認

**3. trial_idグルーピング失敗**
- 「Trial X 集約」が表示されない場合
- `aggregate_results_by_trial()`のロジックを確認

**4. ProcessPoolExecutor停止**
```bash
# タイムアウト設定を確認
# as_completed()にtimeout引数を追加
```

---

## ✅ 成功基準

- [ ] **機能:** 最小構成でエラーなく完了
- [ ] **性能:** CPU使用率が30%以上
- [ ] **整合性:** Optunaに結果が正しく登録される

全て満たせば実装成功！

---

## 次のステップ

テスト成功後:
1. 中規模テスト（2-4並列）を実行
2. フル構成（8並列）で性能測定
3. 実際の最適化タスクに適用
