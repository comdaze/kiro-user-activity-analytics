#!/usr/bin/env python3
"""
创建 QuickSight 可视化分析
- 管理概览 + 成本优化: 基于 user_report (credits 数据集)
- 用户行为 + 功能采用: 基于 by_user_analytic (行为数据集)
"""
import boto3
import yaml

config = yaml.safe_load(open('config.yaml'))
qs = boto3.client('quicksight', region_name=config['aws']['region'])
account_id = config['aws']['account_id']

ACTIVITY_DATASET = f"arn:aws:quicksight:{config['aws']['region']}:{account_id}:dataset/kiro-user-activity-dataset"
CREDITS_DATASET = f"arn:aws:quicksight:{config['aws']['region']}:{account_id}:dataset/kiro-user-credits-dataset"


def update_analysis(analysis_id, name, dataset_arn, dataset_id, sheets):
    """通用的 update_analysis 封装"""
    try:
        qs.update_analysis(
            AwsAccountId=account_id,
            AnalysisId=analysis_id,
            Name=name,
            Definition={
                'DataSetIdentifierDeclarations': [{
                    'Identifier': dataset_id,
                    'DataSetArn': dataset_arn
                }],
                'Sheets': sheets
            }
        )
        print(f"✓ {name} 更新成功")
    except Exception as e:
        print(f"✗ {name} 失败: {e}")


# ============================================
# 辅助函数: 构建 FieldWell
# ============================================
def kpi_visual(visual_id, title, dataset_id, column, agg='SUM'):
    col_ref = {'DataSetIdentifier': dataset_id, 'ColumnName': column}
    if agg == 'DISTINCT_COUNT':
        measure = {
            'CategoricalMeasureField': {
                'FieldId': visual_id,
                'Column': col_ref,
                'AggregationFunction': 'DISTINCT_COUNT'
            }
        }
    else:
        measure = {
            'NumericalMeasureField': {
                'FieldId': visual_id,
                'Column': col_ref,
                'AggregationFunction': {'SimpleNumericalAggregation': agg}
            }
        }
    return {
        'KPIVisual': {
            'VisualId': visual_id,
            'Title': {'Visibility': 'VISIBLE', 'FormatText': {'PlainText': title}},
            'ChartConfiguration': {
                'FieldWells': {
                    'Values': [measure]
                }
            }
        }
    }


def line_visual(visual_id, title, dataset_id, date_col, value_cols):
    """value_cols: list of (field_id, column_name, agg)"""
    values = []
    for fid, col, agg in value_cols:
        values.append({
            'NumericalMeasureField': {
                'FieldId': fid,
                'Column': {'DataSetIdentifier': dataset_id, 'ColumnName': col},
                'AggregationFunction': {'SimpleNumericalAggregation': agg}
            }
        })
    return {
        'LineChartVisual': {
            'VisualId': visual_id,
            'Title': {'Visibility': 'VISIBLE', 'FormatText': {'PlainText': title}},
            'ChartConfiguration': {
                'FieldWells': {
                    'LineChartAggregatedFieldWells': {
                        'Category': [{
                            'CategoricalDimensionField': {
                                'FieldId': 'date',
                                'Column': {'DataSetIdentifier': dataset_id, 'ColumnName': date_col}
                            }
                        }],
                        'Values': values
                    }
                }
            }
        }
    }


def bar_visual(visual_id, title, dataset_id, cat_col, value_cols, limit=None):
    """value_cols: list of (field_id, column_name, agg)"""
    values = []
    for fid, col, agg in value_cols:
        if agg == 'DISTINCT_COUNT':
            values.append({
                'CategoricalMeasureField': {
                    'FieldId': fid,
                    'Column': {'DataSetIdentifier': dataset_id, 'ColumnName': col},
                    'AggregationFunction': 'DISTINCT_COUNT'
                }
            })
        else:
            values.append({
                'NumericalMeasureField': {
                    'FieldId': fid,
                    'Column': {'DataSetIdentifier': dataset_id, 'ColumnName': col},
                    'AggregationFunction': {'SimpleNumericalAggregation': agg}
                }
            })
    config = {
        'FieldWells': {
            'BarChartAggregatedFieldWells': {
                'Category': [{
                    'CategoricalDimensionField': {
                        'FieldId': cat_col,
                        'Column': {'DataSetIdentifier': dataset_id, 'ColumnName': cat_col}
                    }
                }],
                'Values': values
            }
        }
    }
    if limit:
        config['SortConfiguration'] = {'CategoryItemsLimit': {'ItemsLimit': limit}}
    return {
        'BarChartVisual': {
            'VisualId': visual_id,
            'Title': {'Visibility': 'VISIBLE', 'FormatText': {'PlainText': title}},
            'ChartConfiguration': config
        }
    }


def table_visual(visual_id, title, dataset_id, group_cols, value_cols):
    """group_cols: list of column names, value_cols: list of (field_id, column_name, agg)"""
    groups = [{
        'CategoricalDimensionField': {
            'FieldId': col,
            'Column': {'DataSetIdentifier': dataset_id, 'ColumnName': col}
        }
    } for col in group_cols]
    values = [{
        'NumericalMeasureField': {
            'FieldId': fid,
            'Column': {'DataSetIdentifier': dataset_id, 'ColumnName': col},
            'AggregationFunction': {'SimpleNumericalAggregation': agg}
        }
    } for fid, col, agg in value_cols]
    return {
        'TableVisual': {
            'VisualId': visual_id,
            'Title': {'Visibility': 'VISIBLE', 'FormatText': {'PlainText': title}},
            'ChartConfiguration': {
                'FieldWells': {
                    'TableAggregatedFieldWells': {
                        'GroupBy': groups,
                        'Values': values
                    }
                }
            }
        }
    }


# ============================================
# 1. 管理概览 (基于 user_report - credits 数据集)
# ============================================
print("创建管理概览可视化...")
ds = 'dataset1'
update_analysis(
    'kiro-admin-overview-analysis', 'Kiro管理概览',
    CREDITS_DATASET, ds,
    [{
        'SheetId': 'sheet1',
        'Name': '概览',
        'Visuals': [
            kpi_visual('kpi-users', '总活跃用户', ds, 'userid', 'DISTINCT_COUNT'),
            kpi_visual('kpi-credits', '总 Credit 消耗', ds, 'credits_used', 'SUM'),
            kpi_visual('kpi-overage', '超额 Credit', ds, 'overage_credits_used', 'SUM'),
            kpi_visual('kpi-messages', '总消息数', ds, 'total_messages', 'SUM'),
            line_visual('line-credits', '每日 Credit 消耗趋势', ds, 'date',
                        [('credits', 'credits_used', 'SUM'),
                         ('overage', 'overage_credits_used', 'SUM')]),
            bar_visual('bar-top-credits', 'Top 10 Credit 消耗用户', ds, 'username',
                       [('credits', 'credits_used', 'SUM')], limit=10),
            bar_visual('bar-tier', '各订阅层级用户数', ds, 'subscription_tier',
                       [('users', 'userid', 'DISTINCT_COUNT')]),
            bar_visual('bar-client', '客户端类型分布', ds, 'client_type',
                       [('users', 'userid', 'DISTINCT_COUNT')]),
        ]
    }]
)

# ============================================
# 2. 成本优化 (基于 user_report - credits 数据集)
# ============================================
print("\n创建成本优化可视化...")
update_analysis(
    'kiro-cost-optimization-analysis', 'Kiro成本优化',
    CREDITS_DATASET, ds,
    [{
        'SheetId': 'sheet1',
        'Name': '成本分析',
        'Visuals': [
            kpi_visual('kpi-overage-users', '有超额的用户数', ds, 'userid', 'DISTINCT_COUNT'),
            kpi_visual('kpi-total-overage', '总超额 Credit', ds, 'overage_credits_used', 'SUM'),
            kpi_visual('kpi-avg-credits', '平均每用户 Credit', ds, 'credits_used', 'AVERAGE'),
            line_visual('line-overage', '每日超额趋势', ds, 'date',
                        [('overage', 'overage_credits_used', 'SUM')]),
            bar_visual('bar-tier-credits', '各层级平均 Credit 消耗', ds, 'subscription_tier',
                       [('avg_credits', 'credits_used', 'AVERAGE'),
                        ('avg_cap', 'overage_cap', 'AVERAGE')]),
            table_visual('table-cost', '用户 Credit 使用明细', ds,
                         ['username', 'subscription_tier', 'client_type'],
                         [('credits', 'credits_used', 'SUM'),
                          ('overage', 'overage_credits_used', 'SUM'),
                          ('cap', 'overage_cap', 'MAX'),
                          ('msgs', 'total_messages', 'SUM')]),
        ]
    }]
)


# ============================================
# 3. 用户行为分析 (基于 by_user_analytic - 行为数据集)
# ============================================
print("\n创建用户行为分析可视化...")
ds = 'dataset1'
update_analysis(
    'kiro-user-behavior-analysis', 'Kiro用户行为分析',
    ACTIVITY_DATASET, ds,
    [{
        'SheetId': 'sheet1',
        'Name': '行为分析',
        'Visuals': [
            kpi_visual('kpi-codelines', '总 AI 代码行数', ds, 'chat_aicodelines', 'SUM'),
            kpi_visual('kpi-inline-code', '总 Inline 代码行数', ds, 'inline_aicodelines', 'SUM'),
            kpi_visual('kpi-chat-msgs', '总 Chat 消息数', ds, 'chat_messagessent', 'SUM'),
            line_visual('line-code', '每日 AI 代码生成趋势', ds, 'date',
                        [('chat_code', 'chat_aicodelines', 'SUM'),
                         ('inline_code', 'inline_aicodelines', 'SUM')]),
            line_visual('line-acceptance', 'Inline 代码接受趋势', ds, 'date',
                        [('accepted', 'inline_acceptancecount', 'SUM'),
                         ('suggested', 'inline_suggestionscount', 'SUM')]),
            bar_visual('bar-top-code', 'Top 10 代码生成用户', ds, 'username',
                       [('chat_code', 'chat_aicodelines', 'SUM'),
                        ('inline_code', 'inline_aicodelines', 'SUM')], limit=10),
            table_visual('table-behavior', '用户行为明细', ds,
                         ['username'],
                         [('chat_msgs', 'chat_messagessent', 'SUM'),
                          ('chat_code', 'chat_aicodelines', 'SUM'),
                          ('inline_code', 'inline_aicodelines', 'SUM'),
                          ('inline_accept', 'inline_acceptancecount', 'SUM'),
                          ('inline_suggest', 'inline_suggestionscount', 'SUM')]),
        ]
    }]
)

# ============================================
# 4. 功能采用 (基于 by_user_analytic - 行为数据集)
# ============================================
print("\n创建功能采用可视化...")
update_analysis(
    'kiro-feature-adoption-analysis', 'Kiro功能采用',
    ACTIVITY_DATASET, ds,
    [{
        'SheetId': 'sheet1',
        'Name': '功能统计',
        'Visuals': [
            # Dev Agent
            line_visual('line-dev', 'Dev Agent 使用趋势', ds, 'date',
                        [('dev_gen', 'dev_generationeventcount', 'SUM'),
                         ('dev_accept', 'dev_acceptanceeventcount', 'SUM')]),
            # Test Generation
            line_visual('line-test', '测试生成趋势', ds, 'date',
                        [('test_events', 'testgeneration_eventcount', 'SUM'),
                         ('test_accepted', 'testgeneration_acceptedtests', 'SUM')]),
            # Code Review
            line_visual('line-review', '代码审查趋势', ds, 'date',
                        [('review_ok', 'codereview_succeededeventcount', 'SUM'),
                         ('review_findings', 'codereview_findingscount', 'SUM')]),
            # CodeFix
            line_visual('line-codefix', 'CodeFix 趋势', ds, 'date',
                        [('fix_gen', 'codefix_generationeventcount', 'SUM'),
                         ('fix_accept', 'codefix_acceptanceeventcount', 'SUM')]),
            # InlineChat
            line_visual('line-inlinechat', 'InlineChat 使用趋势', ds, 'date',
                        [('ic_total', 'inlinechat_totaleventcount', 'SUM'),
                         ('ic_accept', 'inlinechat_acceptanceeventcount', 'SUM')]),
            # Doc Generation
            line_visual('line-docgen', '文档生成趋势', ds, 'date',
                        [('doc_events', 'docgeneration_eventcount', 'SUM'),
                         ('doc_created', 'docgeneration_acceptedfilescreations', 'SUM')]),
            # Transformation
            line_visual('line-transform', '代码转换趋势', ds, 'date',
                        [('transform_events', 'transformation_eventcount', 'SUM'),
                         ('transform_lines', 'transformation_linesgenerated', 'SUM')]),
        ]
    }]
)

print(f"\n✅ 所有可视化创建完成！")
print(f"访问: https://{config['aws']['region']}.quicksight.aws.amazon.com/")
