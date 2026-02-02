import optuna
db_path = '/srv/samba/share/output/unified_P00_P00/optuna_study_unified.db'
study = optuna.load_study(
    study_name='unified_optimization_unified_P00',
    storage=f'sqlite:///{db_path}'
)
# 未完了トライアルをFAILEDにマーク
running_trials = [t for t in study.trials if t.state == optuna.trial.TrialState.RUNNING]
for trial in running_trials:
    # Optunaの内部APIを使用してステータスを変更
    study._storage.set_trial_state_values(
        trial._trial_id,
        state=optuna.trial.TrialState.FAIL
    )
    print(f'Trial {trial.number}: RUNNING → FAIL')
print(f'✅ {len(running_trials)}個のトライアルをクリーンアップしました')
