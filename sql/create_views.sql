-- =============================================
-- 视图基于 by_user_analytic 表（详细行为数据，46 列）
-- 包含 KiroLogs + QDeveloperLogs 合并数据
-- =============================================

-- 增强视图：添加计算字段
CREATE OR REPLACE VIEW kiro_analytics.user_activity_enhanced AS
SELECT 
    date,
    userid,
    -- Chat 指标
    chat_aicodelines,
    chat_messagesinteracted,
    chat_messagessent,
    -- Inline 指标
    inline_aicodelines,
    inline_acceptancecount,
    inline_suggestionscount,
    -- CodeFix 指标
    codefix_acceptanceeventcount,
    codefix_acceptedlines,
    codefix_generatedlines,
    codefix_generationeventcount,
    -- CodeReview 指标
    codereview_failedeventcount,
    codereview_findingscount,
    codereview_succeededeventcount,
    -- Dev Agent 指标
    dev_acceptanceeventcount,
    dev_acceptedlines,
    dev_generatedlines,
    dev_generationeventcount,
    -- TestGeneration 指标
    testgeneration_acceptedlines,
    testgeneration_acceptedtests,
    testgeneration_eventcount,
    testgeneration_generatedlines,
    testgeneration_generatedtests,
    -- InlineChat 指标
    inlinechat_acceptanceeventcount,
    inlinechat_acceptedlineadditions,
    inlinechat_acceptedlinedeletions,
    inlinechat_totaleventcount,
    -- DocGeneration 指标
    docgeneration_eventcount,
    docgeneration_acceptedfilescreations,
    docgeneration_acceptedlineadditions,
    -- 计算字段
    CASE 
        WHEN chat_aicodelines + inline_aicodelines > 500 THEN 'Heavy'
        WHEN chat_aicodelines + inline_aicodelines > 50 THEN 'Medium'
        ELSE 'Light'
    END AS user_segment,

    CAST(inline_acceptancecount AS DOUBLE) / NULLIF(CAST(inline_suggestionscount AS DOUBLE), 0) * 100 AS inline_acceptance_rate_pct,

    CAST(chat_messagessent AS DOUBLE) / NULLIF(CAST(chat_messagesinteracted AS DOUBLE), 0) AS messages_per_interaction,

    chat_aicodelines + inline_aicodelines AS total_ai_codelines,

    date_format(date_parse(date, '%m-%d-%Y'), '%Y-%m') AS year_month,
    date_format(date_parse(date, '%m-%d-%Y'), '%W') AS day_of_week

FROM kiro_analytics.by_user_analytic;

-- 每日汇总视图
CREATE OR REPLACE VIEW kiro_analytics.daily_summary AS
SELECT 
    date,
    COUNT(DISTINCT userid) AS active_users,
    SUM(chat_messagessent) AS total_messages,
    SUM(chat_aicodelines) AS total_chat_codelines,
    SUM(inline_aicodelines) AS total_inline_codelines,
    SUM(chat_aicodelines + inline_aicodelines) AS total_ai_codelines,
    SUM(inline_acceptancecount) AS total_inline_accepted,
    SUM(inline_suggestionscount) AS total_inline_suggestions,
    SUM(testgeneration_eventcount) AS total_test_events,
    SUM(codereview_findingscount) AS total_review_findings
FROM kiro_analytics.by_user_analytic
GROUP BY date
ORDER BY date DESC;

-- Top 用户视图
CREATE OR REPLACE VIEW kiro_analytics.top_users AS
SELECT 
    userid,
    SUM(chat_aicodelines + inline_aicodelines) AS total_ai_codelines,
    SUM(chat_messagessent) AS total_messages,
    SUM(inline_acceptancecount) AS total_inline_accepted,
    SUM(inline_suggestionscount) AS total_inline_suggestions,
    SUM(testgeneration_eventcount) AS total_test_events,
    COUNT(DISTINCT date) AS active_days
FROM kiro_analytics.by_user_analytic
GROUP BY userid
ORDER BY total_ai_codelines DESC
LIMIT 100;

-- =============================================
-- 视图基于 user_report 表（用户汇总数据，11 列）
-- 包含 Credits / Subscription / Overage 信息
-- =============================================

-- 用户 Credits 使用视图
CREATE OR REPLACE VIEW kiro_analytics.user_credits_enhanced AS
SELECT 
    date,
    userid,
    client_type,
    subscription_tier,
    profileid,
    total_messages,
    chat_conversations,
    credits_used,
    overage_enabled,
    overage_cap,
    overage_credits_used,

    CAST(credits_used AS DOUBLE) / NULLIF(CAST(overage_cap AS DOUBLE), 0) * 100 AS credit_utilization_pct,

    CASE 
        WHEN credits_used > overage_cap THEN 'Over Limit'
        WHEN CAST(credits_used AS DOUBLE) / NULLIF(CAST(overage_cap AS DOUBLE), 0) > 0.8 THEN 'Warning'
        ELSE 'Normal'
    END AS usage_status,

    CAST(credits_used AS DOUBLE) / NULLIF(CAST(total_messages AS DOUBLE), 0) AS credits_per_message,

    overage_credits_used * 0.04 AS overage_cost_usd,

    date_format(date_parse(date, '%Y-%m-%d'), '%Y-%m') AS year_month

FROM kiro_analytics.user_report;

-- 订阅层级汇总
CREATE OR REPLACE VIEW kiro_analytics.tier_summary AS
SELECT 
    subscription_tier,
    COUNT(DISTINCT userid) AS user_count,
    SUM(credits_used) AS total_credits,
    AVG(credits_used) AS avg_credits,
    SUM(overage_credits_used) AS total_overage,
    SUM(overage_credits_used * 0.04) AS total_overage_cost_usd,
    COUNT(DISTINCT CASE WHEN overage_credits_used > 0 THEN userid END) AS users_with_overage
FROM kiro_analytics.user_report
GROUP BY subscription_tier;
