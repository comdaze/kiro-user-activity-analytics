#!/bin/bash
set -e

echo "🚀 开始部署 Kiro User Activity Analytics"
echo ""

# ============================================
# 前置检查
# ============================================
if [ ! -f "config.yaml" ]; then
    echo "❌ 配置文件不存在，请先复制 config.example.yaml 为 config.yaml 并填写配置"
    exit 1
fi

command -v aws >/dev/null 2>&1 || { echo "❌ 需要安装 AWS CLI"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "❌ 需要安装 Python3"; exit 1; }

# 读取配置
REGION=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c['aws']['region'])")
ACCOUNT_ID=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c['aws']['account_id'])")
BUCKET=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c['s3']['bucket_name'])")
PREFIX=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c['s3']['prefix'])")
IDENTITY_STORE_ID=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c['identity_center']['identity_store_id'])")
STACK_NAME="kiro-analytics-stack"
WORKGROUP="kiro-analytics-workgroup"
GLUE_DB="kiro_analytics"
QS_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/service-role/aws-quicksight-service-role-v0"
QS_USER_ARN=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c['quicksight']['user_arn'])")

echo "📋 配置信息:"
echo "  Region:    $REGION"
echo "  Account:   $ACCOUNT_ID"
echo "  S3 Bucket: $BUCKET"
echo "  S3 Prefix: $PREFIX"
echo ""

# ============================================
# 1. 部署 CloudFormation
# ============================================
echo "1️⃣  部署基础设施 (CloudFormation)..."
aws cloudformation deploy \
    --template-file infrastructure/cloudformation.yaml \
    --stack-name $STACK_NAME \
    --parameter-overrides \
        S3BucketName=$BUCKET \
        S3Prefix=$PREFIX \
        IdentityStoreId=$IDENTITY_STORE_ID \
    --capabilities CAPABILITY_IAM \
    --region $REGION \
    --no-fail-on-empty-changeset

echo "✓ CloudFormation 部署完成"
echo ""

# ============================================
# 2. 配置 Lake Formation 权限
# ============================================
echo "2️⃣  配置 Lake Formation 权限..."

CRAWLER_ROLE_NAME=$(aws cloudformation describe-stack-resource \
    --stack-name $STACK_NAME \
    --logical-resource-id GlueCrawlerRole \
    --region $REGION \
    --query 'StackResourceDetail.PhysicalResourceId' --output text)
CRAWLER_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${CRAWLER_ROLE_NAME}"
CALLER_ARN=$(aws sts get-caller-identity --query 'Arn' --output text)

grant_lf() {
    local PRINCIPAL=$1
    local RESOURCE=$2
    local PERMS=$3
    local DESC=$4
    aws lakeformation grant-permissions \
        --principal "DataLakePrincipalIdentifier=$PRINCIPAL" \
        --resource "$RESOURCE" \
        --permissions $PERMS \
        --region $REGION 2>/dev/null && echo "  ✓ $DESC" || echo "  ✓ $DESC (已存在)"
}

# Crawler: 建表权限
grant_lf "$CRAWLER_ROLE_ARN" \
    "{\"Database\":{\"Name\":\"$GLUE_DB\"}}" \
    "CREATE_TABLE ALTER DROP" \
    "Crawler 数据库权限"

grant_lf "$CRAWLER_ROLE_ARN" \
    "{\"Table\":{\"DatabaseName\":\"$GLUE_DB\",\"TableWildcard\":{}}}" \
    "ALL" \
    "Crawler 表权限"

# 当前用户: Athena 查询权限
grant_lf "$CALLER_ARN" \
    "{\"Table\":{\"DatabaseName\":\"$GLUE_DB\",\"TableWildcard\":{}}}" \
    "SELECT DESCRIBE" \
    "当前用户查询权限"

# QuickSight: 读取权限
grant_lf "$QS_ROLE_ARN" \
    "{\"Database\":{\"Name\":\"$GLUE_DB\"}}" \
    "DESCRIBE" \
    "QuickSight 数据库权限"

grant_lf "$QS_ROLE_ARN" \
    "{\"Table\":{\"DatabaseName\":\"$GLUE_DB\",\"TableWildcard\":{}}}" \
    "SELECT DESCRIBE" \
    "QuickSight 表权限"

# QuickSight 用户 IAM 角色: 从 user_arn 中提取角色名并授权
QS_IAM_ROLE=$(python3 -c "
arn = '$QS_USER_ARN'
# arn:aws:quicksight:region:account:user/default/role_name/username
parts = arn.split('/')
if len(parts) >= 3:
    print('arn:aws:iam::$ACCOUNT_ID:role/' + parts[-2])
else:
    print('')
")
if [ -n "$QS_IAM_ROLE" ]; then
    grant_lf "$QS_IAM_ROLE" \
        "{\"Database\":{\"Name\":\"$GLUE_DB\"}}" \
        "DESCRIBE" \
        "QuickSight 用户角色数据库权限"

    grant_lf "$QS_IAM_ROLE" \
        "{\"Table\":{\"DatabaseName\":\"$GLUE_DB\",\"TableWildcard\":{}}}" \
        "SELECT DESCRIBE" \
        "QuickSight 用户角色表权限"
fi

# IAMAllowedPrincipals: 回退到 IAM 模式，确保所有有 IAM 权限的角色都能访问
grant_lf "IAM_ALLOWED_PRINCIPALS" \
    "{\"Database\":{\"Name\":\"$GLUE_DB\"}}" \
    "ALL" \
    "IAMAllowedPrincipals 数据库权限"

grant_lf "IAM_ALLOWED_PRINCIPALS" \
    "{\"Table\":{\"DatabaseName\":\"$GLUE_DB\",\"TableWildcard\":{}}}" \
    "ALL" \
    "IAMAllowedPrincipals 表权限"

# Lambda 用户映射同步: 查询和建表权限
LAMBDA_ROLE_FULL_ARN=$(aws lambda get-function-configuration \
    --function-name kiro-user-mapping-sync \
    --query 'Role' --output text --region $REGION 2>/dev/null || echo "")
if [ -n "$LAMBDA_ROLE_FULL_ARN" ] && [ "$LAMBDA_ROLE_FULL_ARN" != "None" ]; then
    grant_lf "$LAMBDA_ROLE_FULL_ARN" \
        "{\"Database\":{\"Name\":\"$GLUE_DB\"}}" \
        "CREATE_TABLE ALTER DESCRIBE" \
        "Lambda 数据库权限"
    grant_lf "$LAMBDA_ROLE_FULL_ARN" \
        "{\"Table\":{\"DatabaseName\":\"$GLUE_DB\",\"TableWildcard\":{}}}" \
        "SELECT DESCRIBE ALTER" \
        "Lambda 表权限"
fi

echo "✓ Lake Formation 权限配置完成"
echo ""

# ============================================
# 3. 运行 Glue Crawlers
# ============================================
echo "3️⃣  运行 Glue Crawlers..."

CRAWLER_ANALYTIC=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --query 'Stacks[0].Outputs[?OutputKey==`GlueCrawlerAnalyticName`].OutputValue' \
    --output text --region $REGION)

CRAWLER_USER_REPORT=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --query 'Stacks[0].Outputs[?OutputKey==`GlueCrawlerUserReportName`].OutputValue' \
    --output text --region $REGION)

aws glue start-crawler --name $CRAWLER_ANALYTIC --region $REGION 2>/dev/null || true
aws glue start-crawler --name $CRAWLER_USER_REPORT --region $REGION 2>/dev/null || true

echo "  等待 Crawlers 完成..."
for CRAWLER in $CRAWLER_ANALYTIC $CRAWLER_USER_REPORT; do
    while true; do
        STATE=$(aws glue get-crawler --name $CRAWLER --region $REGION \
            --query 'Crawler.State' --output text)
        if [ "$STATE" = "READY" ]; then
            STATUS=$(aws glue get-crawler --name $CRAWLER --region $REGION \
                --query 'Crawler.LastCrawl.Status' --output text)
            if [ "$STATUS" = "SUCCEEDED" ]; then
                echo "  ✓ $CRAWLER 完成"
            else
                echo "  ✗ $CRAWLER 失败:"
                aws glue get-crawler --name $CRAWLER --region $REGION \
                    --query 'Crawler.LastCrawl.ErrorMessage' --output text
                exit 1
            fi
            break
        fi
        sleep 10
    done
done

echo "✓ Crawlers 全部完成"
echo ""

# ============================================
# 4. 验证 Athena 数据查询
# ============================================
echo "4️⃣  验证 Athena 数据查询..."

python3 -c "
import boto3, time, sys
athena = boto3.client('athena', region_name='$REGION')
tables = ['by_user_analytic', 'user_report']
ok = True
for t in tables:
    r = athena.start_query_execution(
        QueryString=f'SELECT COUNT(*) FROM kiro_analytics.{t}',
        WorkGroup='$WORKGROUP')
    qid = r['QueryExecutionId']
    while True:
        s = athena.get_query_execution(QueryExecutionId=qid)['QueryExecution']['Status']['State']
        if s == 'SUCCEEDED':
            cnt = athena.get_query_results(QueryExecutionId=qid)['ResultSet']['Rows'][1]['Data'][0]['VarCharValue']
            print(f'  ✓ {t}: {cnt} 条记录')
            break
        elif s == 'FAILED':
            reason = athena.get_query_execution(QueryExecutionId=qid)['QueryExecution']['Status'].get('StateChangeReason','')
            print(f'  ✗ {t}: {reason}')
            ok = False
            break
        time.sleep(2)
if not ok:
    sys.exit(1)
"

echo "✓ 数据验证通过"
echo ""

# ============================================
# 5. 创建 Athena 视图
# ============================================
echo "5️⃣  创建 Athena 视图..."
python3 scripts/create_views.py
echo ""

# ============================================
# 6. 同步用户映射 (Identity Center → S3 → Athena)
# ============================================
echo "6️⃣  同步用户名映射..."
python3 scripts/sync_user_mapping.py
echo ""

# ============================================
# 7. 部署 QuickSight 数据源和数据集
# ============================================
echo "7️⃣  部署 QuickSight 数据源和数据集..."
python3 scripts/create_dashboards.py
echo ""

# ============================================
# 8. 部署 QuickSight 可视化分析
# ============================================
echo "8️⃣  部署 QuickSight 可视化分析..."
python3 scripts/create_visuals.py
echo ""

# ============================================
# 9. 发布 QuickSight Dashboard
# ============================================
echo "9️⃣  发布 QuickSight Dashboard..."
python3 scripts/create_dashboard_publish.py
echo ""

# ============================================
# 完成
# ============================================
echo "✅ 端到端部署完成！"
echo ""
echo "📊 访问 QuickSight 控制台查看仪表板:"
echo "   https://$REGION.quicksight.aws.amazon.com/"
echo ""
