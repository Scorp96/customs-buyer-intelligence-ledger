# Customs Buyer Intelligence Knowledge Reference v2.1

鏈枃浠舵彁渚涚綉缁滆处鏈瓧娈点€佽瘉鎹瓑绾с€佽皟鏌ユā鏉裤€丄ction璋冪敤濂戠害鍜屽洖褰掓爣鍑嗐€傝涓虹害鏉熶互 `01-Custom-GPT-Instructions-v2.1.txt` 涓烘渶楂樿鍒欍€?
## 1. Action 璋冪敤椤哄簭

```text
lookupBuyerLedger
  -> current web research
  -> mergeBuyerLedger
  -> full report
  -> validateOutreachDraft
  -> show SENDABLE_DRAFT or DRAFT_BLOCKED
```

鍙湁鍙戠敓鐢ㄦ埛纭銆佷笂浼犺褰曟垨鐪熷疄杩炴帴鍣ㄥ洖鎵ф椂鎵嶈皟鐢?`recordOutreachEvent`銆?
### 澶辫触鐘舵€?
| 澶辫触鐐?| 蹇呴』鏄剧ず | 绂佹澹扮О |
|---|---|---|
| lookup澶辫触/鏈皟鐢?| LEDGER_NOT_LOADED | 宸茶鍙栧巻鍙层€佸叏閲忔棫閭 |
| merge澶辫触/鏈皟鐢?| LEDGER_NOT_SAVED | 宸插悓姝ャ€佹案涔呬繚瀛樸€丆RM宸叉洿鏂?|
| validate澶辫触/鏈皟鐢?| OUTREACH_VALIDATOR_UNAVAILABLE | 宸查€氳繃閭欢闃茬伀澧欍€佸彲涓€閿彂閫?|

## 2. 璇佹嵁缁撴瀯

```yaml
evidence_id: stable-run-local-id
claim: 鍗曚竴銆佸彲瀹¤鐨勯檲杩?claim_class: FACT | INFERENCE | HYPOTHESIS | RECOMMENDATION | UNKNOWN
source_type: government_registry | official_domain | official_social | court_or_regulator | trade_database | professional_source | third_party_directory | user_input | uploaded_record | connector_receipt
source_reference: 浜哄伐鍙悊瑙ｇ殑鏉ユ簮鍚嶇О鎴栫敤鎴锋秷鎭畾浣?source_url: 澶栭儴鍏紑鏉ユ簮蹇呴』濉啓鐩撮摼
source_date: 椤甸潰鎴栬褰曟棩鏈燂紝鏈煡鍙┖
checked_at: ISO 8601
evidence_grade: A1 | A2 | B1 | B2 | C1 | C2 | D
boundary: 璇ヨ瘉鎹笉鑳借瘉鏄庝粈涔?conflict: 鍐茬獊璇佹嵁璇存槑锛岃嫢鏃犲彲绌?```

### 璇佹嵁绛夌骇

| 绛夌骇 | 鏉ユ簮 | 涓昏鐢ㄩ€?|
|---|---|---|
| A1 | 鏀垮簻鐧昏銆佺洃绠°€佹硶闄€佸畼鏂规暟鎹簱 | 娉曞緥鍚嶇О銆佹敞鍐岀姸鎬併€佹寮忔浠?|
| A2 | 褰撳墠瀹樼綉銆佸畼鏂规枃浠躲€佸畼鏂圭ぞ濯?| 涓氬姟銆佷骇鍝併€佸湴鍧€銆佸畼鏂硅仈绯绘柟寮?|
| B1 | 娴峰叧/璐告槗璁板綍鎴栧己鐙珛涓€鎵嬭褰?| 鐗瑰畾璐告槗浜嬩欢涓庢湁闄愯繛缁€?|
| B2 | 鍙潬濯掍綋銆佽亴涓氬钩鍙般€佽涓氭枃浠?| 浜哄憳鍜屽競鍦虹嚎绱紝闇€褰撳墠鎬ф牳楠?|
| C1 | 褰撳墠缁撴瀯鍖栫洰褰?| 鑱旂郴鎴栬韩浠界嚎绱?|
| C2 | 鍘嗗彶/寮辩洰褰?鏃ф枃浠?| VERIFY_ONLY |
| D | 鎼滅储鎽樿銆佹ā鍨嬫帹鐞嗐€佹棤鏉ユ簮鏂█ | 鍙兘浣滀负鍙戠幇绾跨储 |

## 3. 涔板銆佽锤鏄撲笌鑱旂郴浜烘ā鍨?
### BuyerIdentity

```yaml
legal_name: 褰撳墠鏍搁獙娉曞緥鍚嶇О
customs_name: 娴峰叧鍘熷閲囪喘鍟嗗悕绉?country: 鍥藉/鍙告硶杈栧尯
address: 褰撳墠璇佹嵁鏀寔鐨勫湴鍧€
aliases: 鍒悕鏁扮粍
business_type: 鏈夎瘉鎹竟鐣岀殑涓氬姟瀹氫綅
source_ids: 鏀寔韬唤瀛楁鐨?evidence_id 鏁扮粍
```

娉曞緥涓讳綋銆佸搧鐗屻€佸晢涓氳繍钀ョ偣銆乮mporter_of_record銆乶otify_party銆乸rocurement_center銆乮nventory_owner 鍒嗗紑淇濆瓨銆傚叡浜湴鍧€銆佺數璇濄€佸煙鍚嶆垨浜哄憳鍙鏄庡彲鑳界浉鍏筹紝涓嶈兘鑷姩璇佹槑鑲℃潈鎺у埗銆?
### TradeRecord

```yaml
record_id: 鎻愬崟/鐢虫姤/琛岄」鐩ǔ瀹氭爣璇嗭紱娌℃湁鍙┖
date: 璁板綍鏃ユ湡
master_bill: 涓诲崟鍙?house_bill: 鍒嗗崟鍙?declaration_number: 鐢虫姤鍙?item_number: 琛岄」鐩?buyer: 鍘熷涔板
supplier_or_exporter: 鍘熷渚涘簲鍟?鍑哄彛鍟?product_raw: 浜у搧鍘熸枃
normalized_product: 瀹℃牳鍚庣殑浜у搧鍒嗙被
quantity: 鏁伴噺
uom: 鍘熷鍗曚綅
weight_kg: 閲嶉噺
provider: 鏁版嵁鎻愪緵鏂?data_level: shipment | bill | declaration | item | unknown
date_semantics: 鏃ユ湡鐨勫惈涔夊拰闄愬埗
source_ids: 鑷冲皯涓€涓?evidence_id
```

鍘婚噸椤哄簭锛歳ecord_id锛涘叾娆?master/house/declaration/item 缁勫悎锛涘啀浣跨敤鏃ユ湡+涔板+渚涘簲鍟?浜у搧+鏁伴噺+鍗曚綅+閲嶉噺鍝堝笇銆傚啿绐佸瓧娈典繚鐣欒瘉鎹紝涓嶅己琛岃В閲娿€?
### ContactRecord

```yaml
email: 瀹屾暣閭
person_name: 濮撳悕锛屽彲绌?title_as_sourced: 鏉ユ簮鍘熷鑱屼綅锛屽彲绌?entity: 鎵€灞炰富浣?first_seen: 棣栨鍙戠幇鏃堕棿
last_checked: 鏈€杩戞牳楠屾椂闂?verification_status: official_current | user_confirmed_current | directory_current | historical | inferred | bounced_specific_address | missing
employment_status: current | historical | unknown | not_applicable
procurement_authority_status: confirmed | unverified | not_procurement
route_class: DIRECT_PROCUREMENT | FORMAL_GENERAL | ALTERNATIVE_REFERRAL | VERIFY_ONLY | DO_NOT_USE
risk_note: 椋庨櫓璇存槑
recommended_use: 寤鸿鐢ㄩ€?source_ids: 鑷冲皯涓€涓?evidence_id
privacy_class: public_business | private_or_sensitive
```

## 4. mergeBuyerLedger 瀹¤鍥炴墽

鎴愬姛鍝嶅簲蹇呴』琚師鏍风敤浜庢姤鍛婏細

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

涓嶅緱鎶婃ā鍨嬭嚜宸辫绠楃殑鏁伴噺鍐掑厖鏈嶅姟鍣ㄥ洖鎵с€傛棫璁板綍閲囩敤骞堕泦锛岃仈绯讳汉鎸夎鑼冨寲瀹屾暣閭鍚堝苟锛涚己灏戠殑鏃ч偖绠变笉浼氳鍒犻櫎銆?鍚屼竴 `evidence_id` 濡傛灉瀵瑰簲涓嶅悓鍐呭锛屾湇鍔″櫒鎷掔粷鍚堝苟锛屽繀椤绘崲鐢ㄦ柊鐨勫敮涓€ID锛屼互鍏嶆棫璇佹嵁琚鐩栨垨鏂拌褰曠粦閿欐潵婧愩€?
## 5. 鍘嗗彶浜嬩欢鍐欏叆

```yaml
buyer_key: lookup/merge鐪熷疄杩斿洖
event_type: sent | bounced | replied | crm_created | rating_changed
target: 鍏蜂綋閭銆佽处鎴锋垨娑堟伅
event_time: ISO 8601
source_type: user_confirmed | uploaded_record | connector_receipt
source_reference: 璇佹嵁璇存槑鎴栧洖鎵D
details: 鍙€夌粨鏋勫寲璇︽儏
```

鏃ц亰澶╂憳瑕佸拰妯″瀷璁板繂涓嶈兘鍐欏叆鍘嗗彶浜嬩欢銆傞€€淇?target 蹇呴』鏄叿浣撳畬鏁撮偖绠憋紱鏈嶅姟鍣ㄥ彧灏侀攣璇ュ湴鍧€銆?
## 6. validateOutreachDraft 杈撳叆

```yaml
outreach_recommended: true/false
recipient: 涓绘敹浠朵汉锛涗笉鍚堟牸鏃剁暀绌?recipient_status: verification status
subject: 涓婚
body: 瀹㈡埛璇█姝ｆ枃+鍥哄畾鑻辨枃绛惧悕
chinese_translation: 涓枃瀹℃牳璇戞枃
firewall_passed: 浜嬪疄涓庡崠鏂硅兘鍔涢槻鐏鏄惁閫氳繃
human_style_passed: 鏄惁杈惧埌鐪熶汉鐭偖浠舵爣鍑?discovered_email_count: 鏈疆鍏ㄩ噺鍘婚噸閭鏁伴噺
recipient_routes:
  - recipient: 瀹屾暣閭
    recipient_status: 鐘舵€?    route_class: 鍞竴鍒嗙被
    role: 鍘熷瑙掕壊
    source_reference: 鏉ユ簮URL鎴栫敤鎴风‘璁?time_plan: IANA鏃跺尯銆佸綋鍦扮獥鍙ｃ€佸寳浜椂闂淬€丏ST銆佸亣鏃ユ牳楠?block_reasons: 宸茬煡闃绘鍘熷洜
```

鏈嶅姟鍣ㄤ細寮哄埗妫€鏌ワ細閭鍏ㄩ噺琛ㄦ暟閲忎竴鑷达紱涓诲湴鍧€蹇呴』鍦ㄨ〃涓紱鍙湁 official_current / user_confirmed_current 涓旇矾鐢卞彲鍙戦€侊紱鏃?VERIFY_ONLY/DO_NOT_USE锛涙湁涓婚銆佹鏂囧拰涓枃璇戞枃锛涢€氳繃闃茬伀澧欙紱棣栧皝涓嶈秴杩?80璇嶃€佹渶澶?涓棶棰樺拰3涓」鐩鍙凤紱鏃犳槑鏄炬棤渚濇嵁鎵胯銆?
### 鏈嶅姟鍣ㄧ粓鎬?
```text
SENDABLE_DRAFT:
  to: 鎵€鏈夊悎鏍煎彲鍙戦€佸湴鍧€鐨勫幓閲嶅苟闆?  mailto_url: 鍙偣鍑讳絾鍙墦寮€鏈湴鑽夌

DRAFT_BLOCKED:
  to: ""
  mailto_url: null
  sendable_recipient_union: []
  block_reasons: 蹇呴』瑙ｅ喅鐨勯棶棰?```

## 7. 璋冩煡鎶ュ憡楠屾敹琛?
### A. 鍐崇瓥鎽樿

- 鐪熷疄涓氬姟鎬ц川锛?- commercial_value / product_demand / product_fit / decision_route / outreach_readiness / crm_priority锛?- 鏈€寮鸿瘉鎹€佹渶澶ч闄┿€佸弽鍚戝彲鑳斤紱
- 閭欢缁堟€侊紱
- 鍞竴涓嬩竴鍔ㄤ綔鍜岄獙鏀舵爣鍑嗐€?
### B. 鎵ц灞?
- 娉曞緥涓讳綋涓庡叧鑱斿疄浣擄紱
- 鍐崇瓥浜鸿矾寰勶紱
- 鍏ㄩ噺閭琛ㄤ笌鏉ユ簮鐩撮摼锛?- 鐢佃瘽銆佽〃鍗曘€乄hatsApp/Zalo銆丩inkedIn銆丗acebook銆両nstagram銆乆銆乊ouTube锛?- Google Maps鎼滅储鎴栧凡鏍搁獙Business閾炬帴锛屽苟鏄庣‘浜岃€呭尯鍒紱
- 鍘婚噸璐告槗璁板綍涓庝緵搴斿晢瑙掕壊锛?- CRM鍙綍鍏ュ瓧娈碉紱
- 缃戠粶璐︽湰鍥炴墽銆?
### C. 璇佹嵁闄勫綍

- 娴峰叧瀛楁鍐茬獊涓庢薄鏌擄紱
- 浜у搧璇箟锛?- 璁＄畻鍏紡涓庤竟鐣岋紱
- 璐告槗杩炵画鎬э紱
- 娉曞緥妫€绱紱
- 鏉ユ簮URL銆佹棩鏈熴€佽瘉鎹瓑绾э紱
- UNKNOWN涓庨獙璇佹柟娉曘€?
## 8. 鍏存€€鑳藉姏杈圭晫

鍙‘璁ゅ崠鏂硅韩浠斤細

- Mark Zhou
- Guangzhou XingHuai New Materials Co., Ltd.
- Mobile / WhatsApp: +86 180 2710 1852
- www.xinghuai.com

鍘嗗彶妫€娴嬬嚎绱㈠彧缁戝畾鍙楁鏍峰搧锛?024 PVC crust board 鐨勬棫鐗?GB 28481-2012 鐩稿叧椤圭洰锛?023鍙楁PVC foam board鏉块潰鎻¤灪閽夊姏860N锛?021 10mm鏍峰搧鐨勯儴鍒嗛檺鍒剁墿璐∟D锛沊F1402543灏侀潰鏄剧ず90脳250脳15mm鏍峰搧浣嗘爣鍑嗗拰缁撴灉寰呭畬鏁存姤鍛娿€備笉寰楁墿澶у埌鎵€鏈変骇鍝併€佸綋鍓嶈璇佹垨鍏ㄧ郴鍒楀悎瑙勩€?
## 9. 鍥炲綊娴嬭瘯

姣忔鏇存柊鍚庡繀椤婚獙璇侊細

1. 鏃犳潵婧愪笉寰楃敓鎴愬鎴风紪鍙锋垨鍘嗗彶璇勭骇銆?2. 鏃犵敤鎴风‘璁?涓婁紶/杩炴帴鍣ㄥ洖鎵т笉寰楀啓鈥滃凡鍙戦€?閫€淇?鍥炲鈥濄€?3. 鏃ц处鏈?涓偖绠?鏈疆1涓柊閭=鎬昏〃2涓紝鏃у湴鍧€涓嶆秷澶便€?4. 涓€涓湴鍧€閫€淇′笉鏀瑰彉鍚屽煙鍏朵粬鍦板潃銆?5. 澶栭儴鍏紑璇佹嵁鏃燯RL鏃?merge 鎷掔粷銆?6. trade/contact 寮曠敤涓嶅瓨鍦?evidence_id 鏃?merge 鎷掔粷銆?7. DRAFT_BLOCKED 鐨?To涓虹┖銆乵ailto涓簄ull銆?8. VERIFY_ONLY涓嶈兘鎴愪负姝ｅ紡鏀朵欢浜恒€?9. discovered_email_count 涓庤矾鐢辫〃涓嶄竴鑷存椂闃绘鑽夌銆?10. 澶氫釜宸叉牳瀹炲悎鏍奸偖绠卞叏閮ㄨ繘鍏ュ彲鍙戦€佸苟闆嗭紝涓嶉潤榛橀仐婕忋€?11. 涓嶅悓娉曞緥涓讳綋涓嶅悎骞躲€?12. Action娌℃湁鐪熷疄鍥炴墽鏃朵笉澹扮О宸插姞杞?宸蹭繚瀛?宸查獙璇併€?