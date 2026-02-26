# Kiro User Activity Analytics

Kiro 企业版用户活动数据分析平台。自动采集 S3 中的用户报告，通过 Athena 查询，在 QuickSight 中展示综合仪表板。

## 架构

```
Kiro Enterprise → S3 (CSV Reports)
                    ├── by_user_analytic/  (每日用户行为明细，46 列)
                    └── user_report/       (每日用户 Credit 汇总，11 列)
                          ↓
                    Glue Crawlers (每天 UTC 2:00 自动爬取)
                          ↓
                    Athena Tables + Views
                          ↓
                    Lambda (每天 UTC 3:00 自动同步用户名映射)
                          ↓
                    QuickSight Datasets (LEFT JOIN user_mapping)
                          ↓
                    QuickSight 综合仪表板 (3 个 Sheet)
```

## 仪表板内容

综合仪表板包含 3 个 Sheet：

- **概览** — 活跃用户数、Credit 消耗、超额统计、消耗趋势、Top 用户、订阅层级分布
- **用户行为** — AI 代码生成量、Chat 消息数、代码生成趋势、Inline 接受率、Top 代码用户
- **成本分析** — 超额趋势、各层级对比、用户 Credit 使用明细表

另有 4 个独立分析（管理概览、用户行为、成本优化、功能采用），包含更详细的图表。

## 前置条件

- AWS CLI 已配置，有足够权限
- Python 3.9+
- Kiro 企业版已开启 User Activity Report，数据投递到 S3
- QuickSight Enterprise 已启用
- IAM Identity Center 已配置（用于用户名映射）

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置
cp config.example.yaml config.yaml
# 编辑 config.yaml，填写：
#   - aws.account_id
#   - s3.bucket_name
#   - identity_center.identity_store_id
#   - quicksight.user_arn

# 3. 一键部署
chmod +x deploy.sh
./deploy.sh
```

`deploy.sh` 是端到端部署脚本，按顺序执行 9 个步骤：

1. 部署 CloudFormation（Glue Crawlers、Athena Workgroup、Lambda、EventBridge）
2. 配置 Lake Formation 权限
3. 运行 Glue Crawlers 并等待完成
4. 验证 Athena 数据查询
5. 创建 Athena 视图
6. 同步用户名映射（Identity Center → S3 → Athena 表）
7. 部署 QuickSight 数据源和数据集
8. 部署 QuickSight 可视化分析
9. 发布综合仪表板

## 项目结构

```
├── config.yaml                  # 项目配置（不提交 Git）
├── config.example.yaml          # 配置模板
├── deploy.sh                    # 端到端部署脚本
├── infrastructure/
│   └── cloudformation.yaml      # AWS 基础设施（Glue、Athena、Lambda、EventBridge）
├── scripts/
│   ├── create_views.py          # 创建 Athena SQL 视图
│   ├── sync_user_mapping.py     # 同步 userid → 用户名映射（也可手动运行）
│   ├── create_dashboards.py     # 创建 QuickSight 数据源、数据集、分析
│   ├── create_visuals.py        # 创建 4 个分析的可视化图表
│   └── create_dashboard_publish.py  # 创建并发布综合仪表板
├── sql/
│   └── create_views.sql         # Athena 视图 SQL 定义
└── quicksight/
    ├── dashboard_admin_overview.json
    ├── dashboard_user_behavior.json
    ├── dashboard_cost_optimization.json
    └── dashboard_feature_adoption.json
```

## 数据源

### by_user_analytic（行为明细）
每日每用户的详细使用数据：Chat 代码生成、Inline 补全、代码审查、测试生成、Dev Agent 等 7 大功能的使用量。

### user_report（Credit 汇总）
每日每用户的订阅和消费数据：订阅层级、Credit 使用量、超额消费、消息数等。

## 用户名映射

报告中的 `userid` 是 IAM Identity Center 的 UUID。项目通过以下方式自动映射为可读的用户名：

- Lambda 函数每天自动运行，从 Athena 查出所有 userid，调用 Identity Center API 获取 DisplayName
- 映射 CSV 存储在 `s3://<bucket>/user-mapping/user_mapping.csv`
- QuickSight 数据集通过 LEFT JOIN 关联映射表，图表中直接显示用户名

手动触发同步：
```bash
python3 scripts/sync_user_mapping.py
# 或
aws lambda invoke --function-name kiro-user-mapping-sync /tmp/out.json
```

## 重新部署

删除旧 stack 后重新部署：
```bash
aws cloudformation delete-stack --stack-name kiro-analytics-stack
# 等待删除完成后
./deploy.sh
```

仅更新仪表板（不重建基础设施）：
```bash
python3 scripts/create_visuals.py
python3 scripts/create_dashboard_publish.py
```
