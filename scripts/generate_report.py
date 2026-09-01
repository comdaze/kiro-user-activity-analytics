#!/usr/bin/env python3
"""
手动触发 Dashboard 快照报告生成。
也可用于本地测试，逻辑与 CloudFormation 中的 Lambda inline code 一致。

用法: python3 scripts/generate_report.py [--trigger-lambda]
  默认: 本地直接调用 QuickSight API 生成报告
  --trigger-lambda: 通过 invoke Lambda 函数生成（测试已部署的 Lambda）
"""
import boto3, time, sys, yaml

config = yaml.safe_load(open('config.yaml'))
region = config['aws']['region']
account_id = config['aws']['account_id']
bucket = config['report']['bucket']
dashboard_id = config['quicksight'].get('dashboard_id', 'kiro-comprehensive-dashboard')

if '--trigger-lambda' in sys.argv:
    lam = boto3.client('lambda', region_name=region)
    print("触发 Lambda: kiro-dashboard-report ...")
    resp = lam.invoke(FunctionName='kiro-dashboard-report', InvocationType='Event')
    print("✓ 已异步触发 (StatusCode: {})".format(resp['StatusCode']))
    print("  报告将在 ~2 分钟后生成，届时查看邮箱或访问:")
    print("  http://{}.s3-website-us-east-1.amazonaws.com/dashboard-reports/public/index.html".format(bucket))
    sys.exit(0)

from datetime import datetime, timezone, timedelta

qs = boto3.client('quicksight', region_name=region)
s3 = boto3.client('s3', region_name=region)

base_url = 'http://{}.s3-website-us-east-1.amazonaws.com/dashboard-reports/public'.format(bucket)
sheets = [
    ('sheet-overview', '概览'),
    ('sheet-behavior', '用户行为'),
    ('sheet-cost', '成本分析'),
    ('sheet-user-summary', '用户概况'),
]

bj = datetime.now(timezone(timedelta(hours=8)))
ts = bj.strftime('%Y%m%d%H%M')
date_str = bj.strftime('%Y-%m-%d')

print("生成 Dashboard 快照报告: {}".format(date_str))
print("  Dashboard: {}".format(dashboard_id))
print("  S3 Bucket: {}".format(bucket))

jobs = []
for sid, name in sheets:
    jid = 'manual-{}-{}'.format(ts, sid)
    qs.start_dashboard_snapshot_job(
        AwsAccountId=account_id, DashboardId=dashboard_id, SnapshotJobId=jid,
        UserConfiguration={'AnonymousUsers': [{}]},
        SnapshotConfiguration={
            'FileGroups': [{'Files': [{'SheetSelections': [{'SheetId': sid, 'SelectionScope': 'ALL_VISUALS'}], 'FormatType': 'PDF'}]}],
            'DestinationConfiguration': {'S3Destinations': [{'BucketConfiguration': {'BucketName': bucket, 'BucketPrefix': 'dashboard-reports/staging', 'BucketRegion': region}}]}
        })
    jobs.append((jid, name, sid))
    print("  ✓ 快照任务已提交: {}".format(name))

print("  等待快照生成 (~90s)...")
time.sleep(90)

pdf_files = []
for jid, name, sid in jobs:
    try:
        r = qs.describe_dashboard_snapshot_job_result(AwsAccountId=account_id, DashboardId=dashboard_id, SnapshotJobId=jid)
        uri = r['Result']['AnonymousUsers'][0]['FileGroups'][0]['S3Results'][0]['S3Uri']
        src_key = uri.replace('s3://{}/'.format(bucket), '')
        dst_key = 'dashboard-reports/public/{}/{}.pdf'.format(date_str, sid)
        s3.copy_object(Bucket=bucket, CopySource={'Bucket': bucket, 'Key': src_key}, Key=dst_key,
                       ContentType='application/pdf', MetadataDirective='REPLACE', ContentDisposition='inline')
        s3.delete_object(Bucket=bucket, Key=src_key)
        url = '{}/{}/{}.pdf'.format(base_url, date_str, sid)
        pdf_files.append((name, sid, url))
        print("  ✓ {}: {}".format(name, url))
    except Exception as e:
        print("  ✗ {}: {}".format(name, e))
        pdf_files.append((name, sid, 'ERROR'))

# Update latest redirect
latest = '<html><head><meta http-equiv="refresh" content="0;url={}/{}/index.html"></head></html>'.format(base_url, date_str)
s3.put_object(Bucket=bucket, Key='dashboard-reports/public/index.html', Body=latest.encode(), ContentType='text/html; charset=utf-8')

print("\n✅ 报告生成完成!")
print("  在线查看: {}/{}/index.html".format(base_url, date_str))
print("  最新链接: {}/index.html".format(base_url))
