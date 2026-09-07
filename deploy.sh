#!/bin/bash
set -e

# 支持 --from-step N 从第 N 步开始执行
FROM_STEP=1
while [[ $# -gt 0 ]]; do
    case $1 in
        --from-step) FROM_STEP=$2; shift 2;;
        *) echo "用法: $0 [--from-step N]  (N=1~8)"; exit 1;;
    esac
done

echo "🚀 开始部署 Kiro User Activity Analytics"
if [ "$FROM_STEP" -gt 1 ]; then
    echo "  ⏩ 从第 ${FROM_STEP} 步开始"
fi
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
DASHBOARD_ID=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c['quicksight'].get('dashboard_id','kiro-comprehensive-dashboard'))")
REPORT_EMAIL=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c.get('report',{}).get('email',''))")
REPORT_SCHEDULE=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c.get('report',{}).get('schedule','cron(0 5 * * ? *)'))")
REPORT_BUCKET=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c['report']['bucket'])")
MONTHLY_KIRO_APPLICATION_ARN=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c.get('monthly_report',{}).get('kiro_application_arn',''))")
MONTHLY_SUBSCRIPTION_CSV_KEY=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c.get('monthly_report',{}).get('subscription_csv_key',''))")
MONTHLY_FEISHU_DEV_SECRET_ARN=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c.get('monthly_report',{}).get('feishu_dev_secret_arn',''))")
MONTHLY_FEISHU_PROD_SECRET_ARN=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c.get('monthly_report',{}).get('feishu_prod_secret_arn',''))")
MONTHLY_FINAL_NOTIFICATION_ENABLED=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(str(c.get('monthly_report',{}).get('final_notification_enabled',True)).lower())")
MONTHLY_FINAL_NOTIFICATION_CHANNEL=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c.get('monthly_report',{}).get('final_notification_channel','dev'))")
MONTHLY_OUTPUT_PREFIX=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c.get('monthly_report',{}).get('output_prefix','dashboard-reports/public/kiro-monthly'))")
MONTHLY_PROVISIONAL_SCHEDULE=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c.get('monthly_report',{}).get('provisional_schedule','cron(0 6 1 * ? *)'))")
MONTHLY_FINAL_SCHEDULE=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c.get('monthly_report',{}).get('final_schedule','cron(0 6 2 * ? *)'))")
AWS_PROFILE=${AWS_PROFILE:-default}
export AWS_PROFILE

echo "📋 配置信息:"
if [ -z "$MONTHLY_SUBSCRIPTION_CSV_KEY" ] && [ -z "$MONTHLY_KIRO_APPLICATION_ARN" ]; then
    echo "❌ monthly_report 必须配置 subscription_csv_key 或 kiro_application_arn"
    exit 1
fi
case "$MONTHLY_FINAL_NOTIFICATION_ENABLED" in true|false) ;; *)
    echo "❌ final_notification_enabled 必须为 true 或 false"; exit 1 ;;
esac
case "$MONTHLY_FINAL_NOTIFICATION_CHANNEL" in dev|prod|both) ;; *)
    echo "❌ final_notification_channel 必须为 dev、prod 或 both"; exit 1 ;;
esac
if [ "$MONTHLY_FINAL_NOTIFICATION_ENABLED" = "true" ]; then
    if { [ "$MONTHLY_FINAL_NOTIFICATION_CHANNEL" = "dev" ] || [ "$MONTHLY_FINAL_NOTIFICATION_CHANNEL" = "both" ]; } && [ -z "$MONTHLY_FEISHU_DEV_SECRET_ARN" ]; then
        echo "❌ 已启用开发通道通知，但 feishu_dev_secret_arn 未配置"; exit 1
    fi
    if { [ "$MONTHLY_FINAL_NOTIFICATION_CHANNEL" = "prod" ] || [ "$MONTHLY_FINAL_NOTIFICATION_CHANNEL" = "both" ]; } && [ -z "$MONTHLY_FEISHU_PROD_SECRET_ARN" ]; then
        echo "❌ 已启用生产通道通知，但 feishu_prod_secret_arn 未配置（不会回退开发通道）"; exit 1
    fi
fi
echo "  Region:    $REGION"
echo "  Account:   $ACCOUNT_ID"
echo "  S3 Bucket: $BUCKET"
echo "  S3 Prefix: $PREFIX"
echo "  CLI Porfile: $AWS_PROFILE"
echo ""

# ============================================
# 1. 部署 CloudFormation
# ============================================
if [ "$FROM_STEP" -le 1 ]; then
echo "1️⃣  部署基础设施 (CloudFormation)..."

# Build the monthly Lambda as an immutable artifact before CloudFormation deploy.
MONTHLY_BUILD_DIR=$(mktemp -d "${TMPDIR:-/tmp}/kiro-monthly.XXXXXX")
MONTHLY_ZIP_PATH="${MONTHLY_BUILD_DIR}.zip"
cleanup_monthly_build() { rm -rf "$MONTHLY_BUILD_DIR" "$MONTHLY_ZIP_PATH"; }
trap cleanup_monthly_build EXIT
python3 -m pip install --disable-pip-version-check --no-compile \
    --requirement lambda/monthly_report/requirements.txt \
    --target "$MONTHLY_BUILD_DIR" >/dev/null
cp lambda/monthly_report/index.py "$MONTHLY_BUILD_DIR/index.py"
PYTHONPATH="$MONTHLY_BUILD_DIR" python3 -c "import index; assert callable(index.handler); print('  ✓ monthly package smoke import')"
(
    cd "$MONTHLY_BUILD_DIR"
    find . -type f -name '*.pyc' -delete
    find . -type f -print | LC_ALL=C sort | zip -q -X "$MONTHLY_ZIP_PATH" -@
)
if command -v shasum >/dev/null 2>&1; then
    MONTHLY_ARTIFACT_HASH=$(shasum -a 256 "$MONTHLY_ZIP_PATH" | awk '{print $1}')
else
    MONTHLY_ARTIFACT_HASH=$(python3 -c "import hashlib; print(hashlib.sha256(open('$MONTHLY_ZIP_PATH','rb').read()).hexdigest())")
fi
MONTHLY_ARTIFACT_KEY="artifacts/monthly-report/${MONTHLY_ARTIFACT_HASH}.zip"
aws s3api put-object --bucket "$BUCKET" --key "$MONTHLY_ARTIFACT_KEY" \
    --body "$MONTHLY_ZIP_PATH" --server-side-encryption AES256 \
    --content-type application/zip --region "$REGION" >/dev/null
echo "  ✓ monthly artifact uploaded: s3://${BUCKET}/${MONTHLY_ARTIFACT_KEY}"

# 检查 stack 是否处于 ROLLBACK_COMPLETE 等不可更新状态，自动清理
STACK_STATUS=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "NOT_FOUND")

if [ "$STACK_STATUS" = "ROLLBACK_COMPLETE" ] || [ "$STACK_STATUS" = "DELETE_FAILED" ]; then
    echo "  ⚠️  Stack 处于 $STACK_STATUS 状态，自动删除后重建..."
    aws cloudformation delete-stack --stack-name $STACK_NAME --region $REGION
    aws cloudformation wait stack-delete-complete --stack-name $STACK_NAME --region $REGION
    echo "  ✓ 旧 Stack 已删除"
fi

aws cloudformation deploy \
    --template-file infrastructure/cloudformation.yaml \
    --stack-name $STACK_NAME \
    --parameter-overrides \
        S3BucketName=$BUCKET \
        IdentityStoreId=$IDENTITY_STORE_ID \
        DashboardId=$DASHBOARD_ID \
        ReportEmail=$REPORT_EMAIL \
        ReportSchedule="$REPORT_SCHEDULE" \
        ReportBucket="$REPORT_BUCKET" \
        MonthlyArtifactBucket="$BUCKET" \
        MonthlyArtifactKey="$MONTHLY_ARTIFACT_KEY" \
        KiroApplicationArn="$MONTHLY_KIRO_APPLICATION_ARN" \
        SubscriptionCsvKey="$MONTHLY_SUBSCRIPTION_CSV_KEY" \
        FeishuDevSecretArn="$MONTHLY_FEISHU_DEV_SECRET_ARN" \
        FeishuProdSecretArn="$MONTHLY_FEISHU_PROD_SECRET_ARN" \
        MonthlyOutputPrefix="$MONTHLY_OUTPUT_PREFIX" \
        MonthlyProvisionalSchedule="$MONTHLY_PROVISIONAL_SCHEDULE" \
        MonthlyFinalSchedule="$MONTHLY_FINAL_SCHEDULE" \
        MonthlyFinalNotificationEnabled="$MONTHLY_FINAL_NOTIFICATION_ENABLED" \
        MonthlyFinalNotificationChannel="$MONTHLY_FINAL_NOTIFICATION_CHANNEL" \
    --capabilities CAPABILITY_IAM \
    --region $REGION \
    --no-fail-on-empty-changeset

echo "✓ CloudFormation 部署完成"

# 强制更新 Lambda 代码（CloudFormation 不检测 inline code 变更）
echo "  更新 Lambda 函数代码..."
python3 -c "
import yaml

# 添加 CloudFormation 标签支持
class CFLoader(yaml.SafeLoader): pass
for tag in ['!Ref','!Sub','!GetAtt','!Join','!Select','!Split','!If','!Equals','!Not','!And','!Or']:
    CFLoader.add_constructor(tag, lambda l,n: l.construct_scalar(n) if n.id=='scalar' else l.construct_sequence(n))
cf = yaml.load(open('infrastructure/cloudformation.yaml'), Loader=CFLoader)
code = cf['Resources']['UserMappingFunction']['Properties']['Code']['ZipFile']
with open('/tmp/index.py', 'w') as f:
    f.write(code)
"
cd /tmp && zip -q lambda_package.zip index.py
aws lambda update-function-code \
    --function-name kiro-user-mapping-sync \
    --zip-file fileb:///tmp/lambda_package.zip \
    --region $REGION > /dev/null
cd - > /dev/null
rm -f /tmp/index.py /tmp/lambda_package.zip
echo "  ✓ Lambda 代码已更新"

echo ""
fi # step 1

# ============================================
# 2. 配置 Lake Formation 权限
# ============================================

# Lake Formation 授权辅助函数
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

grant_lf_all_tables() {
    local PRINCIPAL=$1
    local PERMS=$2
    local DESC=$3
    for TABLE in by_user_analytic user_report user_mapping; do
        grant_lf "$PRINCIPAL" \
            "{\"Table\":{\"DatabaseName\":\"$GLUE_DB\",\"Name\":\"$TABLE\"}}" \
            "$PERMS" \
            "$DESC ($TABLE)"
    done
}

if [ "$FROM_STEP" -le 2 ]; then
echo "2️⃣  配置 Lake Formation 数据库权限..."

CALLER_ARN=$(aws sts get-caller-identity --query 'Arn' --output text)

# 当前用户: 数据库权限（建表需要）
grant_lf "$CALLER_ARN" \
    "{\"Database\":{\"Name\":\"$GLUE_DB\"}}" \
    "CREATE_TABLE ALTER DESCRIBE" \
    "当前用户数据库权限"

# QuickSight: 数据库权限
grant_lf "$QS_ROLE_ARN" \
    "{\"Database\":{\"Name\":\"$GLUE_DB\"}}" \
    "DESCRIBE" \
    "QuickSight 数据库权限"

# QuickSight 用户 IAM 角色: 数据库权限
QS_IAM_ROLE=$(python3 -c "
arn = '$QS_USER_ARN'
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
fi

# IAMAllowedPrincipals: 数据库权限
grant_lf "IAM_ALLOWED_PRINCIPALS" \
    "{\"Database\":{\"Name\":\"$GLUE_DB\"}}" \
    "ALL" \
    "IAMAllowedPrincipals 数据库权限"

# Lambda: 数据库权限
LAMBDA_ROLE_FULL_ARN=$(aws lambda get-function-configuration \
    --function-name kiro-user-mapping-sync \
    --query 'Role' --output text --region $REGION 2>/dev/null || echo "")
if [ -n "$LAMBDA_ROLE_FULL_ARN" ] && [ "$LAMBDA_ROLE_FULL_ARN" != "None" ]; then
    grant_lf "$LAMBDA_ROLE_FULL_ARN" \
        "{\"Database\":{\"Name\":\"$GLUE_DB\"}}" \
        "CREATE_TABLE ALTER DESCRIBE" \
        "Lambda 数据库权限"
fi

MONTHLY_ROLE_NAME=$(aws cloudformation describe-stack-resource \
    --stack-name "$STACK_NAME" --logical-resource-id MonthlyReportLambdaRole \
    --query 'StackResourceDetail.PhysicalResourceId' --output text --region "$REGION" 2>/dev/null || echo "")
if [ -n "$MONTHLY_ROLE_NAME" ] && [ "$MONTHLY_ROLE_NAME" != "None" ]; then
    MONTHLY_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${MONTHLY_ROLE_NAME}"
    grant_lf "$MONTHLY_ROLE_ARN" \
        "{\"Database\":{\"Name\":\"$GLUE_DB\"}}" \
        "DESCRIBE" \
        "月度报告 Lambda 数据库权限"
    grant_lf "$MONTHLY_ROLE_ARN" \
        "{\"Table\":{\"DatabaseName\":\"$GLUE_DB\",\"Name\":\"user_report\"}}" \
        "SELECT DESCRIBE" \
        "月度报告 Lambda user_report 读取权限"
fi

echo "✓ Lake Formation 数据库权限配置完成"
echo ""
fi # step 2

# ============================================
# 3. 通过 Glue API 创建外部表（替代 Glue Crawler）
# ============================================
if [ "$FROM_STEP" -le 3 ]; then
echo "3️⃣  通过 Glue API 创建外部表..."

python3 -c "
import boto3, yaml, sys

config = yaml.safe_load(open('config.yaml'))
region = config['aws']['region']
account_id = config['aws']['account_id']
bucket = config['s3']['bucket_name']
prefix = config['s3']['prefix']
glue_db = config['glue']['database_name']

glue = boto3.client('glue', region_name=region)

CSV_SERDE = {
    'SerializationLibrary': 'org.apache.hadoop.hive.serde2.OpenCSVSerde',
    'Parameters': {'separatorChar': ',', 'quoteChar': '\"', 'escapeChar': '\\\\'}
}
INPUT_FMT = 'org.apache.hadoop.mapred.TextInputFormat'
OUTPUT_FMT = 'org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat'

def create_table(name, columns, s3_path):
    table_input = {
        'Name': name,
        'StorageDescriptor': {
            'Columns': columns,
            'Location': s3_path,
            'InputFormat': INPUT_FMT,
            'OutputFormat': OUTPUT_FMT,
            'SerdeInfo': CSV_SERDE,
        },
        'TableType': 'EXTERNAL_TABLE',
        'Parameters': {'skip.header.line.count': '1', 'classification': 'csv'}
    }
    try:
        glue.create_table(DatabaseName=glue_db, TableInput=table_input)
        print(f'  ✓ {name} 表创建成功')
    except glue.exceptions.AlreadyExistsException:
        # 旧 Crawler 建的表可能带分区列，无法直接更新，先删后建
        try:
            glue.delete_table(DatabaseName=glue_db, Name=name)
            glue.create_table(DatabaseName=glue_db, TableInput=table_input)
            print(f'  ✓ {name} 表已重建（删除旧表并重新创建）')
        except Exception as e:
            print(f'  ✗ {name} 表重建失败: {e}')
            sys.exit(1)

# by_user_analytic 表 (按 CSV header 实际列顺序，OpenCSVSerde 全部为 string)
create_table('by_user_analytic', [
    {'Name': 'userid', 'Type': 'string'},
    {'Name': 'date', 'Type': 'string'},
    {'Name': 'chat_aicodelines', 'Type': 'string'},
    {'Name': 'chat_messagesinteracted', 'Type': 'string'},
    {'Name': 'chat_messagessent', 'Type': 'string'},
    {'Name': 'codefix_acceptanceeventcount', 'Type': 'string'},
    {'Name': 'codefix_acceptedlines', 'Type': 'string'},
    {'Name': 'codefix_generatedlines', 'Type': 'string'},
    {'Name': 'codefix_generationeventcount', 'Type': 'string'},
    {'Name': 'codereview_failedeventcount', 'Type': 'string'},
    {'Name': 'codereview_findingscount', 'Type': 'string'},
    {'Name': 'codereview_succeededeventcount', 'Type': 'string'},
    {'Name': 'dev_acceptanceeventcount', 'Type': 'string'},
    {'Name': 'dev_acceptedlines', 'Type': 'string'},
    {'Name': 'dev_generatedlines', 'Type': 'string'},
    {'Name': 'dev_generationeventcount', 'Type': 'string'},
    {'Name': 'docgeneration_acceptedfileupdates', 'Type': 'string'},
    {'Name': 'docgeneration_acceptedfilescreations', 'Type': 'string'},
    {'Name': 'docgeneration_acceptedlineadditions', 'Type': 'string'},
    {'Name': 'docgeneration_acceptedlineupdates', 'Type': 'string'},
    {'Name': 'docgeneration_eventcount', 'Type': 'string'},
    {'Name': 'docgeneration_rejectedfilecreations', 'Type': 'string'},
    {'Name': 'docgeneration_rejectedfileupdates', 'Type': 'string'},
    {'Name': 'docgeneration_rejectedlineadditions', 'Type': 'string'},
    {'Name': 'docgeneration_rejectedlineupdates', 'Type': 'string'},
    {'Name': 'inlinechat_acceptanceeventcount', 'Type': 'string'},
    {'Name': 'inlinechat_acceptedlineadditions', 'Type': 'string'},
    {'Name': 'inlinechat_acceptedlinedeletions', 'Type': 'string'},
    {'Name': 'inlinechat_dismissaleventcount', 'Type': 'string'},
    {'Name': 'inlinechat_dismissedlineadditions', 'Type': 'string'},
    {'Name': 'inlinechat_dismissedlinedeletions', 'Type': 'string'},
    {'Name': 'inlinechat_rejectedlineadditions', 'Type': 'string'},
    {'Name': 'inlinechat_rejectedlinedeletions', 'Type': 'string'},
    {'Name': 'inlinechat_rejectioneventcount', 'Type': 'string'},
    {'Name': 'inlinechat_totaleventcount', 'Type': 'string'},
    {'Name': 'inline_aicodelines', 'Type': 'string'},
    {'Name': 'inline_acceptancecount', 'Type': 'string'},
    {'Name': 'inline_suggestionscount', 'Type': 'string'},
    {'Name': 'testgeneration_acceptedlines', 'Type': 'string'},
    {'Name': 'testgeneration_acceptedtests', 'Type': 'string'},
    {'Name': 'testgeneration_eventcount', 'Type': 'string'},
    {'Name': 'testgeneration_generatedlines', 'Type': 'string'},
    {'Name': 'testgeneration_generatedtests', 'Type': 'string'},
    {'Name': 'transformation_eventcount', 'Type': 'string'},
    {'Name': 'transformation_linesgenerated', 'Type': 'string'},
    {'Name': 'transformation_linesingested', 'Type': 'string'},
], f's3://{bucket}/{prefix}AWSLogs/{account_id}/KiroLogs/by_user_analytic/')

# user_report 表 (按 CSV header 实际列顺序，OpenCSVSerde 全部为 string)
# CSV header: Date,UserId,Client_Type,Chat_Conversations,Credits_Used,Overage_Cap,Overage_Credits_Used,Overage_Enabled,ProfileId,Subscription_Tier,Total_Messages
create_table('user_report', [
    {'Name': 'date', 'Type': 'string'},
    {'Name': 'userid', 'Type': 'string'},
    {'Name': 'client_type', 'Type': 'string'},
    {'Name': 'chat_conversations', 'Type': 'string'},
    {'Name': 'credits_used', 'Type': 'string'},
    {'Name': 'overage_cap', 'Type': 'string'},
    {'Name': 'overage_credits_used', 'Type': 'string'},
    {'Name': 'overage_enabled', 'Type': 'string'},
    {'Name': 'profileid', 'Type': 'string'},
    {'Name': 'subscription_tier', 'Type': 'string'},
    {'Name': 'total_messages', 'Type': 'string'},
], f's3://{bucket}/{prefix}AWSLogs/{account_id}/KiroLogs/user_report/')
"

echo "✓ 外部表创建完成"

# 建表完成后，统一授权所有 principal 的表级别 Lake Formation 权限
echo "  配置 Lake Formation 表级别权限..."

CALLER_ARN=$(aws sts get-caller-identity --query 'Arn' --output text)
grant_lf_all_tables "$CALLER_ARN" "SELECT DESCRIBE ALTER" "当前用户查询权限"

grant_lf_all_tables "IAM_ALLOWED_PRINCIPALS" "ALL" "IAMAllowedPrincipals 表权限"

grant_lf_all_tables "$QS_ROLE_ARN" "SELECT DESCRIBE" "QuickSight 表权限"

QS_IAM_ROLE=$(python3 -c "
arn = '$QS_USER_ARN'
parts = arn.split('/')
if len(parts) >= 3:
    print('arn:aws:iam::$ACCOUNT_ID:role/' + parts[-2])
else:
    print('')
")
if [ -n "$QS_IAM_ROLE" ]; then
    grant_lf_all_tables "$QS_IAM_ROLE" "SELECT DESCRIBE" "QuickSight 用户角色表权限"
fi

LAMBDA_ROLE_FULL_ARN=$(aws lambda get-function-configuration \
    --function-name kiro-user-mapping-sync \
    --query 'Role' --output text --region $REGION 2>/dev/null || echo "")
if [ -n "$LAMBDA_ROLE_FULL_ARN" ] && [ "$LAMBDA_ROLE_FULL_ARN" != "None" ]; then
    grant_lf_all_tables "$LAMBDA_ROLE_FULL_ARN" "SELECT DESCRIBE ALTER" "Lambda 表权限"
fi

echo ""
fi # step 3

# ============================================
# 4. 验证 Athena 数据查询
# ============================================
if [ "$FROM_STEP" -le 4 ]; then
echo "4️⃣  验证 Athena 数据查询..."

python3 -c "
import boto3, time, sys
athena = boto3.client('athena', region_name='$REGION')
tables = ['by_user_analytic', 'user_report']
ok = True

for t in tables:
    r = athena.start_query_execution(
        QueryString=f'SELECT COUNT(*) FROM $GLUE_DB.{t}',
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
fi # step 4

# ============================================
# 5. 同步用户映射 (Identity Center → S3 → Athena)
# ============================================
if [ "$FROM_STEP" -le 5 ]; then
echo "5️⃣  同步用户名映射..."
python3 scripts/sync_user_mapping.py

# user_mapping 表可能被 sync 脚本重建，需要补授 Lake Formation 权限
echo "  补授 user_mapping 表 Lake Formation 权限..."
for PERM_PAIR in \
    "IAM_ALLOWED_PRINCIPALS|ALL|IAMAllowedPrincipals" \
    "$(aws sts get-caller-identity --query 'Arn' --output text)|SELECT DESCRIBE ALTER|当前用户" \
    "$QS_ROLE_ARN|SELECT DESCRIBE|QuickSight"; do
    IFS='|' read -r P PERMS DESC <<< "$PERM_PAIR"
    grant_lf "$P" \
        "{\"Table\":{\"DatabaseName\":\"$GLUE_DB\",\"Name\":\"user_mapping\"}}" \
        "$PERMS" \
        "$DESC user_mapping 权限"
done
echo ""
fi # step 5

# ============================================
# 5.5 创建 Athena 视图（用户月度概况）
# ============================================
if [ "$FROM_STEP" -le 5 ]; then
echo "  创建 Athena 视图 user_summary..."
aws athena start-query-execution \
    --query-string "
CREATE OR REPLACE VIEW ${GLUE_DB}.user_summary AS
WITH current_month AS (
  SELECT date_format(current_date, '%Y-%m') as month
),
monthly_data AS (
  SELECT 
    m.username,
    array_join(array_sort(array_agg(DISTINCT r.subscription_tier)), ' → ') as tier_history,
    MAX(CASE 
      WHEN r.subscription_tier = 'POWER' THEN 10000
      WHEN r.subscription_tier = 'PRO_PLUS' THEN 2000
      ELSE 1000
    END) as capacity,
    array_join(array_sort(array_agg(DISTINCT r.client_type)), ' / ') as client_types,
    SUM(CAST(r.credits_used AS DECIMAL(10,2))) as total_credits,
    SUM(CAST(r.overage_credits_used AS DECIMAL(10,2))) as total_overage,
    SUM(CAST(r.total_messages AS INTEGER)) as total_messages,
    SUM(CAST(r.chat_conversations AS INTEGER)) as total_conversations,
    MIN(r.date) as first_seen,
    MAX(r.date) as last_seen,
    COUNT(DISTINCT r.date) as active_days
  FROM ${GLUE_DB}.user_report r
  LEFT JOIN ${GLUE_DB}.user_mapping m ON r.userid = m.userid
  WHERE date_format(date_parse(r.date, '%Y-%m-%d'), '%Y-%m') = (SELECT month FROM current_month)
  GROUP BY m.username
),
all_users AS (
  SELECT DISTINCT username FROM ${GLUE_DB}.user_mapping WHERE userid NOT LIKE 'd-%'
),
combined AS (
  SELECT d.username, (SELECT month FROM current_month) as month, d.tier_history, d.client_types,
    d.total_credits, d.total_overage, d.total_messages, d.total_conversations,
    d.first_seen, d.last_seen, d.active_days,
    d.capacity,
    ROUND(d.total_credits * 100.0 / d.capacity, 1) as usage_pct,
    1 as is_active,
    CASE
      WHEN d.tier_history LIKE '%→%' THEN '🔶 升级用户'
      WHEN d.total_credits * 100.0 / d.capacity >= 80 THEN '🟣 超高活跃'
      WHEN d.total_credits * 100.0 / d.capacity >= 50 THEN '🟢 高活跃'
      WHEN d.total_credits * 100.0 / d.capacity >= 10 THEN '🔵 一般活跃'
      WHEN d.total_credits * 100.0 / d.capacity >= 5 THEN '🟠 稍低活跃'
      WHEN d.total_credits > 0 THEN '🟡 低活跃'
      ELSE '🔴 不活跃'
    END as activity_level
  FROM monthly_data d
  UNION ALL
  SELECT u.username, (SELECT month FROM current_month) as month, '-' as tier_history, '-' as client_types,
    0.00 as total_credits, 0.00 as total_overage, 0 as total_messages, 0 as total_conversations,
    NULL as first_seen, NULL as last_seen, 0 as active_days,
    0 as capacity, 0.0 as usage_pct,
    0 as is_active,
    '🔴 不活跃' as activity_level
  FROM all_users u
  WHERE u.username NOT IN (SELECT username FROM monthly_data)
)
SELECT CAST(ROW_NUMBER() OVER (ORDER BY is_active DESC, total_credits DESC) AS INTEGER) as row_num,
  username, month, tier_history, client_types,
  total_credits, total_overage, total_messages, total_conversations,
  first_seen, last_seen, active_days, capacity, usage_pct, is_active, activity_level
FROM combined
" \
    --work-group $WORKGROUP \
    --region $REGION \
    --output text > /dev/null
sleep 5

# 授权 user_summary 和 credit_summary 视图
echo "  创建 Athena 视图 credit_summary..."
aws athena start-query-execution \
    --query-string "
CREATE OR REPLACE VIEW ${GLUE_DB}.credit_summary AS
WITH base AS (
  SELECT
    m.username,
    r.subscription_tier,
    r.client_type,
    SUM(CAST(r.credits_used AS DECIMAL(10,2))) as total_credits,
    SUM(CAST(r.overage_credits_used AS DECIMAL(10,2))) as total_overage,
    MAX(CAST(r.overage_cap AS DECIMAL(10,2))) as overage_cap,
    SUM(CAST(r.total_messages AS INTEGER)) as total_messages
  FROM ${GLUE_DB}.user_report r
  LEFT JOIN ${GLUE_DB}.user_mapping m ON r.userid = m.userid
  WHERE r.date > '2026-02-10'
  GROUP BY m.username, r.subscription_tier, r.client_type
)
SELECT CAST(ROW_NUMBER() OVER (ORDER BY total_credits DESC) AS INTEGER) as row_num,
  username, subscription_tier, client_type, total_credits, total_overage, overage_cap, total_messages
FROM base
" \
    --work-group $WORKGROUP \
    --region $REGION \
    --output text > /dev/null
sleep 5

for VIEW_NAME in user_summary credit_summary; do
for PRINCIPAL_PAIR in \
    "$(aws sts get-caller-identity --query 'Arn' --output text)|SELECT DESCRIBE" \
    "$QS_ROLE_ARN|SELECT DESCRIBE" \
    "IAM_ALLOWED_PRINCIPALS|SELECT DESCRIBE"; do
    IFS='|' read -r P PERMS <<< "$PRINCIPAL_PAIR"
    aws lakeformation grant-permissions \
        --principal "DataLakePrincipalIdentifier=$P" \
        --resource "{\"Table\":{\"DatabaseName\":\"$GLUE_DB\",\"Name\":\"$VIEW_NAME\"}}" \
        --permissions $PERMS \
        --region $REGION 2>/dev/null || true
done
done
echo "  ✓ user_summary / credit_summary 视图创建完成"
echo ""
fi # step 5.5

# ============================================
# 6. 部署 QuickSight 数据源、数据集和 Dashboard
# ============================================
if [ "$FROM_STEP" -le 6 ]; then
echo "6️⃣  部署 QuickSight 数据源和数据集 (SPICE 模式)..."
python3 scripts/create_datasets.py
echo ""
fi # step 6

if [ "$FROM_STEP" -le 7 ]; then
echo "7️⃣  发布 QuickSight Dashboard..."
python3 scripts/create_dashboard.py
echo ""
fi # step 7

# ============================================
# 8. 配置 Dashboard 报告 (SES 验证 + S3 静态网站)
# ============================================
if [ "$FROM_STEP" -le 8 ]; then
echo "8️⃣  配置 Dashboard 快照报告..."

# 验证 SES 发件人邮箱
if [ -n "$REPORT_EMAIL" ]; then
    SES_VERIFIED=$(aws sesv2 get-email-identity --email-identity "$REPORT_EMAIL" \
        --region $REGION --query 'VerifiedForSendingStatus' --output text 2>/dev/null || echo "NOT_FOUND")
    if [ "$SES_VERIFIED" != "True" ]; then
        echo "  发送 SES 验证邮件到 $REPORT_EMAIL ..."
        aws sesv2 create-email-identity --email-identity "$REPORT_EMAIL" --region $REGION 2>/dev/null || true
        echo "  ⚠️  请检查邮箱并点击验证链接！"
    else
        echo "  ✓ SES 邮箱已验证: $REPORT_EMAIL"
    fi
fi

# 启用 S3 静态网站托管
aws s3api put-bucket-website \
    --bucket $REPORT_BUCKET \
    --website-configuration '{"IndexDocument":{"Suffix":"index.html"},"ErrorDocument":{"Key":"error.html"}}' \
    --region $REGION 2>/dev/null
echo "  ✓ S3 静态网站已启用"

# 更新 Dashboard Report Lambda 代码
echo "  更新 Dashboard Report Lambda 代码..."
python3 -c "
import yaml
class CFLoader(yaml.SafeLoader): pass
for tag in ['!Ref','!Sub','!GetAtt','!Join','!Select','!Split','!If','!Equals','!Not','!And','!Or']:
    CFLoader.add_constructor(tag, lambda l,n: l.construct_scalar(n) if n.id=='scalar' else l.construct_sequence(n))
cf = yaml.load(open('infrastructure/cloudformation.yaml'), Loader=CFLoader)
code = cf['Resources']['DashboardReportFunction']['Properties']['Code']['ZipFile']
with open('/tmp/index.py', 'w') as f:
    f.write(code)
"
cd /tmp && zip -q report_lambda.zip index.py
aws lambda update-function-code \
    --function-name kiro-dashboard-report \
    --zip-file fileb:///tmp/report_lambda.zip \
    --region $REGION > /dev/null 2>&1 || echo "  (Lambda 将在 CF 部署时创建)"
cd - > /dev/null
rm -f /tmp/index.py /tmp/report_lambda.zip
echo "  ✓ Dashboard Report Lambda 代码已更新"

REPORT_URL="http://${REPORT_BUCKET}.s3-website-${REGION}.amazonaws.com/dashboard-reports/public/index.html"
echo "  ✓ 报告访问地址: $REPORT_URL"
echo ""
fi # step 8

# ============================================
# 完成
# ============================================
echo "✅ 端到端部署完成！"
echo ""
echo "📊 访问 QuickSight 控制台查看仪表板:"
echo "   https://$REGION.quicksight.aws.amazon.com/"
echo ""
