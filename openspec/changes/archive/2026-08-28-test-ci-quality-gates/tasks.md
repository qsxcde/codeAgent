## 1. 设计 CI 分层

- [x] 1.1 确认 test-foundation-stability 和 test-structure-coverage 的测试命令与 marker
- [x] 1.2 将现有 workflow 拆分为快速质量、测试矩阵和包安装 smoke job
- [x] 1.3 为各 job 设置缓存、超时、artifact 和失败日志保留策略

## 2. 增加快速质量门禁

- [x] 2.1 增加测试超时检查并确保本地与 CI 使用相同命令
- [x] 2.2 增加覆盖率报告，记录当前基线但暂不设置过高硬阈值
- [x] 2.3 增加 Ruff 基础静态检查并修复阻塞级问题
- [x] 2.4 保留版本一致性、补丁格式和 OpenSpec 校验

## 3. 增加平台测试矩阵

- [x] 3.1 在 Ubuntu、Windows 和 macOS 上执行稳定的离线测试集
- [x] 3.2 将 bash、subprocess、路径、权限和 MCP stdio 测试接入 platform job
- [x] 3.3 为平台差异测试收集清晰的跳过原因和失败日志
- [x] 3.4 验证平台矩阵不依赖真实 API key、网络或用户目录

## 4. 增加发布前验证

- [x] 4.1 构建 wheel 并检查构建产物内容
- [x] 4.2 在临时虚拟环境中安装 wheel
- [x] 4.3 执行 `codeagent --prompt` fake provider smoke 测试
- [x] 4.4 验证内建 prompt、skill 和其他 resources 在安装包中可用

## 5. 接入性能基线

- [x] 5.1 将 TUI 渲染、历史恢复和内存指标输出为结构化 artifact
- [x] 5.2 建立性能基线比较脚本并支持相对变化报告
- [x] 5.3 初期将性能回归设为告警而非普通 PR 硬失败
- [x] 5.4 根据至少一轮稳定 CI 数据评估覆盖率和性能硬阈值（覆盖率下限 77.9%；性能保持非阻塞告警，待更多稳定样本后再启用硬失败）

## 6. 阶段验收

- [x] 6.1 在本地复现快速质量、完整测试和包 smoke 命令
- [x] 6.2 验证 CI job 之间没有重复执行不必要的慢测试
- [x] 6.3 更新 README、开发文档和 CI 状态说明
