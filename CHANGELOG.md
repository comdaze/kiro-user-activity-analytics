# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Documentation
- 补充月报生产基线、事件/响应契约、业务通知错误判定和部署后只读验收
- 补充 Feishu dev/prod Secret 创建、切换、轮换、回滚、`both` 部分成功与同 ARN 防护说明
- 补充 Card JSON 2.0 客户端/容量边界、故障排查、测试边界和 Git 本地配置与 AWS 已部署真值的区别
- 将 `config.example.yaml` 的 Final 通知改为安全默认关闭，避免空 Secret 配置在首次部署时触发失败

## [1.4.0] - 2026-08-31

### Added
- **自然月 Kiro Credits 月报**：新增独立月报 Lambda，按订阅用户汇总 Credits、套餐容量、使用率、固定成本及连续低使用月份
- **月度与年度 Excel**：生成月度明细、订阅快照、稳定别名和年度汇总工作簿，支持从 2026-02 开始同步回填
- **双阶段调度**：每月 1 日生成静默暂定版，每月 2 日生成最终版；最终通知由显式开关和通道参数控制
- **Feishu Card JSON 2.0**：响应式 KPI、风险折叠面板、浅色/深色企业配色、语义图标和完整报告按钮
- **开发/生产通知隔离**：独立 Secrets Manager Secret，支持 `dev`、`prod`、`both` 显式通道；事件缺少 `notify` 时默认不通知，定时 Final 由 CloudFormation 参数明确启用，且生产通道不回退开发机器人
- **历史身份回退**：从历史月报、用户映射和当前名册按身份字段合并姓名与邮箱，不使用当前名册补造历史订阅状态
- **自动化回归测试**：覆盖月度边界、套餐优先级、Excel OOXML、身份合并、Card 2.0、容量限制和通知防误发逻辑

### Changed
- 用户映射同步保留已删除 Identity Center 用户最后一次有效姓名
- 月报 Lambda 使用 SHA-256 地址化的不可变 S3 ZIP 制品部署，依赖固定为 `openpyxl==3.1.5` 和 `et-xmlfile==2.0.0`
- Final EventBridge 规则显式传递 `notify` 与 `notification_channel`，Provisional 显式关闭通知

### Fixed
- 移除年度工作簿重复的 worksheet AutoFilter，避免 Excel 修复或删除筛选/视图记录
- 修复重复用户 ID 覆盖有效姓名、跨风险组重名标识、低使用排序及首次低使用建议等边界问题
- 风险用户超过 24 人时使用密集两行布局并保留全部用户；当前回归规模满足 Card 2.0 的 200 组件预算
- 修复 detail CSV 中合法负数环比被公式注入防护误转义、导致年度工作簿显示为 0 的问题

## [1.3.0] - 2026-03-23

### Added
- **表格序号列**：用户概况表和成本分析表均新增 `row_num` 排名序号，方便快速识别活跃用户数量
- **Athena 视图 `credit_summary`**：Credit 汇总视图，按消耗降序排名，含序号
- **QuickSight 数据集 `kiro-credit-summary-dataset`**：基于 credit_summary 视图，SPICE 模式，每日自动刷新
- **Lambda 代码自动同步**：deploy.sh 步骤 1 在 CloudFormation 部署后，自动从 `cloudformation.yaml` 提取 Lambda inline code 并通过 `update-function-code` 强制更新，解决 CloudFormation 不检测 inline code 变更的问题

### Changed
- **用户概况 Sheet 改进**：
  - 视图 `user_summary` 改为只查询当前自然月数据（不再包含历史月份）
  - KPI 改为"总用户数"和"活跃用户数"（通过 `is_active` 字段 SUM 实现）
  - 柱状图改为按用户分组降序排列（不再按月分色），一眼可见消耗/活跃排名
  - 明细表增加容量（capacity）、使用率（usage_pct）、活跃度（activity_level）字段
- **活跃度按订阅容量比例计算**：PRO=1000, PRO_PLUS=2000, POWER=10000，根据 usage_pct 划分 6 个等级
- **用户映射同步**：`sync_user_mapping.py` 和 Lambda 改为拉取 Identity Center 全部用户，不再仅拉取有使用记录的用户
- **成本分析表格**：改用 `credit_summary` 数据集，含排名序号
- **deploy.sh 步骤 6/7 拆分**：`--from-step 7` 现在可以单独更新 Dashboard

### Fixed
- README 中 3 处 `create_dashboard_publish.py` 修正为 `create_dashboard.py`

## [1.2.0] - 2026-03-23

### Added
- **用户概况 Sheet**：新增 Dashboard 第 4 个 Tab，按自然月展示用户使用情况
  - 每月用户 Credit 消耗柱状图（按用户分色）
  - 每月用户活跃天数柱状图（按用户分色）
  - 用户月度概况表：含层级变化追踪（如 `PRO → PRO_PLUS`）、客户端类型、活跃天数等
- **Athena 视图 `user_summary`**：按自然月聚合用户数据，支持层级变化追踪
- **QuickSight 数据集 `kiro-user-summary-dataset`**：基于 user_summary 视图，SPICE 模式，每日自动刷新
- deploy.sh 步骤 5.5 自动创建 user_summary 视图并授权 Lake Formation 权限

## [1.1.1] - 2026-03-23

### Fixed
- **Lambda 用户名映射再次出现 null**：修复 Lambda 函数两个遗漏的 bug
  - `get_name()` 缺少 `\r` 清理：Identity Center API 返回的 DisplayName 包含 `\r`，导致 CSV 中用户名带不可见字符，OpenCSVSerde 解析后 LEFT JOIN 匹配失败
  - `csv.writer` 未指定 `lineterminator='\n'`：默认使用 `\r\n`，进一步导致解析异常
  - 根本原因：上次部署时本地脚本（已修复）生成了干净的映射文件，但 Lambda 每天自动运行时用未修复的代码覆盖了好的文件
  - 影响文件：`infrastructure/cloudformation.yaml`

## [1.1.0] - 2026-03-13

### Fixed
- **用户名映射问题**：修复 Dashboard 中部分用户显示为 null 的问题
  - AWS 在 2026-03-10 改变了 `user_report` 表的 userid 格式，从纯 UUID 变为带 Identity Store ID 前缀（如 `d-xxxxxxxxxx.{uuid}`）
  - 原有的 `user_mapping` 表只包含纯 UUID，导致新格式无法 JOIN 匹配
  - 修复后为每个用户生成两种格式的映射记录（纯 UUID + 带前缀），确保新旧格式都能正确匹配
  - 影响文件：
    - `scripts/sync_user_mapping.py` - 本地同步脚本
    - `infrastructure/cloudformation.yaml` - Lambda 函数代码

### Changed
- 用户映射表现在包含双倍记录（每个用户 2 条：纯 UUID + 带前缀）
- Athena 查询时提取纯 UUID，但映射表支持两种格式以兼容 JOIN

## [1.0.0] - 2026-03-11

### Added
- 初始版本发布
- 完整的 Kiro User Activity Analytics 数据分析平台
- 支持 by_user_analytic（行为明细）和 user_report（Credit 汇总）两种数据源
- QuickSight 综合仪表板（概览、用户行为、成本分析）
- 自动化用户名映射（Lambda + EventBridge 定时同步）
- SPICE 模式数据集，每日自动刷新

### Fixed
- 修复 Identity Center API 返回的用户名中包含 `\r` 换行符的问题
- 修复 QuickSight 趋势图不显示的问题（date 字段类型转换）
- 添加数据过滤，排除 2026-02-10 之前的异常数据
