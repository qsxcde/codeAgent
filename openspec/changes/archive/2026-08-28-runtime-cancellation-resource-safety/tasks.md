## 1. 取消与操作登记

- [x] 1.1 定义 operation 清理状态和运行取消状态，登记活动 operation、取消请求和清理任务
- [x] 1.2 使工具超时、取消、清理成功和清理失败产生一致的结构化结果
- [x] 1.3 修正同步线程工具、subprocess 和 MCP 操作的不可抢占/不确定语义

## 2. 等待式生命周期

- [x] 2.1 为 SessionRuntime 增加 cancel_and_wait、wait_for_idle 和幂等收尾入口
- [x] 2.2 修改 AgentSession、SessionManager 和组合根，切换、释放、配置替换和关闭前等待运行收尾
- [x] 2.3 确保共享模型、MCP client、后台线程和 subprocess 在运行结束后再关闭

## 3. 确认与运行干预

- [x] 3.1 将 ConfirmationCoordinator 改为活动请求注册表，支持响应接受、过期忽略和清理
- [x] 3.2 增加确认超时和取消唤醒逻辑，保证不留下悬挂 Future
- [x] 3.3 修正 steer/follow-up 的队列边界，保证取消时不启动新 turn

## 4. 验证

- [x] 4.1 增加模型等待、工具等待、确认等待和关闭过程中的取消测试
- [x] 4.2 增加清理成功、清理失败、同步不可抢占和 cleanup_uncertain 测试
- [x] 4.3 增加重复 abort、切换/释放/关闭竞态和资源关闭幂等测试
