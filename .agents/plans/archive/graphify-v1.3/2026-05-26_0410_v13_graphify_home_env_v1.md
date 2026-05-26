---
slug: v13_graphify_home_env
title: GRAPHIFY_HOME env var support (F4 closure)
created: 2026-05-26
target_version: graphify-v1.3
priority: P3 (backlog)
status: backlog
---

# v1.3 — GRAPHIFY_HOME env var

## Sorun
Şu an `Graphify.__init__` ve CLI yalnızca `Path.home() / ".graphify"`
kullanıyor; CI/test/multi-user senaryolarında override gerekli.

## Tasarım
- `GRAPHIFY_HOME` env var varsa onu kullan, yoksa fallback `Path.home() / ".graphify"`
- `core/graphify.py` + `core/cli.py` ortak helper: `def _graphify_home() -> Path`
- Test: env override + missing env davranışları

## Acceptance
- `GRAPHIFY_HOME=/tmp/gx python -m core.cli status` → DB path `/tmp/gx/instances/*.db`
- Suite: 187+ PASS
