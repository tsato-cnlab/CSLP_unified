# 改修指示書: Optuna探索効率化（実効パラメータによる重複スキップ）

## 1. 概要
現在の最適化プロセスにおいて、シミュレーション結果が100%同一になるパラメータセットを重複して計算している課題があります。
特に、**「設置しない（$u_i=0$）」を選択した箇所の「台数（$n_i$）」や「出力（$p_i$）」を変化させただけのケース**は、シミュレーション結果に影響を与えません。
これらを「実質的に同一のパラメータ」とみなし、計算をスキップ（Pruning）するロジックを実装してください。

## 2. 前提条件
* **シミュレーション特性:** ランダム性なし（入力が同じなら出力は常に一定）。
* **Sampler設定:** 既に設定済みのため変更不要。
* **対象変数:** 各地点 $i$ に対して、$u_i$ (設置有無), $n_i$ (台数), $p_i$ (出力)。

## 3. 実装要件
`objective` 関数の冒頭に、以下のロジックを追加してください。

1.  **実効パラメータの生成:**
    * $u_i = 0$ の場合、$n_i, p_i$ の値を無視し、固定値（例: -1）に置き換えたタプルを作成する。
    * $u_i = 1$ の場合、そのままの値を使用する。
2.  **重複チェック:**
    * 生成した実効パラメータのタプルが、過去に計算済み（`visited` セットに存在）か確認する。
3.  **Pruning:**
    * 重複している場合、シミュレーションを実行せずに `optuna.TrialPruned` を発生させ、即座に終了する。

## 4. 実装コードイメージ

既存の `objective` 関数を以下のように拡張してください。

```python
import optuna

# 【追加】計算済みの実効パラメータ構成を記録するセット（グローバルまたはクラスメンバとして保持）
visited_effective_params = set()

def objective(trial):
    # --- 1. パラメータの提案 (既存のコード) ---
    # 例: 10箇所(I=0..9)について提案を受けると仮定
    params = {}
    num_locations = 10 # 実際の実装に合わせて変更してください

    for i in range(num_locations):
        # 変数名は既存実装に合わせてください
        u_val = trial.suggest_int(f"u_{i}", 0, 1)
        n_val = trial.suggest_int(f"n_{i}", 1, 4)
        p_val = trial.suggest_categorical(f"p_{i}", [50, 100])

        params[f"u_{i}"] = u_val
        params[f"n_{i}"] = n_val
        params[f"p_{i}"] = p_val

    # --- 2. 【追加】実効パラメータによる重複チェック ---
    effective_key_list = []

    for i in range(num_locations):
        u = params[f"u_{i}"]
        n = params[f"n_{i}"]
        p = params[f"p_{i}"]

        if u == 0:
            # 設置しない場合、nとpは結果に影響しないため、固定値(-1)に正規化
            # これにより (u=0, n=1, p=50) と (u=0, n=4, p=100) を「同じ」とみなす
            effective_key_list.append((i, 0, -1, -1))
        else:
            # 設置する場合は全ての値が有効
            effective_key_list.append((i, 1, n, p))

    # ハッシュ可能なタプルに変換
    current_effective_key = tuple(effective_key_list)

    # 既に計算した構成と実質的に同じならスキップ
    if current_effective_key in visited_effective_params:
        # シミュレーションを実行せず、Optunaに「ここは見る価値なし(重複)」と伝える
        raise optuna.TrialPruned("Duplicate effective parameters")

    # 新規の構成なら記録
    visited_effective_params.add(current_effective_key)
```

## 5. 期待される効果
* $u_i=0$ の際の無意味な $n_i, p_i$ 探索により発生していた「計算時間の浪費」と「最適化グラフの停滞（横一直線のプロット）」が解消される。
* 削減された計算リソースが、より有意なパラメータ探索に充てられる。
