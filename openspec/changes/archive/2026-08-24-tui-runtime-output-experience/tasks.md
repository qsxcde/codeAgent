## 1. 运行状态和事件契约

- [x] 1.1 定义 RuntimeSnapshot、phase 状态及 session_id/run_id 关联规则
- [x] 1.2 扩展 AgentEvent 生命周期类型和可选元数据字段
- [x] 1.3 发出模型、工具、确认、压缩、取消、错误和重试生命周期事件
- [x] 1.4 为所有阶段转换及过期事件增加 reducer 测试

## 2. 状态栏与命令诊断

- [x] 2.1 扩展 StatusBar/Footer 状态，显示阶段、耗时、当前操作和上下文新鲜度
- [x] 2.2 更新 TuiApp 的 /status，展示运行、工具、错误、重试、渲染和输出诊断信息
- [x] 2.3 在模型或 provider 重建及会话恢复时同步 context_window
- [x] 2.4 增加 compact 阶段计时，并在 restoring/compacting 时门控输入

## 3. 渲染调度和大型历史

- [x] 3.1 增加合并刷新的帧调度器，控制在 30fps 目标并保留活动状态计时
- [x] 3.2 增加组件 revision 以及按宽度和 revision 复用的 RichLine/layout 缓存
- [x] 3.3 增加 viewport/overscan 布局索引，并在未跟随底部时显示新输出数量
- [x] 3.4 增加 resize 防抖，并让后端只渲染可见区域

## 4. 工具输出缓冲和分页

- [x] 4.1 为 ToolResult/events 增加非持久化输出统计元数据
- [x] 4.2 实现 OutputBuffer 的头尾预览、页游标和截断状态
- [x] 4.3 增加面向输出的分页和导出交互，且不触发模型调用或修改会话历史
- [x] 4.4 增加可选 artifact 写入和清理，并明确不可恢复输出的诊断信息

## 5. Restore、重试和退出生命周期

- [x] 5.1 让大型会话恢复可观测，安全卸载阻塞式快照读取，并防止过期会话覆盖当前界面
- [x] 5.2 实现 retry/continue 命令及副作用和 cleanup 不确定状态的确认语义
- [x] 5.3 通过 TuiBackend/TextualBackend 按块生成和写出完整退出文档

## 6. 验证

- [x] 6.1 增加阶段状态、状态栏、会话恢复、压缩和重试测试
- [x] 6.2 增加输出预览、分页、截断和导出测试
- [x] 6.3 增加帧调度、缓存、viewport、resize 测试及大型历史基准
- [x] 6.4 运行完整测试套件和严格 OpenSpec 校验，并记录手工验收结果
