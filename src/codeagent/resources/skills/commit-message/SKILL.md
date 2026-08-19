---
name: commit-message
description: 生成符合 Conventional Commits 规范的 git 提交信息。
---

1. 若尚未查看变更,先运行 `git status` 与 `git diff`(必要时 `git diff --cached`)。
2. 归纳变更类型:feat / fix / docs / refactor / test / chore / perf。
3. 用中文写主题行(≤50 字符),必要时补充正文要点(原因、影响)。
4. 输出建议的 `git commit` 命令,**不擅自执行**。
