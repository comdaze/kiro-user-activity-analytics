# Kiro User Activity Analytics

Kiro 企业版用户活动数据分析平台。自动采集 S3 中的用户报告数据，通过 AWS Glue + Athena 构建数据湖，在 QuickSight 中展示综合仪表板，帮助管理员了解团队的 Kiro 使用情况和 Credit 消耗。

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
└──────────┬──────────────────────────────────┬───────────────────────────┘
           │                                  │
           ▼                                  ▼
┌─────────────────────┐            ┌─────────────────────────┐
│  Glue Crawler x2    │            │  Lambda Function        │
│  每天 UTC 2:00      │            │  每天 UTC 3:00          │
│  ├─ analytic crawler │            │  查询 Athena userid     │
│  └─ user_report     │            │  → Identity Center API  │
│     crawler         │            │  → 生成 user_mapping.csv│
└────────┬────────────┘            └────────┬────────────────┘
         │ 自动建表/更新 schema               │
         ▼                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Glue Data Catalog (kiro_analytics)                                     │
│  ├── by_user_analytic   行为明细表                                       │
│  ├── user_report        Credit 汇总表                                   │
│  └── user_mapping       用户名映射表                                     │
└──────────┬──────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Athena (kiro-analytics-workgroup)                                      │
│  ├── 直接查询 Glue 表                                                   │
│  └── SQL 视图 (汇总统计)                                                │
└──────────┬──────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  QuickSight                                                             │
│  ├── Data Source: Athena 连接                                           │
│  ├── Datasets x2:                                                       │
│  │   ├── activity dataset (by_user_analytic LEFT JOIN user_mapping)     │
│  │   └── credits dataset  (user_report LEFT JOIN user_mapping)          │
│  ├── Analysis: Kiro 综合分析 (可在控制台编辑)                             │
│  └── Dashboard: Kiro 综合仪表板 (只读发布版)                              │
│      ├── Sheet 1: 概览                                                  │
│      ├── Sheet 2: 用户行为                                              │
│      └── Sheet 3: 成本分析                                              │
└─────────────────────────────────────────────────────────────────────────┘
```

## 仪表板内容

综合仪表板包含 3 个 Sheet：

| Sheet | 数据集 | 包含图表 |
|-------|--------|---------|
| 概览 | credits | 活跃用户数 KPI、Credit 消耗 KPI、超额 Credit KPI、总消息数 KPI、每日 Credit 趋势折线图、Top 10 用户柱状图、订阅层级分布 |
| 用户行为 | activity | AI 代码行数 KPI、Inline 代码行数 KPI、Chat 消息数 KPI、代码生成趋势折线图、Inline 接受趋势折线图、Top 10 代码用户柱状图 |
| 成本分析 | credits | 每日超额趋势折线图、各层级平均消耗柱状图、用户 Credit 使用明细表 |


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
- **QuickSight S3 权限（重要！！）**）: 在 QuickSight Console → Manage QuickSight → Security & permissions → S3 中，勾选报告所在的 S3 bucket，并启用 "Write permission for Athena Workgroup"
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
  crawlers:
    analytic:
      name: "kiro-analytic-crawler"  # 行为数据 Crawler 名称
      table_name: "by_user_analytic" # 行为数据表名
    user_report:
      name: "kiro-user-report-crawler"  # Credit 数据 Crawler 名称
      table_name: "user_report"         # Credit 数据表名

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
| 1️⃣ | 部署 CloudFormation 基础设施 | `infrastructure/cloudformation.yaml` |
| 2️⃣ | 配置 Lake Formation 权限（6 个 Principal） | deploy.sh 内置 |
| 3️⃣ | 运行 Glue Crawlers 并等待完成 | Glue Crawlers |
| 4️⃣ | 验证 Athena 数据查询 | Athena |
| 5️⃣ | 创建 Athena SQL 视图 | `scripts/create_views.py` |
| 6️⃣ | 同步用户名映射 | `scripts/sync_user_mapping.py` |
| 7️⃣ | 部署 QuickSight 数据源和数据集 | `scripts/create_datasets.py` |
| 8️⃣ | 发布综合仪表板和分析 | `scripts/create_dashboard_publish.py` |

### Lake Formation 权限

项目自动为以下 6 个 Principal 配置 Lake Formation 权限：

| Principal | 权限 | 用途 |
|-----------|------|------|
| Glue Crawler Role | CREATE_TABLE, ALTER, DROP, ALL | 爬取 S3 数据建表 |
| 当前 IAM 用户/角色 | SELECT, DESCRIBE | Athena 手动查询 |
| QuickSight Service Role | SELECT, DESCRIBE | QuickSight 读取数据 |
| QuickSight 用户 IAM 角色 | SELECT, DESCRIBE | QuickSight 用户访问 |
| Lambda Role | SELECT, DESCRIBE, ALTER, CREATE_TABLE | 用户映射同步 |
| IAMAllowedPrincipals | ALL | 兼容 IAM 模式访问 |


## 项目结构

```
kiro-user-activity-analytics/
├── config.yaml                      # 项目配置（包含账户信息，不提交 Git）
├── config.example.yaml              # 配置模板
├── deploy.sh                        # 端到端部署脚本
├── requirements.txt                 # Python 依赖
├── infrastructure/
│   └── cloudformation.yaml          # AWS 基础设施定义
│                                    #   - Glue Database + Crawlers x2
│                                    #   - Athena Workgroup
│                                    #   - Lambda 用户映射同步函数
│                                    #   - EventBridge 定时规则
├── scripts/
│   ├── create_views.py              # 创建 Athena SQL 视图
│   ├── sync_user_mapping.py         # 同步 userid → 用户名映射
│   ├── create_datasets.py           # 创建 QuickSight 数据源和数据集
│   └── create_dashboard_publish.py  # 创建并发布综合仪表板和分析
└── sql/
    └── create_views.sql             # Athena 视图 SQL 定义
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

S3 报告中的 `userid` 是 IAM Identity Center 的 UUID（如 `24681498-20e1-7057-3818-19d6b7a2f397`），不便于识别。项目通过以下机制自动映射为可读的用户名：

1. **Lambda 函数** (`kiro-user-mapping-sync`) 每天 UTC 3:00 自动运行
2. 从 Athena 查询所有不重复的 `userid`
3. 调用 IAM Identity Center `DescribeUser` API 获取 `DisplayName`
4. 生成映射 CSV 上传到 `s3://<bucket>/user-mapping/user_mapping.csv`
5. 创建/更新 Glue 外部表 `user_mapping`
6. QuickSight 数据集通过 `LEFT JOIN` 关联映射表，图表中直接显示用户名

手动触发同步：
```bash
# 本地运行
python3 scripts/sync_user_mapping.py

# 或通过 Lambda
aws lambda invoke --function-name kiro-user-mapping-sync /tmp/out.json && cat /tmp/out.json
```

## 常用操作

### 仅更新仪表板（不重建基础设施）

```bash
python3 scripts/create_datasets.py
python3 scripts/create_dashboard_publish.py
```

### 手动触发 Crawler 抓取最新数据

```bash
aws glue start-crawler --name kiro-analytic-crawler
aws glue start-crawler --name kiro-user-report-crawler
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
SELECT date, userid, client_type, credits_used
FROM kiro_analytics.user_report
WHERE date >= date_format(date_add('day', -7, current_date), '%Y-%m-%d')
ORDER BY date DESC;

-- 查看每个用户的总代码生成量
SELECT userid, 
       SUM(chat_aicodelines) as chat_code,
       SUM(inline_aicodelines) as inline_code
FROM kiro_analytics.by_user_analytic
GROUP BY userid;
```

## 故障排查

| 问题 | 解决方案 |
|------|---------|
| Athena 查询报 `AccessDeniedException` | 检查 Lake Formation 权限，重新运行 `deploy.sh` 的第 2 步 |
| Crawler 运行失败 | 检查 S3 桶策略是否允许 Glue Crawler Role 访问 |
| QuickSight 报 `SQL exception` | 确认 QuickSight 已授权访问 S3 bucket（Manage QuickSight → Security & permissions → S3），并确认当前用户是 Lake Formation Data Lake Admin |
| QuickSight 数据源 `CREATION_FAILED` | 通常是 S3 权限问题，在 QuickSight Console 授权 S3 后删除数据源重建：`sh deploy.sh --from-step 7` |
| 用户名显示为 UUID | 运行 `python3 scripts/sync_user_mapping.py` 手动同步映射 |
| 仪表板图表为空 | 检查 Athena 表是否有数据：`SELECT COUNT(*) FROM kiro_analytics.user_report` |
| S3 没有新数据 | 报告有 1-2 天延迟，确认 Kiro User Activity Report 已开启 |
| CloudFormation 部署报 `ROLLBACK_COMPLETE` | deploy.sh 会自动处理，删除旧 stack 后重建 |

## License

This project is licensed under the [MIT License](LICENSE).
