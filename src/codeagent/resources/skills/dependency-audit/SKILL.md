---
name: dependency-audit
description: 审计项目依赖的安全性、过期版本与更新建议。
---

1. 识别依赖清单:优先 `pyproject.toml`(Python / uv 项目),否则按项目类型找 `package.json` / `go.mod` / `Cargo.toml`。
2. 检查依赖是否过期:`uv pip list --outdated`(或对应生态的等价命令)。
3. 安全审计:说明已知漏洞的来源与修复版本;无法联网时明确说明"离线未做安全库查询"。
4. 输出分级建议:高危(尽快升级)/ 中危(规划升级)/ 低危(可暂缓),不擅自执行安装或升级命令。
