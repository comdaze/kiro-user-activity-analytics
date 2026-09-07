#!/usr/bin/env python3
"""
从 Athena 查出所有 userid，通过 IAM Identity Center 获取用户名，
生成映射 CSV 上传到 S3，并创建/更新 Athena 外部表。

NOTE: 此脚本用于本地/手动执行。CloudFormation 中的 Lambda inline code
(infrastructure/cloudformation.yaml → UserMappingFunction) 包含相同逻辑。
修改时请同步更新两处。
"""
import boto3
import yaml
import csv
import io
import time

config = yaml.safe_load(open('config.yaml'))
region = config['aws']['region']
account_id = config['aws']['account_id']
bucket = config['s3']['bucket_name']
glue_db = config['glue']['database_name']
identity_store_id = config['identity_center']['identity_store_id']

athena = boto3.client('athena', region_name=region)
s3 = boto3.client('s3', region_name=region)
ids = boto3.client('identitystore', region_name=region)
glue = boto3.client('glue', region_name=region)

WORKGROUP = 'kiro-analytics-workgroup'
MAPPING_PREFIX = 'user-mapping/'
MAPPING_KEY = f'{MAPPING_PREFIX}user_mapping.csv'


def run_query(sql):
    """执行 Athena 查询并返回结果行"""
    r = athena.start_query_execution(QueryString=sql, WorkGroup=WORKGROUP)
    qid = r['QueryExecutionId']
    while True:
        s = athena.get_query_execution(QueryExecutionId=qid)['QueryExecution']['Status']['State']
        if s == 'SUCCEEDED':
            break
        elif s == 'FAILED':
            reason = athena.get_query_execution(QueryExecutionId=qid)['QueryExecution']['Status'].get('StateChangeReason', '')
            raise Exception(f"Query failed: {reason}")
        time.sleep(2)
    rows = []
    paginator = athena.get_paginator('get_query_results')
    for page in paginator.paginate(QueryExecutionId=qid):
        for row in page['ResultSet']['Rows']:
            rows.append([col.get('VarCharValue', '') for col in row['Data']])
    return rows[1:]  # skip header


def get_display_name(user_id):
    """从 Identity Center 获取用户显示名"""
    try:
        user = ids.describe_user(IdentityStoreId=identity_store_id, UserId=user_id)
        name = user.get('DisplayName', '') or user.get('UserName', '') or user_id
        # 清理换行符和特殊字符
        return name.replace('\r', '').replace('\n', '').strip()
    except Exception as e:
        print(f"    ✗ DescribeUser 失败: {e}")
        return user_id


def canonical_user_id(value):
    value = (value or '').strip()
    return value.split('.', 1)[1] if value.startswith('d-') and '.' in value else value


def load_previous_names():
    """保留已删除 IIC 用户最后一次有效姓名，避免每日全量覆盖丢失。"""
    try:
        body = s3.get_object(Bucket=bucket, Key=MAPPING_KEY)['Body'].read().decode('utf-8-sig')
    except Exception:
        return {}
    result = {}
    for row in csv.DictReader(io.StringIO(body)):
        uid = canonical_user_id(row.get('userid'))
        name = (row.get('username') or '').replace('\r', '').replace('\n', '').strip()
        if uid and name and name != uid:
            result[uid] = name
    return result


# ============================================
# 1. 从两张表查出所有不重复的 userid（提取纯 UUID）
# ============================================
print("1. 查询所有 userid...")
raw_userids = set()  # 原始值（可能带引号）

for table in ['by_user_analytic', 'user_report']:
    try:
        # 使用 CASE 语句提取纯 UUID（去掉 d-xxxxx. 前缀）
        query = f"""
            SELECT DISTINCT 
                CASE 
                    WHEN userid LIKE 'd-%' THEN split_part(userid, '.', 2)
                    ELSE userid
                END as userid_clean
            FROM {glue_db}.{table}
        """
        rows = run_query(query)
        for row in rows:
            if row[0]:
                raw_userids.add(row[0])
    except Exception as e:
        print(f"  跳过 {table}: {e}")

print(f"  找到 {len(raw_userids)} 个不重复用户")

# ============================================
# 2. 从 Identity Center 获取所有用户，合并 Athena userid
# ============================================
print("2. 从 Identity Center 获取所有用户...")
mapping = []
iic_userids = set()
previous_names = load_previous_names()

# 拉取 IIC 全部用户
paginator_token = None
while True:
    kwargs = {'IdentityStoreId': identity_store_id}
    if paginator_token:
        kwargs['NextToken'] = paginator_token
    resp = ids.list_users(**kwargs)
    for user in resp.get('Users', []):
        uid = user['UserId']
        name = user.get('DisplayName', '') or user.get('UserName', '') or uid
        name = name.replace('\r', '').replace('\n', '').strip()
        if name == uid:
            name = previous_names.get(uid, uid)
        iic_userids.add(uid)
        mapping.append((uid, name))
        mapping.append((f'{identity_store_id}.{uid}', name))
        print(f"  {uid} → {name}")
    paginator_token = resp.get('NextToken')
    if not paginator_token:
        break

# 补充 Athena 中存在但 IIC 中不存在的 userid（如已删除的用户）
for raw_uid in sorted(raw_userids):
    clean_uid = raw_uid.strip('"').strip()
    if clean_uid and clean_uid not in iic_userids:
        name = get_display_name(clean_uid)
        if name == clean_uid:
            name = previous_names.get(clean_uid, clean_uid)
        mapping.append((clean_uid, name))
        mapping.append((f'{identity_store_id}.{clean_uid}', name))
        print(f"  {clean_uid} → {name} (仅在 Athena 中)")

print(f"  IIC 用户: {len(iic_userids)}, Athena 用户: {len(raw_userids)}, 映射记录: {len(mapping)}")

# ============================================
# 3. 生成 CSV 并上传到 S3（使用 Unix 换行符）
# ============================================
print("3. 上传映射文件到 S3...")
buf = io.StringIO(newline='')  # 强制使用 \n
writer = csv.writer(buf, lineterminator='\n')  # Unix 换行符
writer.writerow(['userid', 'username'])
for uid, name in mapping:
    writer.writerow([uid, name])

s3.put_object(
    Bucket=bucket,
    Key=MAPPING_KEY,
    Body=buf.getvalue().encode('utf-8'),
    ContentType='text/csv'
)
print(f"  ✓ s3://{bucket}/{MAPPING_KEY}")

# ============================================
# 4. 创建/更新 Glue 表指向映射 CSV
# ============================================
print("4. 创建 Athena 映射表...")
table_input = {
    'Name': 'user_mapping',
    'StorageDescriptor': {
        'Columns': [
            {'Name': 'userid', 'Type': 'string'},
            {'Name': 'username', 'Type': 'string'},
        ],
        'Location': f's3://{bucket}/{MAPPING_PREFIX}',
        'InputFormat': 'org.apache.hadoop.mapred.TextInputFormat',
        'OutputFormat': 'org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat',
        'SerdeInfo': {
            'SerializationLibrary': 'org.apache.hadoop.hive.serde2.OpenCSVSerde',
            'Parameters': {
                'separatorChar': ',',
                'quoteChar': '"',
                'escapeChar': '\\'
            }
        }
    },
    'TableType': 'EXTERNAL_TABLE',
    'Parameters': {
        'skip.header.line.count': '1',
        'classification': 'csv'
    }
}

try:
    glue.create_table(DatabaseName=glue_db, TableInput=table_input)
    print("  ✓ user_mapping 表创建成功")
except glue.exceptions.AlreadyExistsException:
    glue.update_table(DatabaseName=glue_db, TableInput=table_input)
    print("  ✓ user_mapping 表已更新")

# ============================================
# 5. 验证
# ============================================
print("5. 验证映射表...")
rows = run_query(f'SELECT * FROM {glue_db}.user_mapping LIMIT 5')
for row in rows:
    print(f"  {row[0]} → {row[1]}")

print(f"\n✅ 用户映射同步完成！共 {len(mapping)} 个用户")
