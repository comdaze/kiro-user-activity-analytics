#!/usr/bin/env python3
import boto3
import yaml
import json
from pathlib import Path

class QuickSightDeployer:
    # QuickSight dataset permissions actions (shared across all datasets)
    QS_DATASET_ACTIONS = [
        'quicksight:DescribeDataSet', 'quicksight:DescribeDataSetPermissions',
        'quicksight:PassDataSet', 'quicksight:DescribeIngestion',
        'quicksight:ListIngestions', 'quicksight:UpdateDataSet',
        'quicksight:DeleteDataSet', 'quicksight:CreateIngestion',
        'quicksight:CancelIngestion', 'quicksight:UpdateDataSetPermissions'
    ]

    def __init__(self, config_path='config.yaml'):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
        
        self.qs = boto3.client('quicksight', region_name=self.config['aws']['region'])
        self.account_id = self.config['aws']['account_id']
        
    def create_data_source(self):
        """创建 Athena 数据源（如果已存在但状态为 CREATION_FAILED，自动删除重建）"""
        ds_id = 'kiro-athena-datasource'

        # 检查是否已存在
        try:
            desc = self.qs.describe_data_source(AwsAccountId=self.account_id, DataSourceId=ds_id)
            status = desc['DataSource']['Status']
            if status == 'CREATION_FAILED':
                print(f"  ⚠ 数据源状态为 CREATION_FAILED，自动删除重建...")
                self.qs.delete_data_source(AwsAccountId=self.account_id, DataSourceId=ds_id)
            else:
                print(f"✓ 数据源已存在 (状态: {status})")
                return ds_id
        except self.qs.exceptions.ResourceNotFoundException:
            pass  # 不存在，继续创建

        response = self.qs.create_data_source(
            AwsAccountId=self.account_id,
            DataSourceId=ds_id,
            Name=self.config['quicksight']['data_source_name'],
            Type='ATHENA',
            DataSourceParameters={
                'AthenaParameters': {
                    'WorkGroup': 'kiro-analytics-workgroup'
                }
            },
            Permissions=[{
                'Principal': self.config['quicksight']['user_arn'],
                'Actions': [
                    'quicksight:DescribeDataSource',
                    'quicksight:DescribeDataSourcePermissions',
                    'quicksight:PassDataSource',
                    'quicksight:UpdateDataSource',
                    'quicksight:DeleteDataSource',
                    'quicksight:UpdateDataSourcePermissions'
                ]
            }]
        )
        print(f"✓ 数据源创建成功: {response['DataSourceId']}")
        return response['DataSourceId']
    
    def create_dataset(self, data_source_id):
        """创建行为分析数据集（JOIN user_mapping 获取用户名，SPICE 模式）"""
        ds_arn = f"arn:aws:quicksight:{self.config['aws']['region']}:{self.account_id}:datasource/{data_source_id}"
        db = self.config['glue']['database_name']
        physical = {
            'activity': {
                'RelationalTable': {
                    'DataSourceArn': ds_arn, 'Catalog': 'AwsDataCatalog',
                    'Schema': db, 'Name': 'by_user_analytic',
                    'InputColumns': [
                        {'Name': 'userid', 'Type': 'STRING'},
                        {'Name': 'date', 'Type': 'STRING'},
                        {'Name': 'chat_aicodelines', 'Type': 'STRING'},
                        {'Name': 'chat_messagesinteracted', 'Type': 'STRING'},
                        {'Name': 'chat_messagessent', 'Type': 'STRING'},
                        {'Name': 'codefix_acceptanceeventcount', 'Type': 'STRING'},
                        {'Name': 'codefix_acceptedlines', 'Type': 'STRING'},
                        {'Name': 'codefix_generatedlines', 'Type': 'STRING'},
                        {'Name': 'codefix_generationeventcount', 'Type': 'STRING'},
                        {'Name': 'codereview_failedeventcount', 'Type': 'STRING'},
                        {'Name': 'codereview_findingscount', 'Type': 'STRING'},
                        {'Name': 'codereview_succeededeventcount', 'Type': 'STRING'},
                        {'Name': 'dev_acceptanceeventcount', 'Type': 'STRING'},
                        {'Name': 'dev_acceptedlines', 'Type': 'STRING'},
                        {'Name': 'dev_generatedlines', 'Type': 'STRING'},
                        {'Name': 'dev_generationeventcount', 'Type': 'STRING'},
                        {'Name': 'docgeneration_acceptedfileupdates', 'Type': 'STRING'},
                        {'Name': 'docgeneration_acceptedfilescreations', 'Type': 'STRING'},
                        {'Name': 'docgeneration_acceptedlineadditions', 'Type': 'STRING'},
                        {'Name': 'docgeneration_acceptedlineupdates', 'Type': 'STRING'},
                        {'Name': 'docgeneration_eventcount', 'Type': 'STRING'},
                        {'Name': 'docgeneration_rejectedfilecreations', 'Type': 'STRING'},
                        {'Name': 'docgeneration_rejectedfileupdates', 'Type': 'STRING'},
                        {'Name': 'docgeneration_rejectedlineadditions', 'Type': 'STRING'},
                        {'Name': 'docgeneration_rejectedlineupdates', 'Type': 'STRING'},
                        {'Name': 'inlinechat_acceptanceeventcount', 'Type': 'STRING'},
                        {'Name': 'inlinechat_acceptedlineadditions', 'Type': 'STRING'},
                        {'Name': 'inlinechat_acceptedlinedeletions', 'Type': 'STRING'},
                        {'Name': 'inlinechat_dismissaleventcount', 'Type': 'STRING'},
                        {'Name': 'inlinechat_dismissedlineadditions', 'Type': 'STRING'},
                        {'Name': 'inlinechat_dismissedlinedeletions', 'Type': 'STRING'},
                        {'Name': 'inlinechat_rejectedlineadditions', 'Type': 'STRING'},
                        {'Name': 'inlinechat_rejectedlinedeletions', 'Type': 'STRING'},
                        {'Name': 'inlinechat_rejectioneventcount', 'Type': 'STRING'},
                        {'Name': 'inlinechat_totaleventcount', 'Type': 'STRING'},
                        {'Name': 'inline_aicodelines', 'Type': 'STRING'},
                        {'Name': 'inline_acceptancecount', 'Type': 'STRING'},
                        {'Name': 'inline_suggestionscount', 'Type': 'STRING'},
                        {'Name': 'testgeneration_acceptedlines', 'Type': 'STRING'},
                        {'Name': 'testgeneration_acceptedtests', 'Type': 'STRING'},
                        {'Name': 'testgeneration_eventcount', 'Type': 'STRING'},
                        {'Name': 'testgeneration_generatedlines', 'Type': 'STRING'},
                        {'Name': 'testgeneration_generatedtests', 'Type': 'STRING'},
                        {'Name': 'transformation_eventcount', 'Type': 'STRING'},
                        {'Name': 'transformation_linesgenerated', 'Type': 'STRING'},
                        {'Name': 'transformation_linesingested', 'Type': 'STRING'},
                    ]
                }
            },
            'mapping': {
                'RelationalTable': {
                    'DataSourceArn': ds_arn, 'Catalog': 'AwsDataCatalog',
                    'Schema': db, 'Name': 'user_mapping',
                    'InputColumns': [
                        {'Name': 'userid', 'Type': 'STRING'},
                        {'Name': 'username', 'Type': 'STRING'},
                    ]
                }
            }
        }
        # 数值列列表（需要从 STRING 转为 INTEGER）
        int_cols = [
            'chat_aicodelines', 'chat_messagesinteracted', 'chat_messagessent',
            'codefix_acceptanceeventcount', 'codefix_acceptedlines',
            'codefix_generatedlines', 'codefix_generationeventcount',
            'codereview_failedeventcount', 'codereview_findingscount',
            'codereview_succeededeventcount',
            'dev_acceptanceeventcount', 'dev_acceptedlines',
            'dev_generatedlines', 'dev_generationeventcount',
            'docgeneration_eventcount', 'docgeneration_acceptedfilescreations',
            'docgeneration_acceptedlineadditions',
            'inlinechat_totaleventcount', 'inlinechat_acceptanceeventcount',
            'inlinechat_acceptedlineadditions', 'inlinechat_acceptedlinedeletions',
            'inline_aicodelines', 'inline_acceptancecount', 'inline_suggestionscount',
            'testgeneration_eventcount', 'testgeneration_acceptedtests',
            'testgeneration_generatedlines', 'testgeneration_generatedtests',
            'transformation_eventcount', 'transformation_linesgenerated',
        ]
        cast_transforms = [
            {'CastColumnTypeOperation': {'ColumnName': 'date', 'NewColumnType': 'DATETIME', 'Format': 'MM-dd-yyyy'}}
        ] + [{'CastColumnTypeOperation': {
            'ColumnName': c, 'NewColumnType': 'INTEGER'
        }} for c in int_cols]

        logical = {
            'activity-base': {
                'Alias': 'activity_data',
                'Source': {'PhysicalTableId': 'activity'},
                'DataTransforms': cast_transforms,
            },
            'mapping-base': {
                'Alias': 'user_mapping',
                'Source': {'PhysicalTableId': 'mapping'},
                'DataTransforms': [{
                    'RenameColumnOperation': {
                        'ColumnName': 'userid',
                        'NewColumnName': 'map_userid'
                    }
                }]
            },
            'activity-joined': {
                'Alias': 'activity_with_username',
                'Source': {
                    'JoinInstruction': {
                        'LeftOperand': 'activity-base',
                        'RightOperand': 'mapping-base',
                        'Type': 'LEFT',
                        'OnClause': 'userid = map_userid'
                    }
                },
                'DataTransforms': [
                    {
                        'ProjectOperation': {
                            'ProjectedColumns': [
                                'date', 'userid', 'username',
                                'chat_aicodelines', 'chat_messagesinteracted', 'chat_messagessent',
                                'inline_aicodelines', 'inline_acceptancecount', 'inline_suggestionscount',
                                'codefix_generationeventcount', 'codefix_acceptanceeventcount',
                                'codereview_findingscount', 'codereview_succeededeventcount',
                                'dev_generationeventcount', 'dev_acceptanceeventcount', 'dev_generatedlines',
                                'testgeneration_eventcount', 'testgeneration_acceptedtests',
                                'inlinechat_totaleventcount', 'inlinechat_acceptanceeventcount',
                                'docgeneration_eventcount', 'docgeneration_acceptedfilescreations',
                                'transformation_eventcount', 'transformation_linesgenerated',
                            ]
                        }
                    },
                    {
                        'FilterOperation': {
                            'ConditionExpression': 'date > parseDate("2026-02-10", "yyyy-MM-dd")'
                        }
                    }
                ]
            }
        }
        params = dict(
            AwsAccountId=self.account_id,
            DataSetId='kiro-user-activity-dataset',
            Name=self.config['quicksight']['dataset_name'],
            PhysicalTableMap=physical,
            LogicalTableMap=logical,
            ImportMode='SPICE',
            Permissions=[{
                'Principal': self.config['quicksight']['user_arn'],
                'Actions': self.QS_DATASET_ACTIONS
            }]
        )
        try:
            self.qs.create_data_set(**params)
            print(f"✓ 行为分析数据集创建成功 (SPICE 模式)")
        except self.qs.exceptions.ResourceExistsException:
            del params['Permissions']
            self.qs.update_data_set(**params)
            print(f"✓ 行为分析数据集已更新 (SPICE 模式)")
        
        # 触发首次 SPICE 导入
        self._trigger_ingestion('kiro-user-activity-dataset')
        # 设置每日刷新计划
        self._create_refresh_schedule('kiro-user-activity-dataset', 'activity-daily-refresh')
        return 'kiro-user-activity-dataset'

    def create_credits_dataset(self, data_source_id):
        """创建 Credits 数据集（JOIN user_mapping 获取用户名，SPICE 模式）"""
        ds_arn = f"arn:aws:quicksight:{self.config['aws']['region']}:{self.account_id}:datasource/{data_source_id}"
        db = self.config['glue']['database_name']
        physical = {
            'credits': {
                'RelationalTable': {
                    'DataSourceArn': ds_arn, 'Catalog': 'AwsDataCatalog',
                    'Schema': db, 'Name': 'user_report',
                    'InputColumns': [
                        {'Name': 'date', 'Type': 'STRING'},
                        {'Name': 'userid', 'Type': 'STRING'},
                        {'Name': 'client_type', 'Type': 'STRING'},
                        {'Name': 'chat_conversations', 'Type': 'STRING'},
                        {'Name': 'credits_used', 'Type': 'STRING'},
                        {'Name': 'overage_cap', 'Type': 'STRING'},
                        {'Name': 'overage_credits_used', 'Type': 'STRING'},
                        {'Name': 'overage_enabled', 'Type': 'STRING'},
                        {'Name': 'profileid', 'Type': 'STRING'},
                        {'Name': 'subscription_tier', 'Type': 'STRING'},
                        {'Name': 'total_messages', 'Type': 'STRING'},
                    ]
                }
            },
            'mapping2': {
                'RelationalTable': {
                    'DataSourceArn': ds_arn, 'Catalog': 'AwsDataCatalog',
                    'Schema': db, 'Name': 'user_mapping',
                    'InputColumns': [
                        {'Name': 'userid', 'Type': 'STRING'},
                        {'Name': 'username', 'Type': 'STRING'},
                    ]
                }
            }
        }
        credits_cast = [
            {'CastColumnTypeOperation': {'ColumnName': 'date', 'NewColumnType': 'DATETIME', 'Format': 'yyyy-MM-dd'}},
            {'CastColumnTypeOperation': {'ColumnName': 'total_messages', 'NewColumnType': 'INTEGER'}},
            {'CastColumnTypeOperation': {'ColumnName': 'chat_conversations', 'NewColumnType': 'INTEGER'}},
            {'CastColumnTypeOperation': {'ColumnName': 'credits_used', 'NewColumnType': 'DECIMAL'}},
            {'CastColumnTypeOperation': {'ColumnName': 'overage_cap', 'NewColumnType': 'DECIMAL'}},
            {'CastColumnTypeOperation': {'ColumnName': 'overage_credits_used', 'NewColumnType': 'DECIMAL'}},
        ]
        logical = {
            'credits-base': {
                'Alias': 'credits_data',
                'Source': {'PhysicalTableId': 'credits'},
                'DataTransforms': credits_cast,
            },
            'mapping2-base': {
                'Alias': 'user_mapping2',
                'Source': {'PhysicalTableId': 'mapping2'},
                'DataTransforms': [{
                    'RenameColumnOperation': {
                        'ColumnName': 'userid',
                        'NewColumnName': 'map_userid'
                    }
                }]
            },
            'credits-joined': {
                'Alias': 'credits_with_username',
                'Source': {
                    'JoinInstruction': {
                        'LeftOperand': 'credits-base',
                        'RightOperand': 'mapping2-base',
                        'Type': 'LEFT',
                        'OnClause': 'userid = map_userid'
                    }
                },
                'DataTransforms': [
                    {
                        'ProjectOperation': {
                            'ProjectedColumns': [
                                'date', 'userid', 'username',
                                'client_type', 'subscription_tier',
                                'total_messages', 'chat_conversations',
                                'credits_used', 'overage_cap',
                                'overage_credits_used', 'overage_enabled', 'profileid',
                            ]
                        }
                    },
                    {
                        'FilterOperation': {
                            'ConditionExpression': 'date > parseDate("2026-02-10", "yyyy-MM-dd")'
                        }
                    }
                ]
            }
        }
        params = dict(
            AwsAccountId=self.account_id,
            DataSetId='kiro-user-credits-dataset',
            Name='KiroUserCreditsDataset',
            PhysicalTableMap=physical,
            LogicalTableMap=logical,
            ImportMode='SPICE',
            Permissions=[{
                'Principal': self.config['quicksight']['user_arn'],
                'Actions': self.QS_DATASET_ACTIONS
            }]
        )
        try:
            self.qs.create_data_set(**params)
            print(f"✓ Credits 数据集创建成功 (SPICE 模式)")
        except self.qs.exceptions.ResourceExistsException:
            del params['Permissions']
            self.qs.update_data_set(**params)
            print(f"✓ Credits 数据集已更新 (SPICE 模式)")
        
        # 触发首次 SPICE 导入
        self._trigger_ingestion('kiro-user-credits-dataset')
        # 设置每日刷新计划
        self._create_refresh_schedule('kiro-user-credits-dataset', 'credits-daily-refresh')
        return 'kiro-user-credits-dataset'

    def create_summary_dataset(self, data_source_id):
        """创建用户概况数据集（基于 Athena 视图 user_summary）"""
        ds_arn = f"arn:aws:quicksight:{self.config['aws']['region']}:{self.account_id}:datasource/{data_source_id}"
        db = self.config['glue']['database_name']
        params = dict(
            AwsAccountId=self.account_id,
            DataSetId='kiro-user-summary-dataset',
            Name='KiroUserSummaryDataset',
            PhysicalTableMap={
                'summary': {
                    'RelationalTable': {
                        'DataSourceArn': ds_arn, 'Catalog': 'AwsDataCatalog',
                        'Schema': db, 'Name': 'user_summary',
                        'InputColumns': [
                            {'Name': 'row_num', 'Type': 'INTEGER'},
                            {'Name': 'username', 'Type': 'STRING'},
                            {'Name': 'month', 'Type': 'STRING'},
                            {'Name': 'tier_history', 'Type': 'STRING'},
                            {'Name': 'client_types', 'Type': 'STRING'},
                            {'Name': 'total_credits', 'Type': 'DECIMAL'},
                            {'Name': 'total_overage', 'Type': 'DECIMAL'},
                            {'Name': 'total_messages', 'Type': 'INTEGER'},
                            {'Name': 'total_conversations', 'Type': 'INTEGER'},
                            {'Name': 'first_seen', 'Type': 'STRING'},
                            {'Name': 'last_seen', 'Type': 'STRING'},
                            {'Name': 'active_days', 'Type': 'INTEGER'},
                            {'Name': 'capacity', 'Type': 'INTEGER'},
                            {'Name': 'usage_pct', 'Type': 'DECIMAL'},
                            {'Name': 'is_active', 'Type': 'INTEGER'},
                            {'Name': 'activity_level', 'Type': 'STRING'},
                        ]
                    }
                }
            },
            LogicalTableMap={
                'summary-base': {
                    'Alias': 'user_summary',
                    'Source': {'PhysicalTableId': 'summary'},
                }
            },
            ImportMode='SPICE',
            Permissions=[{
                'Principal': self.config['quicksight']['user_arn'],
                'Actions': self.QS_DATASET_ACTIONS
            }]
        )
        try:
            self.qs.create_data_set(**params)
            print(f"✓ 用户概况数据集创建成功 (SPICE 模式)")
        except self.qs.exceptions.ResourceExistsException:
            del params['Permissions']
            self.qs.update_data_set(**params)
            print(f"✓ 用户概况数据集已更新 (SPICE 模式)")
        self._trigger_ingestion('kiro-user-summary-dataset')
        self._create_refresh_schedule('kiro-user-summary-dataset', 'summary-daily-refresh')
        return 'kiro-user-summary-dataset'

    def create_credit_summary_dataset(self, data_source_id):
        """创建 Credit 汇总数据集（基于 Athena 视图 credit_summary，含序号）"""
        ds_arn = f"arn:aws:quicksight:{self.config['aws']['region']}:{self.account_id}:datasource/{data_source_id}"
        db = self.config['glue']['database_name']
        params = dict(
            AwsAccountId=self.account_id,
            DataSetId='kiro-credit-summary-dataset',
            Name='KiroCreditSummaryDataset',
            PhysicalTableMap={
                'creditsummary': {
                    'RelationalTable': {
                        'DataSourceArn': ds_arn, 'Catalog': 'AwsDataCatalog',
                        'Schema': db, 'Name': 'credit_summary',
                        'InputColumns': [
                            {'Name': 'row_num', 'Type': 'INTEGER'},
                            {'Name': 'username', 'Type': 'STRING'},
                            {'Name': 'subscription_tier', 'Type': 'STRING'},
                            {'Name': 'client_type', 'Type': 'STRING'},
                            {'Name': 'total_credits', 'Type': 'DECIMAL'},
                            {'Name': 'total_overage', 'Type': 'DECIMAL'},
                            {'Name': 'overage_cap', 'Type': 'DECIMAL'},
                            {'Name': 'total_messages', 'Type': 'INTEGER'},
                        ]
                    }
                }
            },
            LogicalTableMap={
                'credit-summary-base': {
                    'Alias': 'creditsummary',
                    'Source': {'PhysicalTableId': 'creditsummary'},
                }
            },
            ImportMode='SPICE',
            Permissions=[{
                'Principal': self.config['quicksight']['user_arn'],
                'Actions': self.QS_DATASET_ACTIONS
            }]
        )
        try:
            self.qs.create_data_set(**params)
            print(f"✓ Credit 汇总数据集创建成功 (SPICE 模式)")
        except self.qs.exceptions.ResourceExistsException:
            del params['Permissions']
            self.qs.update_data_set(**params)
            print(f"✓ Credit 汇总数据集已更新 (SPICE 模式)")
        self._trigger_ingestion('kiro-credit-summary-dataset')
        self._create_refresh_schedule('kiro-credit-summary-dataset', 'credit-summary-daily-refresh')
        return 'kiro-credit-summary-dataset'

    def _trigger_ingestion(self, dataset_id):
        """触发 SPICE 数据导入"""
        import time
        ingestion_id = f"initial-{int(time.time())}"
        try:
            self.qs.create_ingestion(
                AwsAccountId=self.account_id,
                DataSetId=dataset_id,
                IngestionId=ingestion_id
            )
            print(f"  ✓ SPICE 导入已触发: {dataset_id}")
        except Exception as e:
            print(f"  ⚠ SPICE 导入触发跳过: {e}")

    def _create_refresh_schedule(self, dataset_id, schedule_id):
        """创建每日 SPICE 刷新计划（UTC 4:00，在 user_mapping 同步之后）"""
        schedule = {
            'ScheduleId': schedule_id,
            'ScheduleFrequency': {
                'Interval': 'DAILY',
                'TimeOfTheDay': '04:00',
            },
            'RefreshType': 'FULL_REFRESH',
        }
        try:
            self.qs.create_refresh_schedule(
                AwsAccountId=self.account_id,
                DataSetId=dataset_id,
                Schedule=schedule
            )
            print(f"  ✓ 每日刷新计划已创建: {schedule_id} (UTC 04:00)")
        except Exception as e:
            if 'already exists' in str(e).lower() or 'ResourceExists' in str(e):
                try:
                    self.qs.update_refresh_schedule(
                        AwsAccountId=self.account_id,
                        DataSetId=dataset_id,
                        Schedule=schedule
                    )
                    print(f"  ✓ 每日刷新计划已更新: {schedule_id} (UTC 04:00)")
                except Exception as e2:
                    print(f"  ⚠ 刷新计划更新跳过: {e2}")
            else:
                print(f"  ⚠ 刷新计划创建跳过: {e}")

    def deploy_all(self):
        """部署所有资源"""
        print("开始部署 QuickSight 资源...\n")

        # 1. 创建数据源
        data_source_id = self.create_data_source()

        # 2. 创建数据集 (SPICE 模式)
        dataset_id = self.create_dataset(data_source_id)
        credits_dataset_id = self.create_credits_dataset(data_source_id)
        summary_dataset_id = self.create_summary_dataset(data_source_id)
        credit_summary_dataset_id = self.create_credit_summary_dataset(data_source_id)

        print("\n✓ 数据源和数据集部署完成 (SPICE 模式，每日自动刷新)")
        print(f"\n访问 QuickSight 控制台查看: https://{self.config['aws']['region']}.quicksight.aws.amazon.com/")

if __name__ == '__main__':
    deployer = QuickSightDeployer()
    deployer.deploy_all()
