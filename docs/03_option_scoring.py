"""Weighted option matrix for SetuHaul architecture (step 3, section 9).
Weights are fixed BEFORE scoring. Scores 1 (poor) to 5 (strong). Run: python3 03_option_scoring.py
"""
CRITERIA = {  # name: (weight, why this weight)
 "Capacity correctness under concurrency": (25, "Brief's central failure; invariants I-1, I-2, I-3, I-11, I-12"),
 "Safety, escalation and guardrails":      (15, "I-5, I-7, I-8, I-13; human-only decisions"),
 "Handles messy multi-turn language":      (20, "Rubric 'Conversation design'; measure M-11; brief's own examples"),
 "Testability":                            (10, "Integrity proof and scenario run are deliverables"),
 "Time to build (learning project)":       (10, "One learner, local machine"),
 "Running cost":                           (5,  "XS tier, small budget"),
 "Explainability and audit":               (5,  "I-9, M-9; refusals must be explainable"),
 "Works on a local / small model":         (5,  "No-budget path (Ollama)"),
 "Room to scale":                          (5,  "6 facilities, 32 docks, spikes"),
}
OPTIONS = {
 "A rules-first workflow": [5,5,2,5,4,5,5,5,3],
 "B single agent + stage-gated tools + code commit": [5,4,5,4,3,3,4,3,4],
 "C multi-agent supervisor": [4,3,5,2,1,2,3,2,5],
}
def score(weights, opts):
    """Return each option as a percent of the best possible score (so weight sets of any total compare)."""
    out = {}
    for name, sc in opts.items():
        out[name] = round(100 * sum(w*s for w, s in zip(weights, sc)) / (5*sum(weights)), 1)
    return out
w = [v[0] for v in CRITERIA.values()]
assert sum(w) == 100
print("BASE WEIGHTS (max 500, shown also as percent)")
for name, sc in OPTIONS.items():
    parts = " + ".join(f"{wi}x{si}" for wi, si in zip(w, sc))
    print(f"  {name}: {parts} = {sum(wi*si for wi, si in zip(w, sc))} ({sum(wi*si for wi, si in zip(w, sc))/5:.1f}%)")
# sensitivity: language 10, testability 20 (what would change my mind)
w2 = w[:]; w2[2] = 10; w2[3] = 20
print("\nSENSITIVITY (language 20->10, testability 10->20):", score(w2, OPTIONS))
# sensitivity: small local model only (local weight 5->20, cost 5->10, scale 5->0)
w3 = w[:]; w3[7] = 20; w3[5] = 10; w3[8] = 0; w3[2] = 15  # weights now total 110; score() normalises
print("SENSITIVITY (must run on small local model only):", score(w3, OPTIONS))
