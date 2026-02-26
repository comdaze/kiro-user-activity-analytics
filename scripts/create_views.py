#!/usr/bin/env python3
"""在 Athena 中创建所有分析视图"""
import boto3
import re
import time
import yaml


def main():
    config = yaml.safe_load(open('config.yaml'))
    region = config['aws']['region']
    workgroup = 'kiro-analytics-workgroup'
    athena = boto3.client('athena', region_name=region)

    with open('sql/create_views.sql') as f:
        content = f.read()

    # 去掉 SQL 注释
    content = re.sub(r'--.*$', '', content, flags=re.MULTILINE)

    # 按 CREATE 语句拆分
    stmts = re.split(r'(?=CREATE)', content)
    stmts = [s.strip().rstrip(';').strip() for s in stmts if s.strip().startswith('CREATE')]

    print(f"共 {len(stmts)} 个视图待创建\n")

    failed = 0
    for stmt in stmts:
        view_name = stmt.split('AS')[0].replace('CREATE OR REPLACE VIEW', '').strip()
        print(f"  创建 {view_name} ... ", end='', flush=True)

        resp = athena.start_query_execution(QueryString=stmt, WorkGroup=workgroup)
        qid = resp['QueryExecutionId']

        while True:
            status = athena.get_query_execution(QueryExecutionId=qid)
            state = status['QueryExecution']['Status']['State']
            if state == 'SUCCEEDED':
                print('✓')
                break
            elif state == 'FAILED':
                reason = status['QueryExecution']['Status'].get('StateChangeReason', 'unknown')
                print(f'✗ {reason}')
                failed += 1
                break
            time.sleep(2)

    if failed:
        print(f"\n✗ {failed} 个视图创建失败")
        exit(1)
    else:
        print("\n✓ 所有视图创建成功")


if __name__ == '__main__':
    main()
