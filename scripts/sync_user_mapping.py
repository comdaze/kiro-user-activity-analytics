#!/usr/bin/env python3
"""
从 Athena 查出所有 userid，通过 IAM Identity Center 获取用户名，
生成映射 CSV 上传到 S3，并创建/更新 Athena 外部表。
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
identity_store_id = config.get('identity_center', {}).get('identity_store_id', 'd-906791923a')

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
        return user.get('DisplayName', '') or user.get('UserName', '') or user_id
    except Exception:
        return user_id


# ============================================
# 1. 从两张表查出所有不重复的 userid
# ============================================
print("1. 查询所有 userid...")
raw_userids = set()  # 原始值（可能带引号）

for table in ['by_user_analytic', 'user_report']:
    try:
        rows = run_query(f'SELECT DISTINCT userid FROM {glue_db}.{table}')
        for row in rows:
            if row[0]:
                raw_userids.add(row[0])
    except Exception as e:
        print(f"  跳过 {table}: {e}")

print(f"  找到 {len(raw_userids)} 个不重复用户")

# ============================================
# 2. 逐个查询 Identity Center 获取用户名
# ============================================
print("2. 从 Identity Center 获取用户名...")
mapping = []
for raw_uid in sorted(raw_userids):
    # 去掉 CSV serde 可能保留的引号
    clean_uid = raw_uid.strip('"').strip()
    if not clean_uid:
        continue
    name = get_display_name(clean_uid)
    # 映射表存储原始 userid（与 Athena 表中一致）以便 JOIN
    mapping.append((raw_uid, name))
    print(f"  {raw_uid} → {name}")

# ============================================
# 3. 生成 CSV 并上传到 S3
# ============================================
print("3. 上传映射文件到 S3...")
buf = io.StringIO()
writer = csv.writer(buf)
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
