"""VYRA v3.27.0 — DB Learning Loop modülü.

Veritabanında Ara öğrenme döngüsünün tüm servisleri burada:
  - dedupe_service: 3 katmanlı duplicate kontrolü (hash + cosine + Jaccard)
  - learned_queries_service: DB LLM bypass cache (G3)
  - synthetic_templates + fk_synthetic_generator: FK-driven sentetik üretim (G1)
  - few_shot_auto_populator + few_shot_pruner: Few-shot self-population (G4)
  - schema_drift_detector: Schema değişimi → cache invalidation (G6)
  - result_cache: Redis result fingerprint (G7)
  - synonym_learner: Kullanıcı terimleri → kolon synonym öğrenme (G5)

Plan: .agents/plans/v3.27_db_learning_loop.md
"""
