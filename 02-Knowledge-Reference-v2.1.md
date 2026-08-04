# Customs Buyer Intelligence Knowledge Reference v2.1

本文件提供网络账本字段、证据等级、调查模板、Action调用契约和回归标准。行为约束以 `01-Custom-GPT-Instructions-v2.1.txt` 为最高规则。

## 1. Action 调用顺序

```text
lookupBuyerLedger
  -> current web research
  -> mergeBuyerLedger
  -> full report
  -> validateOutreachDraft
  -> show SENDABLE_DRAFT or DRAFT_BLOCKED
```

只有发生用户确认、上传记录或真实连接器回执时才调用 `recordOutreachEvent`。

### 失败状态

| 失败点 | 必须显示 | 禁止声称 |
|---|---|---|
| lookup失败/未调用 | LEDGER_NOT_LOADED | 已读取历史、全量旧邮箱 |
| merge失败/未调用 | LEDGER_NOT_SAVED | 已同步、永久保存、CRM已更新 |
| validate失败/未调用 | OUTREACH_VALIDATOR_UNAVAILABLE | 已通过邮件防火墙、可一键发送 |

## 2. 证据结构

```yaml
evidence_id: stable-run-local-id
claim: 单一、可审计的陈述
claim_class: FACT | INFERENCE | HYPOTHESIS | RECOMMENDATION | UNKNOWN
source_type: government_registry | official_domain | official_social | court_or_regulator | trade_database | professional_source | third_party_directory | user_input | uploaded_record | connector_receipt
source_reference: 人工可理解的来源名称或用户消息定位
source_url: 外部公开来源必须填写直链
source_date: 页面或记录日期，未知可空
checked_at: ISO 8601
evidence_grade: A1 | A2 | B1 | B2 | C1 | C2 | D
boundary: 该证据不能证明什么
conflict: 冲突证据说明，若无可空
```

### 证据等级

| 等级 | 来源 | 主要用途 |
|---|---|---|
| A1 | 政府登记、监管、法院、官方数据库 | 法律名称、注册状态、正式案件 |
| A2 | 当前官网、官方文件、官方社媒 | 业务、产品、地址、官方联系方式 |
| B1 | 海关/贸易记录或强独立一手记录 | 特定贸易事件与有限连续性 |
| B2 | 可靠媒体、职业平台、行业文件 | 人员和市场线索，需当前性核验 |
| C1 | 当前结构化目录 | 联系或身份线索 |
| C2 | 历史/弱目录/旧文件 | VERIFY_ONLY |
| D | 搜索摘要、模型推理、无来源断言 | 只能作为发现线索 |

## 3. 买家、贸易与联系人模型

### BuyerIdentity

```yaml
legal_name: 当前核验法律名称
customs_name: 海关原始采购商名称
country: 国家/司法辖区
address: 当前证据支持的地址
aliases: 别名数组
business_type: 有证据边界的业务定位
source_ids: 支持身份字段的 evidence_id 数组
```

法律主体、品牌、商业运营点、importer_of_record、notify_party、procurement_center、inventory_owner 分开保存。共享地址、电话、域名或人员只说明可能相关，不能自动证明股权控制。

### TradeRecord

```yaml
record_id: 提单/申报/行项目稳定标识；没有可空
date: 记录日期
master_bill: 主单号
house_bill: 分单号
declaration_number: 申报号
item_number: 行项目
buyer: 原始买家
supplier_or_exporter: 原始供应商/出口商
product_raw: 产品原文
normalized_product: 审核后的产品分类
quantity: 数量
uom: 原始单位
weight_kg: 重量
provider: 数据提供方
data_level: shipment | bill | declaration | item | unknown
date_semantics: 日期的含义和限制
source_ids: 至少一个 evidence_id
```

去重顺序：record_id；其次 master/house/declaration/item 组合；再使用日期+买家+供应商+产品+数量+单位+重量哈希。冲突字段保留证据，不强行解释。

### ContactRecord

```yaml
email: 完整邮箱
person_name: 姓名，可空
title_as_sourced: 来源原始职位，可空
entity: 所属主体
first_seen: 首次发现时间
last_checked: 最近核验时间
verification_status: official_current | user_confirmed_current | directory_current | historical | inferred | bounced_specific_address | missing
employment_status: current | historical | unknown | not_applicable
procurement_authority_status: confirmed | unverified | not_procurement
route_class: DIRECT_PROCUREMENT | FORMAL_GENERAL | ALTERNATIVE_REFERRAL | VERIFY_ONLY | DO_NOT_USE
risk_note: 风险说明
recommended_use: 建议用途
source_ids: 至少一个 evidence_id
privacy_class: public_business | private_or_sensitive
```

## 4. mergeBuyerLedger 审计回执

成功响应必须被原样用于报告：

```text
status: LEDGER_MERGED
buyer_key:
created:
previous_counts: trade / email / evidence
submitted_counts: trade / email / evidence
added_counts: trade / email / evidence
updated_counts: trade / email / evidence
total_counts: trade / email / evidence
ledger_hash:
ledger_updated_at:
warnings:
```

不得把模型自己计算的数量冒充服务器回执。旧记录采用并集，联系人按规范化完整邮箱合并；缺少的旧邮箱不会被删除。
同一 `evidence_id` 如果对应不同内容，服务器拒绝合并，必须换用新的唯一ID，以免旧证据被覆盖或新记录绑错来源。

## 5. 历史事件写入

```yaml
buyer_key: lookup/merge真实返回
event_type: sent | bounced | replied | crm_created | rating_changed
target: 具体邮箱、账户或消息
event_time: ISO 8601
source_type: user_confirmed | uploaded_record | connector_receipt
source_reference: 证据说明或回执ID
details: 可选结构化详情
```

旧聊天摘要和模型记忆不能写入历史事件。退信 target 必须是具体完整邮箱；服务器只封锁该地址。

## 6. validateOutreachDraft 输入

```yaml
outreach_recommended: true/false
recipient: 主收件人；不合格时留空
recipient_status: verification status
subject: 主题
body: 客户语言正文+固定英文签名
chinese_translation: 中文审核译文
firewall_passed: 事实与卖方能力防火墙是否通过
human_style_passed: 是否达到真人短邮件标准
discovered_email_count: 本轮全量去重邮箱数量
recipient_routes:
  - recipient: 完整邮箱
    recipient_status: 状态
    route_class: 唯一分类
    role: 原始角色
    source_reference: 来源URL或用户确认
time_plan: IANA时区、当地窗口、北京时间、DST、假日核验
block_reasons: 已知阻止原因
```

服务器会强制检查：邮箱全量表数量一致；主地址必须在表中；只有 official_current / user_confirmed_current 且路由可发送；无 VERIFY_ONLY/DO_NOT_USE；有主题、正文和中文译文；通过防火墙；首封不超过180词、最多3个问题和3个项目符号；无明显无依据承诺。

### 服务器终态

```text
SENDABLE_DRAFT:
  to: 所有合格可发送地址的去重并集
  mailto_url: 可点击但只打开本地草稿

DRAFT_BLOCKED:
  to: ""
  mailto_url: null
  sendable_recipient_union: []
  block_reasons: 必须解决的问题
```

## 7. 调查报告验收表

### A. 决策摘要

- 真实业务性质；
- commercial_value / product_demand / product_fit / decision_route / outreach_readiness / crm_priority；
- 最强证据、最大风险、反向可能；
- 邮件终态；
- 唯一下一动作和验收标准。

### B. 执行层

- 法律主体与关联实体；
- 决策人路径；
- 全量邮箱表与来源直链；
- 电话、表单、WhatsApp/Zalo、LinkedIn、Facebook、Instagram、X、YouTube；
- Google Maps搜索或已核验Business链接，并明确二者区别；
- 去重贸易记录与供应商角色；
- CRM可录入字段；
- 网络账本回执。

### C. 证据附录

- 海关字段冲突与污染；
- 产品语义；
- 计算公式与边界；
- 贸易连续性；
- 法律检索；
- 来源URL、日期、证据等级；
- UNKNOWN与验证方法。

## 8. 兴怀能力边界

可确认卖方身份：

- Mark Zhou
- Guangzhou XingHuai New Materials Co., Ltd.
- Mobile / WhatsApp: +86 180 2710 1852
- www.xinghuai.com

历史检测线索只绑定受检样品：2024 PVC crust board 的旧版 GB 28481-2012 相关项目；2023受检PVC foam board板面握螺钉力860N；2021 10mm样品的部分限制物质ND；XF1402543封面显示90×250×15mm样品但标准和结果待完整报告。不得扩大到所有产品、当前认证或全系列合规。

## 9. 回归测试

每次更新后必须验证：

1. 无来源不得生成客户编号或历史评级。
2. 无用户确认/上传/连接器回执不得写“已发送/退信/回复”。
3. 旧账本1个邮箱+本轮1个新邮箱=总表2个，旧地址不消失。
4. 一个地址退信不改变同域其他地址。
5. 外部公开证据无URL时 merge 拒绝。
6. trade/contact 引用不存在 evidence_id 时 merge 拒绝。
7. DRAFT_BLOCKED 的 To为空、mailto为null。
8. VERIFY_ONLY不能成为正式收件人。
9. discovered_email_count 与路由表不一致时阻止草稿。
10. 多个已核实合格邮箱全部进入可发送并集，不静默遗漏。
11. 不同法律主体不合并。
12. Action没有真实回执时不声称已加载/已保存/已验证。
