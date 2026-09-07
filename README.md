# Kiro User Activity Analytics

Kiro 企业版用户活动数据分析平台。自动采集 S3 中的用户报告数据，通过 Athena 外部表构建数据湖，在 QuickSight (SPICE 模式) 中展示综合仪表板，帮助管理员了解团队的 Kiro 使用情况和 Credit 消耗。

## 系统架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Kiro Enterprise                                │
│                    (User Activity Report 功能)                          │
└──────────────────────────┬──────────────────────────────────────────────┘
                           │ 每日自动投递 CSV
                           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  S3 Bucket                                                              │
│  s3://<bucket>/<prefix>/AWSLogs/<account>/KiroLogs/           │
│  ├── by_user_analytic/   每日用户行为明细 (46 列)                         │
│  │   └── <region>/<year>/<month>/<day>/00/*.csv                         │
│  ├── user_report/        每日用户 Credit 汇总 (11 列)                    │
│  │   └── <region>/<year>/<month>/<day>/00/*.csv                         │
│  └── user-mapping/       用户名映射 (Lambda 生成)                        │
│      └── user_mapping.csv                                               │
└──────────┬──────────────────────────────────────────────────────────────┘
           │                                  │
           ▼                                  ▼
┌─────────────────────┐            ┌─────────────────────────┐
│  Glue API 建表       │            │  Lambda Function        │
│  (部署时一次性执行)   │            │  每天 UTC 3:00          │
│  ├─ by_user_analytic │            │  查询 Athena userid     │
│  └─ user_report      │            │  → Identity Center API  │
│                      │            │  → 生成 user_mapping.csv│
└────────┬─────────────┘            └────────┬────────────────┘
         │                                   │
         ▼                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Glue Data Catalog (kiro_analytics)                                     │
│  ├── by_user_analytic   行为明细表 (Glue API 建表，schema 固定)           │
│  ├── user_report        Credit 汇总表 (Glue API 建表，schema 固定)       │
│  ├── user_mapping       用户名映射表 (脚本管理，schema 可扩展)            │
│  ├── user_summary       用户概况视图 (Athena VIEW，当前自然月)            │
│  └── credit_summary     Credit 汇总视图 (Athena VIEW，含排名序号)        │
└──────────┬──────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  QuickSight (SPICE 模式)                                                │
│  ├── Data Source: Athena 连接                                           │
│  ├── Datasets x4 (SPICE，每日 UTC 04:00 自动刷新):                      │
│  │   ├── activity dataset (by_user_analytic LEFT JOIN user_mapping)     │
│  │   ├── credits dataset  (user_report LEFT JOIN user_mapping)          │
│  │   ├── summary dataset  (user_summary 视图，当前自然月)                │
│  │   └── credit summary dataset (credit_summary 视图，含排名序号)       │
│  ├── Analysis: Kiro 综合分析 (可在控制台编辑)                             │
│  └── Dashboard: Kiro 综合仪表板 (只读发布版)                              │
│      ├── Sheet 1: 概览                                                  │
│      ├── Sheet 2: 用户行为                                              │
│      ├── Sheet 3: 成本分析                                              │
│      └── Sheet 4: 用户概况                                              │
└─────────────────────────────────────────────────────────────────────────┘
```

## 仪表板内容

综合仪表板包含 4 个 Sheet：

| Sheet | 数据集 | 包含图表 |
|-------|--------|---------|
| 概览 | credits | 活跃用户数 KPI、Credit 消耗 KPI、超额 Credit KPI、总消息数 KPI、每日 Credit 趋势折线图、Top 10 用户柱状图、订阅层级分布 |
| 用户行为 | activity | AI 代码行数 KPI、Inline 代码行数 KPI、Chat 消息数 KPI、代码生成趋势折线图、Inline 接受趋势折线图、Top 10 代码用户柱状图 |
| 成本分析 | credits + credit_summary | 每日超额趋势折线图、每日每用户 Credit 消耗趋势、各层级平均消耗柱状图、用户 Credit 使用明细表（含排名序号） |
| 用户概况 | summary | 总用户数 KPI、活跃用户数 KPI、用户 Credit 消耗柱状图（按消耗降序）、用户活跃天数柱状图（按天数降序）、用户概况明细表（含订阅层级、活跃度、容量使用率）。数据范围：当前自然月 |


## 前置条件

### 1. 开启 Kiro User Activity Report

在 AWS 管理控制台中开启 Kiro 的用户活动报告功能：

1. 登录 [AWS Console](https://console.aws.amazon.com/)
2. 进入 **Kiro** (原 Amazon Q Developer) 服务页面
3. 在左侧导航栏选择 **Settings** → **User activity report**
4. 点击 **Enable** 开启报告
5. 配置 S3 存储桶：
   - 选择一个已有的 S3 桶，或创建新桶
   - 记录桶名称（如 `kiro-user-reports-xxxxxxxx`）
   - 报告会自动投递到 `s3://<bucket>/<prefix>/AWSLogs/<account_id>/KiroLogs/` 路径下
   - 确认 S3 桶策略包含 Kiro 服务写入权限：
     ```json
     {
       "Version": "2012-10-17",
       "Statement": [
         {
           "Sid": "KiroLogsWrite",
           "Effect": "Allow",
           "Principal": {
             "Service": "q.amazonaws.com"
           },
           "Action": "s3:PutObject",
           "Resource": "arn:aws:s3:::<bucket-name>/<prefix>/*",
           "Condition": {
             "StringEquals": {
               "aws:SourceAccount": "<account-id>"
             },
             "ArnLike": {
               "aws:SourceArn": "arn:aws:codewhisperer:<region>:<account-id>:*"
             }
           }
         }
       ]
     }
     ```
6. 等待至少 1-2 天，确认 S3 中有数据生成

> **注意**: 报告有 1-2 天的延迟。开启后第二天才会看到第一份报告。

### 2. 其他前置条件

- **AWS CLI** 已安装并配置，当前用户有管理员权限
- **Python 3.9+** 已安装
- **QuickSight Enterprise** 已在当前 Region 启用
- **QuickSight S3 权限（重要！！）**: 在 QuickSight Console → 右上角头像 → Manage QuickSight → Permissions → AWS resources → 勾选 Amazon S3 → 点击 Select S3 buckets，勾选报告所在的 S3 bucket，并启用 "Write permission for Athena Workgroup"
- **IAM Identity Center** 已配置（用于将 userid 映射为可读的用户名）
- **Lake Formation（重要！！）**: 当前用户需要是 Data Lake Admin（部署脚本会自动配置表权限）

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

```bash
cp config.example.yaml config.yaml
```

编辑 `config.yaml`，填写你的环境信息（详见下方配置说明）。

### 3. 一键部署

```bash
# 如果你有多个AWS config, 需要指定具体的profile名称
# export AWS_PROFILE="Your-profile-name"
export AWS_PROFILE=${AWS_PROFILE:-default}

chmod +x deploy.sh
./deploy.sh
```

部署完成后，访问 QuickSight 控制台即可查看仪表板。

## 配置文件说明

`config.yaml` 包含所有部署所需的配置项：

```yaml
# AWS 基础配置
aws:
  region: us-east-1              # AWS Region（必须与 Kiro 和 QuickSight 在同一 Region）
  account_id: "123456789012"     # 你的 AWS 账户 ID（12 位数字，用引号包裹）

# S3 数据源配置
s3:
  bucket_name: "q-developer-reports-xxxxxxxx"  # Kiro User Activity Report 投递的 S3 桶名
  prefix: "amazon-q-developer/"                # S3 前缀（通常不需要修改）

# Glue 配置（通常不需要修改）
glue:
  database_name: "kiro_analytics"    # Glue 数据库名称

# IAM Identity Center 配置
identity_center:
  identity_store_id: "d-xxxxxxxxxx"  # Identity Store ID
                                      # 获取方式: AWS Console → IAM Identity Center → Settings
                                      # 或: aws sso-admin list-instances

# QuickSight 配置
quicksight:
  user_arn: "arn:aws:quicksight:us-east-1:123456789012:user/default/role_name/username"
    # QuickSight 用户 ARN，用于授权访问数据源、数据集和仪表板
    # 获取方式: aws quicksight list-users --aws-account-id <account_id> --namespace default
    # 如果通过 IAM 角色登录 QuickSight，格式为:
    #   arn:aws:quicksight:<region>:<account>:user/default/<role_name>/<username>
  data_source_name: "KiroUserActivity"       # QuickSight 数据源显示名称
  dataset_name: "KiroUserActivityDataset"    # QuickSight 数据集显示名称
```

### 如何获取关键配置值

| 配置项 | 获取方式 |
|--------|---------|
| `aws.account_id` | `aws sts get-caller-identity --query Account --output text` |
| `s3.bucket_name` | Kiro 控制台 → Settings → User activity report 中查看 |
| `identity_center.identity_store_id` | IAM Identity Center 控制台 → Settings → Identity store ID |
| `quicksight.user_arn` | `aws quicksight list-users --aws-account-id <ACCOUNT_ID> --namespace default` |

## 部署流程详解

`deploy.sh` 是端到端部署脚本，按顺序执行以下步骤：

| 步骤 | 说明 | 对应脚本/资源 |
|------|------|--------------|
| 1️⃣ | 构建 SHA-256 地址化月报 ZIP，上传 S3，并部署 CloudFormation/Lambda/EventBridge/IAM | `lambda/monthly_report/`、`infrastructure/cloudformation.yaml` |
| 2️⃣ | 配置 Lake Formation 数据库权限 | deploy.sh 内置 |
| 3️⃣ | 通过 Glue API 创建外部表 + 配置表级别权限 | deploy.sh 内置 |
| 4️⃣ | 验证 Athena 数据查询 | Athena |
| 5️⃣ | 同步用户名映射 + 创建 Athena 视图 | `scripts/sync_user_mapping.py` + deploy.sh 内置 |
| 6️⃣ | 部署 QuickSight 数据源和数据集 (SPICE) | `scripts/create_datasets.py` |
| 7️⃣ | 发布综合仪表板和分析 | `scripts/create_dashboard.py` |
| 8️⃣ | 配置每日 Dashboard 快照报告（SES + S3 静态网站） | deploy.sh 内置 |

> `./deploy.sh --from-step N` 可从指定步骤继续。步骤 1 会把本地、未提交的 `config.yaml` 中月报 Secret ARN、Final 通知开关和通道写入 CloudFormation；执行前必须先与 AWS 已部署参数核对，避免把生产 `prod` 通道意外切回 `dev`。

### Lake Formation 权限

项目自动为以下 Principal 配置 Lake Formation 权限：

| Principal | 权限 | 用途 |
|-----------|------|------|
| 当前 IAM 用户/角色 | CREATE_TABLE, ALTER, SELECT, DESCRIBE | DDL 建表 + Athena 手动查询 |
| QuickSight Service Role | SELECT, DESCRIBE | QuickSight 读取数据 |
| QuickSight 用户 IAM 角色 | SELECT, DESCRIBE | QuickSight 用户访问 |
| Lambda Role | SELECT, DESCRIBE, ALTER, CREATE_TABLE | 用户映射同步 |
| IAMAllowedPrincipals | ALL | 兼容 IAM 模式访问 |


## 项目结构

```
kiro-user-activity-analytics/
├── config.yaml                         # 本地环境配置（Git 忽略，不是生产真值审计记录）
├── config.example.yaml                 # 无环境、默认关闭通知的安全配置模板
├── deploy.sh                           # 端到端部署脚本（步骤 1~8）
├── requirements.txt                    # 主部署/脚本 Python 依赖
├── infrastructure/
│   └── cloudformation.yaml             # Glue、Athena、Lambda、IAM、EventBridge、快照报告
├── lambda/
│   └── monthly_report/
│       ├── index.py                    # 自然月 Credits 月报、Excel、Card 2.0、双通道路由
│       └── requirements.txt            # 月报 ZIP 精确锁定依赖
├── scripts/
│   ├── sync_user_mapping.py            # 同步 userid → 用户名映射并保留最后有效姓名
│   ├── backfill_monthly_reports.py     # 同步历史月报回填，可显式选择通知通道
│   ├── create_datasets.py              # 创建 QuickSight 数据源和数据集 (SPICE)
│   └── create_dashboard.py             # 创建并发布综合仪表板和分析
└── tests/
    └── test_monthly_report.py           # 月报、Excel、Card 2.0 和通知路由回归测试
```

## 数据源说明

### by_user_analytic（行为明细）

每日每用户的详细使用数据，按 `client_type`（KIRO_CLI / KIRO_IDE）分别生成 CSV。

主要字段：
- `date` / `userid` — 日期和用户 ID
- `chat_*` — Chat 功能：AI 代码行数、消息数、交互数
- `inline_*` — Inline 补全：代码行数、建议数、接受数
- `codefix_*` — 代码修复：生成次数、接受次数
- `codereview_*` — 代码审查：发现数、成功次数
- `dev_*` — Dev Agent：生成次数、接受次数、生成行数
- `testgeneration_*` — 测试生成：次数、接受的测试数
- `inlinechat_*` — Inline Chat：总次数、接受次数
- `docgeneration_*` — 文档生成：次数、接受的文件数
- `transformation_*` — 代码转换：次数、生成行数

### user_report（Credit 汇总）

每日每用户的订阅和消费数据，同样按 `client_type` 分别生成。

| 字段 | 说明 |
|------|------|
| `date` | 报告日期 |
| `userid` | IAM Identity Center 用户 ID |
| `client_type` | 客户端类型（KIRO_CLI / KIRO_IDE） |
| `subscription_tier` | 订阅层级（PRO / PRO_PLUS） |
| `credits_used` | 当日 Credit 消耗量 |
| `overage_cap` | 超额上限 |
| `overage_credits_used` | 超额 Credit 消耗 |
| `overage_enabled` | 是否启用超额 |
| `total_messages` | 当日总消息数 |
| `chat_conversations` | 当日 Chat 会话数 |
| `profileid` | Kiro Profile ARN |

> **注意**: `user_report` 功能从 2026-02-10 开始提供数据。早期 PRO 层级的 credit 数值可能异常偏大，升级到 PRO_PLUS 后数据正常。报告有 1-2 天延迟。

## 用户名映射机制

S3 报告中的 `userid` 是 IAM Identity Center 的 UUID（如 `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`），不便于识别。项目通过以下机制自动映射为可读的用户名：

1. **Lambda 函数** (`kiro-user-mapping-sync`) 每天 UTC 3:00 自动运行
2. 从 IAM Identity Center 拉取全部用户列表
3. 从 Athena 查询所有不重复的 `userid`，补充已删除但有历史记录的用户
4. 为每个用户生成两种格式的映射记录（纯 UUID + 带 Identity Store ID 前缀），兼容新旧 userid 格式
5. 生成映射 CSV 上传到 `s3://<bucket>/user-mapping/user_mapping.csv`
6. 创建/更新 Glue 外部表 `user_mapping`
7. QuickSight 数据集通过 `LEFT JOIN` 关联映射表，图表中直接显示用户名

手动触发同步：
```bash
# 本地运行
python3 scripts/sync_user_mapping.py

# 或通过 Lambda
aws lambda invoke --function-name kiro-user-mapping-sync /tmp/out.json && cat /tmp/out.json
```

## 常用操作

### 仅更新数据集配置（不重建基础设施）

当需要修改数据集的字段、筛选器或类型转换时：

```bash
python3 scripts/create_datasets.py
```

此操作会：
- 更新 QuickSight 数据集配置
- 自动触发 SPICE 刷新
- 保留现有的 Dashboard 和 Analysis

### 仅更新仪表板（不重建基础设施）

```bash
python3 scripts/create_datasets.py
python3 scripts/create_dashboard.py
```

### 手动同步用户名映射

当有新用户加入或用户名变更时：

```bash
python3 scripts/sync_user_mapping.py
```

此脚本会：
1. 从 Athena 查询所有不重复的 userid（自动处理新旧格式）
2. 调用 Identity Center API 获取用户显示名
3. 生成 CSV 并上传到 S3
4. 更新 Glue 外部表 `user_mapping`

**注意**：Lambda 函数每天 UTC 3:00 自动执行此操作。

### 更新 Lambda 用户映射函数

`deploy.sh` 步骤 1 在 CloudFormation 部署后会自动从 `infrastructure/cloudformation.yaml` 提取 Lambda inline code 并强制更新。通常无需手动操作。

如需单独更新 Lambda 代码：

```bash
# deploy.sh 步骤 1 会自动执行以下操作：
# 1. 从 cloudformation.yaml 提取 ZipFile 中的 Lambda 代码
# 2. 打包为 zip 并通过 update-function-code 上传

# 手动测试 Lambda
aws lambda invoke --function-name kiro-user-mapping-sync /tmp/out.json && cat /tmp/out.json
```

### 手动触发 SPICE 数据刷新

SPICE 数据集每日 UTC 04:00 自动刷新。如需手动刷新：

```bash
# 通过 QuickSight 控制台: Datasets → 选择数据集 → Refresh now
# 或通过 CLI:
aws quicksight create-ingestion \
    --aws-account-id <ACCOUNT_ID> \
    --data-set-id kiro-user-activity-dataset \
    --ingestion-id manual-$(date +%s)
```

### 完全重新部署

```bash
aws cloudformation delete-stack --stack-name kiro-analytics-stack --region us-east-1
aws cloudformation wait stack-delete-complete --stack-name kiro-analytics-stack --region us-east-1
./deploy.sh
```

### Athena 手动查询示例

```sql
-- 查看最近 7 天的 Credit 消耗
SELECT date, userid, client_type, CAST(credits_used AS decimal) as credits_used
FROM kiro_analytics.user_report
WHERE date >= date_format(date_add('day', -7, current_date), '%Y-%m-%d')
ORDER BY date DESC;

-- 查看每个用户的总代码生成量（OpenCSVSerde 列为 STRING，需要 CAST）
SELECT userid, 
       SUM(CAST(chat_aicodelines AS bigint)) as chat_code,
       SUM(CAST(inline_aicodelines AS bigint)) as inline_code
FROM kiro_analytics.by_user_analytic
GROUP BY userid;
```

## 故障排查

| 问题 | 解决方案 |
|------|---------|
| Athena 查询报 `AccessDeniedException` | 检查 Lake Formation 权限，重新运行 `sh deploy.sh --from-step 3`（建表后会自动重新授权） |
| Athena 查询 `SUM()` 报 `FUNCTION_NOT_FOUND` | OpenCSVSerde 所有列为 STRING，手动查询需要 CAST：`SUM(CAST(col AS bigint))`。QuickSight 数据集已通过 CastColumnTypeOperation 自动转换，不受影响 |
| Glue API 建表失败 | 确认 S3 路径正确，检查 S3 桶策略是否允许访问 |
| QuickSight 报 `SQL exception` / `TABLE_NOT_FOUND` | 1. 确认 Athena 表存在：`aws glue get-table --database-name kiro_analytics --name by_user_analytic`<br>2. 确认 QuickSight 已授权 S3（Manage QuickSight → Security & permissions → S3）<br>3. 确认当前用户是 Lake Formation Data Lake Admin<br>4. 重跑 `sh deploy.sh --from-step 3` |
| QuickSight 数据源 `CREATION_FAILED` | S3 权限问题。先在 QuickSight Console → Manage QuickSight → Security & permissions → S3 中授权 bucket，然后重跑 `sh deploy.sh --from-step 6`（脚本会自动删除失败的数据源并重建） |
| SPICE 刷新失败 | 检查 Athena 表是否可查询，确认 Lake Formation 表权限已授予 QuickSight Service Role。如果是删表重建导致权限丢失，重跑 `sh deploy.sh --from-step 3` |
| Dashboard 数值显示为 0 或无数据 | 可能是 Glue 表列顺序与 CSV header 不匹配。用 `SELECT * FROM kiro_analytics.user_report LIMIT 1` 验证列值是否合理，如不对需要修正表定义并重跑 `sh deploy.sh --from-step 3` |
| 用户名显示为 UUID 或 null | 1. 运行 `python3 scripts/sync_user_mapping.py` 手动同步映射<br>2. 检查 S3 映射文件是否干净：`aws s3 cp s3://<bucket>/user-mapping/user_mapping.csv - \| od -c \| head`，确认无 `\r` 字符<br>3. 如果本地同步成功但 Dashboard 仍显示错误，说明 Lambda 自动同步覆盖了好的文件，需重新部署 `./deploy.sh`<br>4. 如果 Identity Center 重建过用户目录，历史 userid 将无法解析 |
| 仪表板图表为空 | 1. 检查 Athena 表有数据：`SELECT COUNT(*) FROM kiro_analytics.user_report`<br>2. 检查 SPICE 导入状态：QuickSight Console → Datasets → 查看最近导入<br>3. 手动触发 SPICE 刷新 |
| 趋势图不显示线条 | date 字段需要是 DATETIME 类型。确认 `scripts/create_datasets.py` 中有 date 类型转换，重新运行 `python3 scripts/create_datasets.py` |
| S3 没有新数据 | 报告有 1-2 天延迟，确认 Kiro User Activity Report 已开启 |
| CloudFormation 部署报 `ROLLBACK_COMPLETE` | deploy.sh 会自动处理，删除旧 stack 后重建 |
| Lake Formation 权限丢失（删表重建后） | deploy.sh 步骤 3 建表后会自动重新授权所有 principal 的表级别权限，无需手动处理 |

## 数据配置说明

### 数据过滤

默认配置过滤掉 **2026-02-10 及之前**的数据（早期数据质量问题）。如需修改过滤日期：

1. 编辑 `scripts/create_datasets.py`
2. 搜索 `FilterOperation` 和 `parseDate("2026-02-10")`
3. 修改日期后运行 `python3 scripts/create_datasets.py`

### 数据类型转换

数据集自动进行以下转换：
- **date**: STRING → DATETIME（支持趋势图时间序列）
- **数值列**: STRING → INTEGER/DECIMAL（支持聚合计算）

### 已知限制

1. **userid 格式变更（已解决）**: 
   - **问题**：AWS 在 2026-03-10 改变了 `user_report` 表的 userid 格式，从纯 UUID（如 `f448f448-...`）变为带 Identity Store ID 前缀（如 `d-xxxxxxxxxx.f448f448-...`）
   - **影响**：新格式的 userid 无法与旧的 `user_mapping` 表匹配，导致 Dashboard 显示 null
   - **解决方案**：`sync_user_mapping.py` 和 Lambda 函数已修复，为每个用户生成两种格式的映射记录，确保新旧格式都能正确匹配

2. **历史数据延迟**: 
   - Kiro User Activity Report 有 1-2 天延迟
   - 开启后第二天才会看到第一份报告

3. **早期 PRO 层级 credit 数值异常**: 
   - `user_report` 功能从 2026-02-10 开始提供数据
   - 早期 PRO 层级的 credit 数值可能异常偏大
   - 升级到 PRO_PLUS 后数据正常

## 成本估算

本方案使用的 AWS 服务均为按量付费或有免费额度，适合中小团队低成本运行。

### 各服务费用（us-east-1 区域）

| 服务 | 计费项 | 预估费用（50 用户/月） | 说明 |
|------|--------|----------------------|------|
| S3 | 存储 + 请求 | < $0.10 | Kiro 报告 CSV 文件很小，每用户每天 ~1KB |
| Glue Data Catalog | 表存储 | $0 | 前 100 万个对象免费 |
| Athena | 查询扫描量 | < $0.50 | 按扫描数据量计费（$5/TB），CSV 数据量极小；SPICE 模式下日常仅刷新时查询 |
| Lambda | 调用 + 执行时间 | $0 | 每天 1 次调用，远低于免费额度（100 万次/月） |
| EventBridge | 定时规则 | $0 | 免费 |
| Lake Formation | 权限管理 | $0 | 免费 |
| SPICE 额外容量 | 超出免费额度部分 | $0.38/GB/月 | 每个 Author 含 10GB 免费，本方案数据量远低于此 |

### QuickSight / Quick Suite 用户定价

AWS 提供两种订阅方式，根据账号所在区域和需求选择：

| 方案 | 角色 | 价格 | 说明 |
|------|------|------|------|
| **Quick Suite**（推荐） | Professional | $20/用户/月 | 包含 Quick Sight + Quick Research + Quick Flows，功能最全且比单独 Author 更便宜 |
| Quick Suite | Enterprise | $35/用户/月 | 在 Professional 基础上增加自动化工作流等高级功能 |
| **Quick Sight 仅 BI** | Author | $24/用户/月 | 创建/编辑仪表板，含 10GB SPICE |
| Quick Sight 仅 BI | Author Pro | $40/用户/月 | Author + AI 生成式分析（需额外 $250/月账户基础设施费） |
| Quick Sight 仅 BI | Reader | $3/用户/月 | 只读查看、筛选、下载 |
| Quick Sight 仅 BI | Reader Pro | $20/用户/月 | Reader + AI 摘要和场景分析 |

> Quick Suite 在 us-east-1 等区域可用。如果你的区域支持 Quick Suite，Professional $20/月比单独买 Quick Sight Author $24/月更划算。

### 典型场景月费估算

| 场景 | 用户配置 | Quick Suite 方案 | Quick Sight 仅 BI 方案 |
|------|---------|-----------------|----------------------|
| 个人/小团队（1 管理员） | 1 Author | $20 | $24 |
| 中型团队（1 管理员 + 5 只读） | 1 Author + 5 Reader | $20 + $0* | $24 + $15 = $39 |
| 大型团队（2 管理员 + 20 只读） | 2 Author + 20 Reader | $40 + $0* | $48 + $60 = $108 |

> \* Quick Suite Professional 用户可以查看仪表板，不需要额外的 Reader 费用。
>
> 费用主要来自用户订阅。其他服务（S3、Athena、Lambda、Glue）在本方案的数据规模下费用可忽略不计。
>
> 定价参考：[Quick Suite Pricing](https://aws.amazon.com/quick/pricing/)、[QuickSight BI-only Pricing](https://aws.amazon.com/quick/quicksight/pricing/)、[Athena Pricing](https://aws.amazon.com/athena/pricing/)

## 月度 Kiro Credits Excel 报告

月报由独立 Lambda `kiro-monthly-credits-report` 生成，不替换或修改每日 QuickSight/PDF 管道。运行时为 Python 3.12；`deploy.sh` 按 `lambda/monthly_report/requirements.txt` 构建 SHA-256 地址化的不可变 ZIP，并上传到数据桶的 `artifacts/monthly-report/<sha256>.zip`。月报函数预留并发为 1，超时 900 秒，日志保留 90 天。

### 已部署生产基线（截至 2026-08-31）

| 项目 | 已部署值 |
|------|----------|
| CloudFormation stack | `kiro-analytics-stack` / `UPDATE_COMPLETE` |
| Provisional | `cron(0 6 1 * ? *)`、`ENABLED`、`notify=false` |
| Final | `cron(0 6 2 * ? *)`、`ENABLED`、`notify=true`、`notification_channel=prod` |
| Secret | `kiro/monthly-report/feishu-bot-dev` 与 `kiro/monthly-report/feishu-bot-prod` 独立存在 |
| 生产验收范围 | Secret 元数据、Lambda 环境、IAM、EventBridge 输入均已只读验收；切换生产通道时未发送测试消息 |

这张表是带日期的运维快照，不替代 AWS 实际状态。CloudFormation parameters、EventBridge target 和 Lambda environment 才是已部署真值；`config.example.yaml` 只是无环境模板，Git 忽略的 `config.yaml` 是下一次部署输入，不是可靠的生产审计记录。

### 调度、数据范围与输出

- Provisional：每月 1 日 UTC 06:00（北京时间 14:00）生成上一个自然月，EventBridge 明确传入 `notify=false`。
- Final：每月 2 日 UTC 06:00 生成上一个自然月；是否通知及通道完全由 CloudFormation 参数显式传入。
- Athena 仅查询 `user_report`，按规范化用户 ID 汇总 Credits，日期使用 `[月初, 下月月初)` 半开区间和 `TRY` 类型转换。
- 2026-02 标记为 `PARTIAL`，可用数据从 2026-02-10 开始。
- 历史回填早于“当前上一个自然月”时，不使用当前订阅名册补造历史零使用用户；工作簿会明确提示历史名册无法重建。

输出路径如下，报告桶公开策略仅用于既定报告前缀；原始数据桶不公开：

```text
dashboard-reports/public/kiro-monthly/YYYY/MM/kiro-credits-YYYY-MM-provisional.xlsx
dashboard-reports/public/kiro-monthly/YYYY/MM/kiro-credits-YYYY-MM-final.xlsx
dashboard-reports/public/kiro-monthly/YYYY/MM/kiro-credits-YYYY-MM.xlsx  # Final 稳定别名
dashboard-reports/public/kiro-monthly/YYYY/MM/kiro-credits-YYYY-MM-detail.csv
dashboard-reports/public/kiro-monthly/YYYY/MM/kiro-credits-YYYY-MM-subscriptions.csv  # 仅可安全使用当前名册时生成
dashboard-reports/public/kiro-monthly/YYYY/kiro-credits-YYYY.xlsx
```

月度持久化文件先写入 S3，再重建年度文件，最后才尝试通知。年度工作簿每次从该年度全部 detail CSV 重建，不增量追加；数值字段保留合法负数，文本字段进行公式注入防护。所有新对象使用 SSE-S3。

### 订阅名册、套餐和身份

优先读取 `monthly_report.subscription_csv_key` 指向的**精确 S3 key**。文件必须是严格 UTF-8（可带 BOM），支持列别名：`userid/user_id`、`user_name/username/name`、`email`、`subscription_status/status`、`subscription_tier/kiro_plan/plan`、`activation_date`、`plan_source/source`。有效的仅表头空 CSV 也具有权威性；相同用户 ID 按最高套餐去重，同时保留非空姓名和邮箱。

精确 key 未配置或不存在时，Lambda 使用 Kiro Application ARN 分页读取 IAM Identity Center Application Assignments，包含直接 USER，并展开 GROUP 成员。套餐组支持 `Kiro-Pro-users`、`Kiro-Pro+-users`、Pro Max 和 Power 规范化；直接分配用户采用最近使用记录中的套餐，无记录时为 Unknown。

套餐容量/价格：Pro `$20/1000`、Pro+ `$40/2000`、Pro Max `$100/5000`、Power `$200/10000`。红色为零使用或 `<10%`，黄色为 `10%-<50%`，绿色为 `>=50%`；`>=90%` 标记容量压力，`>=100%` 标记超过容量。

历史 detail、`user-mapping/user_mapping.csv` 和当前名册只用于姓名/邮箱身份回退；当前名册不会为历史月份补造订阅状态、套餐、激活日期或零使用行。重名用户附加邮箱，无法识别的身份显示用户 ID 后缀。

### Feishu Card JSON 2.0

- 固定企业蓝 Header，KPI/面板使用浅色和深色独立的中性色 token；红/橙仅作为小型风险标签。
- 语义图标限定为用户、成本、零使用、低用、建议和完整报告，不使用装饰性 Emoji 堆叠。
- 零使用面板始终展开；总风险 `<=20` 时低用面板展开，`>=21` 时折叠，但用户仍保留在 JSON。
- 风险人数 `<=24` 使用双列两行明细，`>24` 使用密集两行 Markdown，以降低组件数且不截断用户。
- Card JSON 2.0 官方客户端要求为 7.20+；PC、iOS、Android 按钮均配置报告 URL。组织实际客户端仍需人工渲染验收。
- 官方上限为 200 个组件。回归样例验证 32 位全风险用户仍低于 200 组件，常规生产样例低于项目自定 20KB 目标；当前实现没有运行时 payload 字节硬限制。若未来用户名或人数显著增长导致飞书拒绝，S3 报告仍然存在，错误只会体现在 Lambda 响应字段中。

### Secret 创建与安全边界

CloudFormation **不会创建或保存 Webhook**，只接收两个 Secret ARN，并按 ARN 精确授予 `secretsmanager:GetSecretValue`：

- `kiro/monthly-report/feishu-bot-dev`
- `kiro/monthly-report/feishu-bot-prod`

Secret JSON 支持：

```json
{"webhook":"https://open.feishu.cn/open-apis/bot/v2/hook/REDACTED","sign_secret":"REDACTED"}
```

也可用 `url` 替代 `webhook`，`sign_secret` 可省略。推荐通过 AWS Console 输入值；若使用 CLI，应从权限 `0600` 的临时 JSON 文件读取，避免写入 shell history：

```bash
umask 077
# 在本机安全编辑 /tmp/feishu-prod.json，内容使用上面的 JSON 结构
aws secretsmanager create-secret \
  --name kiro/monthly-report/feishu-bot-prod \
  --description "Production Feishu bot for Kiro monthly reports" \
  --secret-string file:///tmp/feishu-prod.json \
  --region us-east-1
rm -f /tmp/feishu-prod.json
```

禁止把 Webhook、签名密钥或 SecretString 写入 `config.yaml`、README、Git、CI 输出或普通日志。部署和验收只使用 ARN/`describe-secret`，不要调用会打印值的 `get-secret-value`。发送异常只返回异常类型，避免 URL 出现在日志或响应中。

### 配置、通道和主动开关

`config.example.yaml` 默认关闭通知；复制为 Git 忽略的 `config.yaml` 后再按环境填写。启用通知时，所选通道的 ARN 必填：

```yaml
monthly_report:
  feishu_dev_secret_arn: "开发 Secret ARN"
  feishu_prod_secret_arn: "生产 Secret ARN"
  final_notification_enabled: true
  final_notification_channel: "prod"  # dev / prod / both
```

| 通道 | 行为 |
|------|------|
| `dev` | 只读取开发 Secret；未配置时返回业务错误，不尝试生产通道 |
| `prod` | 只读取生产 Secret；未配置/无权限/发送失败时绝不回退开发通道 |
| `both` | 固定先 dev 后 prod，顺序发送、非事务、无回滚，可出现部分成功 |

`both` 下如果两个 ARN 都配置且相同，运行时会对两个通道返回 `Feishu notification configuration error`，且一个 Webhook 也不会调用。如果前一个通道成功、后一个通道未配置或失败，前一个通知不会撤回。单通道模式不会比较 dev/prod ARN，因此部署前必须人工确认两个 ARN 不同；`deploy.sh` 会校验所选通道 ARN 非空，但当前不会比较 ARN 是否相同。

直接使用 CloudFormation 模板时，其参数默认仍是 Final `true/dev`；不要依赖默认值。推荐始终通过 `deploy.sh` 显式传入本地配置，并在完整部署前对比 AWS 当前参数，防止生产通道被旧的本地配置覆盖。

### Lambda 事件契约

| 字段 | 必填 | 规则 |
|------|------|------|
| `month` | 否 | 严格 `YYYY-MM`；提供后直接选择该月，`report_type` 默认 `final` |
| `time` | 计划任务应提供 | 未提供 `month` 时，使用事件时间所在月份减一；两者都没有才使用 Lambda 当前 UTC |
| `report_type` | 否 | 仅 `provisional` / `final` |
| `notify` | 否 | 默认 `false`；规范调用使用 JSON boolean。代码还兼容 `0/1`、`yes/no`、`on/off` 字符串 |
| `notification_channel` | `notify=true` 时有效 | `dev` / `prod` / `both`，省略时默认 `dev` |
| `backfill` | 否 | 回填脚本附带的审计元数据；handler 不读取，不改变行为 |

规范事件示例：

```json
{"month":"2026-08","report_type":"final","notify":false}
{"month":"2026-08","report_type":"final","notify":true,"notification_channel":"dev"}
{"time":"2026-09-02T06:00:00Z","report_type":"final","notify":true,"notification_channel":"prod"}
```

`report_type=provisional` 本身不会强制静默；如果手动显式传入 `notify=true`，函数仍会尝试通知。生产 Provisional 静默由 EventBridge 输入中的 `notify=false` 保证。

### Lambda 响应与成功判定

handler 返回：`month`、`report_type`、`status`、`users`、`report_url`、`notification_attempted`、`notification_channels`、`notification_results`、`notification_error`、`warning`。

```json
{
  "month": "2026-08",
  "report_type": "final",
  "status": "COMPLETE",
  "users": 32,
  "report_url": "https://example.invalid/report.xlsx",
  "notification_attempted": true,
  "notification_channels": ["prod"],
  "notification_results": {"prod": null},
  "notification_error": null,
  "warning": ""
}
```

- 报告生成成功：AWS Invoke 没有 `FunctionError`，响应包含 `report_url`，且对应 S3 对象存在。
- 通知成功：`notification_attempted=true`、目标通道在 `notification_channels` 中、`notification_results.<channel> == null`，并且 `notification_error == null`。
- `notification_attempted` 只表示事件请求发送，不代表飞书已成功接受。
- 通知失败通常被捕获为 `notification_results` 字符串和聚合后的 `notification_error`，Lambda 仍正常返回，**不会产生 `FunctionError`**，也通常不会触发 EventBridge/Lambda 失败重试。
- 报告文件先于通知写入；飞书失败不会回滚 S3 文件。
- `warning` 可能说明 2026-02 部分数据、当前月部分快照或历史订阅名册不可重建。

### 手动执行与历史回填

手动执行默认不通知。测试开发机器人必须显式打开通知；生产和双通道必须明确指定：

```bash
aws lambda invoke --function-name kiro-monthly-credits-report \
  --cli-binary-format raw-in-base64-out \
  --payload '{"month":"2026-08","report_type":"final","notify":true,"notification_channel":"dev"}' \
  /tmp/monthly-result.json
cat /tmp/monthly-result.json
```

同步回填脚本默认从 2026-02 到最后一个已关闭自然月，逐月调用：

```bash
python3 scripts/backfill_monthly_reports.py
python3 scripts/backfill_monthly_reports.py --start 2026-02 --end 2026-07
python3 scripts/backfill_monthly_reports.py --include-current-partial
python3 scripts/backfill_monthly_reports.py --start 2026-07 --end 2026-07 --notify --notification-channel dev
python3 scripts/backfill_monthly_reports.py --start 2026-07 --end 2026-07 --notify --notification-channel prod
```

脚本会在 AWS Invoke 顶层 `FunctionError` 时停止，但当前不会解析响应体中的 `notification_error`。启用通知的回填必须逐月检查打印出的 `notification_results`/`notification_error`，不能只看进程退出码。部署不会自动回填；可通过 `--profile`/`--region` 指定 boto3 会话。

### 部署、切换、轮换与回滚

1. 运维人员先独立创建 dev/prod Secret；CloudFormation 不创建 Secret。
2. 将两个 ARN 和明确的通知开关/通道写入本地 `config.yaml`；确认 dev/prod ARN 不同。
3. 运行完整 `./deploy.sh`，或先创建 CloudFormation no-execute change set。Secret ARN 变化必须同时更新 IAM policy 和 Lambda environment，不能只手工改 Lambda 环境变量。
4. 审查变更只涉及预期月报资源后再执行，并完成下方只读验收。
5. 观察至少一个调度周期后，再考虑退役旧 Secret；删除 Secret 时使用恢复窗口，不立即永久删除。

同 ARN 轮换可直接更新 Secret 版本并移动 `AWSCURRENT`。若 ARN 改变，必须重新部署 stack。版本回滚是恢复旧版本为 `AWSCURRENT`；ARN 回滚是把旧 ARN 写回配置并重新部署，以同步 IAM 和环境变量。

快速止损：将 `final_notification_enabled` 改为 `false` 后部署。切回开发：保持 enabled 为 `true`，将 channel 改为 `dev` 后部署。两种回滚都不需要删除生产 Secret。

### 部署后只读验收（不发送消息）

以下命令不会读取 SecretString，也不会触发通知：

```bash
REGION=us-east-1
aws cloudformation describe-stacks --stack-name kiro-analytics-stack --region "$REGION" \
  --query 'Stacks[0].{Status:StackStatus,Params:Parameters[?starts_with(ParameterKey, `MonthlyFinalNotification`)]}'
aws events describe-rule --name kiro-monthly-credits-final --region "$REGION"
aws events list-targets-by-rule --rule kiro-monthly-credits-final --region "$REGION"
aws events describe-rule --name kiro-monthly-credits-provisional --region "$REGION"
aws events list-targets-by-rule --rule kiro-monthly-credits-provisional --region "$REGION"
aws lambda get-function-configuration --function-name kiro-monthly-credits-report --region "$REGION" \
  --query '{State:State,Update:LastUpdateStatus,Dev:Environment.Variables.FEISHU_DEV_SECRET_ARN,Prod:Environment.Variables.FEISHU_PROD_SECRET_ARN}'
aws secretsmanager describe-secret --secret-id kiro/monthly-report/feishu-bot-dev --region "$REGION"
aws secretsmanager describe-secret --secret-id kiro/monthly-report/feishu-bot-prod --region "$REGION"
```

期望：stack `UPDATE_COMPLETE`；Final `ENABLED` 且 InputTemplate 与预期 channel 一致；Provisional `ENABLED` 且 `notify=false`；Lambda `Active/Successful`；两个 Secret 元数据存在。生产端到端投递和客户端渲染只有在明确发送验证消息后才能认定为已验证。

### 故障排查

| 现象 | 检查位置 | 行为/处理 |
|------|----------|-----------|
| `FunctionError` | Lambda invoke 元数据、CloudWatch | 报告执行失败；检查 Athena、S3、IIC、超时和堆栈，修复后重跑 |
| Secret 未配置 | `notification_results` | 返回 channel not configured；不回退其他通道，S3 报告通常已生成 |
| Secrets Manager `AccessDenied` | IAM policy、Lambda env、`notification_error` | 确认 ARN 同时存在于 IAM 与环境变量；ARN 变化后重新部署 stack |
| dev/prod ARN 相同且 channel=`both` | `notification_results` | 两边均 configuration error，零次 Webhook 调用；改为两个不同 ARN |
| 飞书 HTTP/API 拒绝或网络失败 | `notification_results`、CloudWatch | 只返回异常类型以防泄密；报告不回滚，确认机器人配置后按需重发 |
| `both` 部分成功 | 每个 channel 的 result | 非事务；成功的一边不会撤回，只重试失败通道时应改成单通道 |
| Card 超限/旧客户端异常 | 飞书响应、实际客户端 | S3 报告仍可用；核对人数/文本长度和 7.20+ 客户端，必要时只发报告链接 |
| 有报告但群里无消息 | S3、响应 JSON、EventBridge target | 不要只看 `FunctionError`；核对 `notification_attempted/results/error` 和实际 channel |

### 本地测试与验证边界

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
python3 -m unittest tests.test_monthly_report -v
python3 -m py_compile lambda/monthly_report/index.py tests/test_monthly_report.py \
  scripts/backfill_monthly_reports.py scripts/sync_user_mapping.py
bash -n deploy.sh
cfn-lint infrastructure/cloudformation.yaml
git diff --check
```

当前回归套件覆盖月份选择、套餐优先级、Excel/OOXML、负数环比、历史身份、Card 2.0 布局/预算、dev/prod/both 路由、缺失 Secret 不回退、同 ARN 的 `both` 拒绝和 CloudFormation 参数契约。它不覆盖真实 AWS 部署状态、生产 Webhook 投递、飞书客户端渲染，也不保证未来任意人数/文本长度都低于 payload 字节限制；这些必须通过部署后只读验收和受控的人工端到端验证补充。

## License

This project is licensed under the [MIT License](LICENSE).
