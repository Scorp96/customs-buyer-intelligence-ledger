# Customs Buyer Intelligence Network v2.1

杩欐槸缁欒嚜瀹氫箟 GPT 浣跨敤鐨勭綉缁滆处鏈拰閭欢闃茬伀澧欍€傚畠涓嶈皟鐢?OpenAI API锛屽洜姝ゆ湰椤圭洰鏈韩涓嶄骇鐢?OpenAI API 璐圭敤銆侰hatGPT 璐熻矗璋冩煡涓庢帹鐞嗭紱鏈湇鍔¤礋璐ｈ法鑱婂ぉ淇濆瓨銆佸幓閲嶅悎骞躲€佽瘉鎹害鏉熷拰閭欢缁堟€佹牎楠屻€?
## 涓€銆佸厛澶勭悊璐﹀彿瀹夊叏

濡傛灉瀵嗙爜鏇惧嚭鐜板湪鎴浘銆佽亰澶╂垨浠讳綍鍏紑浣嶇疆锛屽畠宸茬粡涓嶈兘缁х画浣跨敤銆傝鍏堬細

1. 鍐嶆淇敼 GitHub 鍜?Render 瀵嗙爜锛屼袱涓钩鍙颁娇鐢ㄤ笉鍚屽瘑鐮侊紱
2. 寮€鍚袱姝ラ獙璇侊紱
3. 涓嶆妸瀵嗙爜鍐欒繘浠ｇ爜銆佺煡璇嗘枃浠躲€丟itHub浠撳簱鎴?Render锛?4. 鍚庣画鍙娇鐢ㄢ€滅粏绮掑害 GitHub Token鈥濓紝涓斿彧鎺堟潈鏈」鐩殑涓€涓鏈変粨搴撱€?
鏈湇鍔′笉闇€瑕?GitHub 鎴?Render 鐧诲綍瀵嗙爜銆?
## 浜屻€佸寘鍐呮枃浠舵€庝箞鐢?
| 鏂囦欢 | 鐢ㄩ€?|
|---|---|
| `01-Custom-GPT-Instructions-v2.1.txt` | 澶嶅埗鍒拌嚜瀹氫箟 GPT 鐨勨€淚nstructions/鎸囦护鈥濊緭鍏ユ锛涗笉鏄笂浼犲埌鐭ヨ瘑搴?|
| `02-Knowledge-Reference-v2.1.md` | 涓婁紶鍒拌嚜瀹氫箟 GPT 鐨勨€淜nowledge/鐭ヨ瘑鈥?|
| `openapi-action.yaml` | Action鎺ュ彛澶囦唤锛涢儴缃插悗浼樺厛浠庢湇鍔＄殑 `/openapi.json` 瀵煎叆 |
| `main.py`銆乣app/` | 缃戠粶鏈嶅姟浠ｇ爜 |
| `render.yaml` | Render鑷姩閮ㄧ讲閰嶇疆 |
| `tests/` | 闃查仐婕忋€侀槻璇€€淇″拰閭欢闃绘鍥炲綊娴嬭瘯 |

涓嶈鎶婃暣涓猌IP涓婁紶鍒?GPT 鐭ヨ瘑搴擄紝涔熶笉瑕佸湪姣忎釜鏂拌亰澶╁彂閫?`.py` 鏂囦欢銆備唬鐮侀儴缃蹭竴娆″悗锛孏PT閫氳繃 Action 鑷姩璋冪敤銆?
## 涓夈€佸垱寤虹鏈?GitHub 浠撳簱

1. 鐧诲綍 GitHub锛屽彸涓婅 `+` 鈫?`New repository`銆?2. 浠撳簱鍚嶅缓璁細`customs-buyer-intelligence-ledger`銆?3. 閫夋嫨 `Private`銆?4. 鍒涘缓浠撳簱鍚庯紝鎶婃湰鏂囦欢鎵€鍦ㄦ枃浠跺す涓殑鍏ㄩ儴椤圭洰鏂囦欢涓婁紶鍒颁粨搴撴牴鐩綍銆?5. 纭鏍圭洰褰曠洿鎺ョ湅寰楀埌 `main.py`銆乣render.yaml` 鍜?`requirements.txt`锛屼笉瑕佸濂椾竴灞傛枃浠跺す銆?
GitHub瀹樻柟涓婁紶璇存槑锛?https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository?platform=windows>

## 鍥涖€佸垱寤烘渶灏忔潈闄?GitHub Token

1. GitHub澶村儚 鈫?`Settings`銆?2. 宸︿晶鏈€涓嬫柟 `Developer settings`銆?3. `Personal access tokens` 鈫?`Fine-grained tokens` 鈫?`Generate new token`銆?4. Token鍚嶇О寤鸿锛歚render-ledger-writer`銆?5. 璁剧疆鍚堢悊杩囨湡鏃ワ紱鍒版湡鍓嶆洿鏂?Render 涓殑浠ょ墝銆?6. Repository access 閫夋嫨 `Only select repositories`锛屽彧閫夋嫨鍒氭墠鐨勭鏈変粨搴撱€?7. Repository permissions鍙紑鍚細`Contents: Read and write`銆侻etadata淇濇寔绯荤粺瑕佹眰鐨勫彧璇诲嵆鍙€?8. 鐢熸垚鍚庡彧澶嶅埗涓€娆★紝鏀惧叆瀵嗙爜绠＄悊鍣紱涓嶈鍙戦€佸埌鑱婂ぉ銆?
瀹樻柟浠ょ墝璇存槑锛?https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens>

## 浜斻€佸湪 Render 閮ㄧ讲

鏈€鐪佷簨鐨勬柟娉曟槸 Blueprint锛?
1. 鐧诲綍 Render锛岄€夋嫨 `New` 鈫?`Blueprint`銆?2. 杩炴帴鍒氭墠鐨?GitHub 绉佹湁浠撳簱銆?3. Render璇诲彇鏍圭洰褰曠殑 `render.yaml`銆?4. 鎸夋彁绀哄～鍐欑幆澧冨彉閲忥細

| 鍙橀噺 | 濉粈涔?|
|---|---|
| `GITHUB_REPOSITORY` | `浣犵殑GitHub鐢ㄦ埛鍚?customs-buyer-intelligence-ledger` |
| `GITHUB_TOKEN` | 绗洓姝ョ敓鎴愮殑缁嗙矑搴︿护鐗?|
| `ACTION_API_KEY` | 鍙﹁鐢熸垚鐨勪竴涓茶嚦灏?2瀛楄妭闅忔満瀵嗛挜锛屼笉鑳戒笌缃戠珯瀵嗙爜鐩稿悓 |
| `PUBLIC_BASE_URL` | 棣栨鍙殏濉?`https://YOUR-SERVICE.onrender.com`锛涙湇鍔″垱寤哄悗鎹㈡垚鐪熷疄缃戝潃 |

5. 瀹屾垚閮ㄧ讲鍚庡鍒?Render 缁欏嚭鐨勫湴鍧€锛屼緥濡?`https://customs-buyer-intelligence-ledger.onrender.com`銆?6. 鎶?`PUBLIC_BASE_URL` 鏀逛负杩欎釜鐪熷疄鍦板潃骞朵繚瀛橈紱Render浼氶噸鏂伴儴缃层€?7. 娴忚鍣ㄨ闂?`浣犵殑鍦板潃/health`銆傜湅鍒?`"status":"ok"` 鎵嶇畻鍚庣閮ㄧ讲鎴愬姛銆?
Render瀹樻柟FastAPI娴佺▼锛?https://render.com/docs/deploy-fastapi>

### 鍏嶈垂鐗堢殑閲嶈闄愬埗

Render褰撳墠瀹樻柟璇存槑锛氬厤璐筗eb鏈嶅姟鍦?5鍒嗛挓鏃犺姹傚悗浼戠湢锛屼笅涓€娆″敜閱掔害闇€涓€鍒嗛挓锛涘厤璐规湇鍔℃湰鍦版枃浠剁郴缁熶細鍦ㄩ噸鍚€佷紤鐪犳垨閲嶆柊閮ㄧ讲鏃朵涪澶便€傚洜姝ゆ湰椤圭洰涓嶆妸璐︽湰鏀惧湪Render鏈湴锛岃€屾槸鍐欏叆绉佹湁GitHub浠撳簱鐨?`ledger-data` 鍒嗘敮銆傝瑙侊細<https://render.com/docs/free>

杩欐剰鍛崇潃绗竴娆ction璋冪敤鍙兘鎱紝浣嗚处鏈笉浼氬洜涓篟ender浼戠湢鑰屼涪澶便€傚厤璐归搴﹀拰鏉℃浠ュ悗鍙兘鏀瑰彉锛屽簲浠ender褰撴椂椤甸潰涓哄噯銆?
## 鍏€佹妸 Action 鍔犲埌鑷畾涔?GPT

OpenAI褰撳墠瑕佹眰 Action 閰嶇疆鍖呭惈鎺ュ彛璁よ瘉鍜?OpenAPI Schema锛汫PT涓嶈兘鍚屾椂浣跨敤Apps鍜孉ctions銆傚鏋滅紪杈戝櫒寮€鍚簡Apps锛屽厛鍏抽棴Apps銆傚畼鏂硅鏄庯細<https://help.openai.com/en/articles/9442513-configuring-actions-in-gpts>

1. 鎵撳紑鑷畾涔?GPT 缂栬緫鍣?鈫?`閰嶇疆`銆?2. 鎶?`01-Custom-GPT-Instructions-v2.1.txt` 鍏ㄦ枃澶嶅埗鍒扳€滄寚浠も€濄€?3. 鐭ヨ瘑搴撳彧涓婁紶 `02-Knowledge-Reference-v2.1.md`銆?4. 鎵惧埌 `Actions/鎿嶄綔` 鈫?`Create new action/鍒涘缓鏂版搷浣渀銆?5. Authentication閫夋嫨 `API Key` 鈫?`Custom header`銆?6. Header鍚嶇О濉啓锛歚X-Action-Key`銆?7. 瀵嗛挜濉啓 Render 涓浉鍚岀殑 `ACTION_API_KEY`銆?8. Schema浼樺厛閫夋嫨鈥滀粠URL瀵煎叆鈥濓紝杈撳叆锛?
   `https://浣犵殑鏈嶅姟.onrender.com/openapi.json`

9. 濡傛灉URL瀵煎叆澶辫触锛屾墦寮€鍖呭唴 `openapi-action.yaml`锛屾妸绗竴澶?`YOUR-SERVICE` 鎹㈡垚鐪熷疄鏈嶅姟鍚嶏紝鍐嶇矘璐村埌Schema妗嗐€?10. 闅愮鏀跨瓥URL濉啓锛?
    `https://浣犵殑鏈嶅姟.onrender.com/privacy`

11. 鍦ˋction娴嬭瘯涓厛杩愯 `getHealth`锛屽啀鐢ㄤ竴涓祴璇曞叕鍙歌繍琛?`lookupBuyerLedger`銆?
## 涓冦€侀娆″畬鏁撮獙鏀?
鏂板紑涓€涓亰澶╋紝鍙矘璐翠竴鏉℃捣鍏虫暟鎹紝涓嶅啀琛ヤ换浣曟彁绀鸿瘝銆傚悎鏍肩粨鏋滃繀椤绘弧瓒筹細

1. 璋冩煡寮€濮嬪墠鐪熷疄璋冪敤 `lookupBuyerLedger`锛?2. 鎵惧埌鍏徃鐨勫畼缃戙€佸湴鍥俱€佺ぞ濯掋€佹硶寰?鐧昏銆佸喅绛栬矾寰勫拰鍏ㄩ儴鍏紑鑱旂郴鏂瑰紡锛屽苟闄勭洿閾撅紱
3. 璋冩煡鍚庣湡瀹炶皟鐢?`mergeBuyerLedger`锛?4. 鎶ュ憡灞曠ず鏈嶅姟鍣ㄨ繑鍥炵殑 previous/added/total counts 鍜?ledger hash锛?5. 鏈夊悎鏍奸偖绠辨椂鐪熷疄璋冪敤 `validateOutreachDraft`锛?6. `SENDABLE_DRAFT` 鎵嶆樉绀?`mailto`锛?7. `DRAFT_BLOCKED` 鏃?To涓虹┖銆佹病鏈夊彲鐐瑰嚮閭欢閾炬帴锛?8. 绗簩娆¤皟鏌ュ悓涓€鍏徃鏃讹紝鏃ч偖绠变粛瀛樺湪锛屽苟鍙鍔犳柊閭锛?9. 鍗曚釜閭閫€淇″彧灏侀攣杩欎釜鍦板潃锛屼笉褰卞搷鍚屽煙鍏朵粬鍦板潃銆?
鑻ュ嚭鐜?`LEDGER_NOT_LOADED`锛屾鏌ender鏄惁浼戠湢骞剁瓑寰呯害涓€鍒嗛挓鍚庨噸璇曘€傝嫢鍑虹幇401锛屾鏌ヨ嚜瀹氫箟GPT鍜孯ender涓殑 `ACTION_API_KEY` 鏄惁瀹屽叏涓€鑷淬€傝嫢鍑虹幇503锛屾鏌itHub Token鏄惁杩囨湡銆佷粨搴撳悕绉版槸鍚﹀噯纭€佹槸鍚︽湁Contents璇诲啓鏉冮檺銆?
## 鍏€佷紒涓氬井淇￠偖绠辫鏄?
`mailto_url`鍙皟鐢╓indows榛樿閭欢绋嬪簭銆傝嫢浼佷笟寰俊閭鑳芥帴绠indows鐨?`MAILTO` 鍗忚锛屼細鎵撳紑鍏惰崏绋匡紱濡傛灉涓嶈兘锛孏PT浠嶄細鎻愪緵宸叉牳楠岀殑To銆佷富棰樺拰姝ｆ枃锛屼汉宸ュ鍒跺埌浼佷笟寰俊閭鍗冲彲銆?
璇ction缁濅笉鑷姩鍙戦€侊紝涔熶笉澹扮О宸茬粡鍦ㄦ湇鍔″櫒绔垱寤鸿崏绋裤€傜湡姝ｅ彂閫佺粨鏋滃繀椤荤敱鐢ㄦ埛纭鎴栭偖绠辫繛鎺ュ櫒鍥炴墽鍐欏洖璐︽湰銆?
## 涔濄€佹暟鎹笌闅愮

- 浠撳簱蹇呴』淇濇寔绉佹湁锛?- `GITHUB_TOKEN`鍜宍ACTION_API_KEY`鍙斁Render鐜鍙橀噺锛?- 涓嶆妸绉佷汉閭銆佹晱鎰熶釜浜鸿祫鏂欐垨鏃犲悎娉曚笟鍔′緷鎹殑鏁版嵁鍐欏叆璐︽湰锛?- 鍏紑鍟嗕笟鑱旂郴鏂瑰紡浠嶉渶閬靛畧鐩爣鍥藉鐨勯殣绉併€佸弽鍨冨溇閭欢鍜岃惀閿€瑙勫垯锛?- 鍒犻櫎鏌愭潯鏉愭枡鍓嶅厛纭鏄惁闇€瑕佷繚鐣欏璁″巻鍙层€?