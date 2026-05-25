---
slug: v13_token_cap_dynamic
title: tool_mine/search token cap dynamic per-tool (F5 closure)
created: 2026-05-26
target_version: graphify-v1.3
priority: P3 (backlog)
status: backlog
---

# v1.3 — Dynamic token cap per MCP tool

## Sorun
Şu an `_cap_for(...)` tüm tool'lar için 50 default; geniş projelerde
`tool_mine` sonuçları clip ediliyor (production scenario).

## Tasarım
- Config: `mcp.token_caps: {mine: 500, search: 50, traverse: 100}`
- `_cap_for(registry, slug, tool, default)` config'i okusun
- ProjectRegistry'de eksik anahtarlar için default fallback

## Acceptance
- `tool_mine` 500-token cap'e kadar genişler
- `tool_search` 50 (mevcut) korunur
- Suite: 187+ PASS, yeni test_token_caps_per_tool
