# Customs Buyer Intelligence Network v2.1

这是给自定义 GPT 使用的网络账本和邮件防火墙。它不调用 OpenAI API，因此本项目本身不产生 OpenAI API 费用。ChatGPT 负责调查与推理；本服务负责跨聊天保存、去重合并、证据约束和邮件终态校验。

## 一、先处理账号安全

如果密码曾出现在截图、聊天或任何公开位置，它已经不能继续使用。请先：

1. 再次修改 GitHub 和 Render 密码，两个平台使用不同密码；
2. 开启两步验证；
3. 不把密码写进代码、知识文件、GitHub仓库或 Render；
4. 后续只使用“细粒度 GitHub Token”，且只授权本项目的一个私有仓库。

本服务不需要 GitHub 或 Render 登录密码。

## 二、包内文件怎么用

| 文件 | 用途 |
|---|---|
| `01-Custom-GPT-Instructions-v2.1.txt` | 复制到自定义 GPT 的“Instructions/指令”输入框；不是上传到知识库 |
| `02-Knowledge-Reference-v2.1.md` | 上传到自定义 GPT 的“Knowledge/知识” |
| `openapi-action.yaml` | Action接口备份；部署后优先从服务的 `/openapi.json` 导入 |
| `main.py`、`app/` | 网络服务代码 |
| `render.yaml` | Render自动部署配置 |
| `tests/` | 防遗漏、防误退信和邮件阻止回归测试 |

不要把整个ZIP上传到 GPT 知识库，也不要在每个新聊天发送 `.py` 文件。代码部署一次后，GPT通过 Action 自动调用。

## 三、创建私有 GitHub 仓库

1. 登录 GitHub，右上角 `+` → `New repository`。
2. 仓库名建议：`customs-buyer-intelligence-ledger`。
3. 选择 `Private`。
4. 创建仓库后，把本文件所在文件夹中的全部项目文件上传到仓库根目录。
5. 确认根目录直接看得到 `main.py`、`render.yaml` 和 `requirements.txt`，不要多套一层文件夹。

GitHub官方上传说明：<https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository?platform=windows>

## 四、创建最小权限 GitHub Token

1. GitHub头像 → `Settings`。
2. 左侧最下方 `Developer settings`。
3. `Personal access tokens` → `Fine-grained tokens` → `Generate new token`。
4. Token名称建议：`render-ledger-writer`。
5. 设置合理过期日；到期前更新 Render 中的令牌。
6. Repository access 选择 `Only select repositories`，只选择刚才的私有仓库。
7. Repository permissions只开启：`Contents: Read and write`。Metadata保持系统要求的只读即可。
8. 生成后只复制一次，放入密码管理器；不要发送到聊天。

官方令牌说明：<https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens>

## 五、在 Render 部署

最省事的方法是 Blueprint：

1. 登录 Render，选择 `New` → `Blueprint`。
2. 连接刚才的 GitHub 私有仓库。
3. Render读取根目录的 `render.yaml`。
4. 按提示填写环境变量：

| 变量 | 填什么 |
|---|---|
| `GITHUB_REPOSITORY` | `你的GitHub用户名/customs-buyer-intelligence-ledger` |
| `GITHUB_TOKEN` | 第四步生成的细粒度令牌 |
| `ACTION_API_KEY` | 另行生成的一串至少32字节随机密钥，不能与网站密码相同 |
| `PUBLIC_BASE_URL` | 首次可暂填 `https://YOUR-SERVICE.onrender.com`；服务创建后换成真实网址 |

5. 完成部署后复制 Render 给出的地址，例如 `https://customs-buyer-intelligence-ledger.onrender.com`。
6. 把 `PUBLIC_BASE_URL` 改为这个真实地址并保存；Render会重新部署。
7. 浏览器访问 `你的地址/health`。看到 `"status":"ok"` 才算后端部署成功。

Render官方FastAPI流程：<https://render.com/docs/deploy-fastapi>

### 免费版的重要限制

Render当前官方说明：免费Web服务在15分钟无请求后休眠，下一次唤醒约需一分钟；免费服务本地文件系统会在重启、休眠或重新部署时丢失。因此本项目不把账本放在Render本地，而是写入私有GitHub仓库的 `ledger-data` 分支。详见：<https://render.com/docs/free>

这意味着第一次Action调用可能慢，但账本不会因为Render休眠而丢失。免费额度和条款以后可能改变，应以Render当时页面为准。

## 六、把 Action 加到自定义 GPT

OpenAI当前要求 Action 配置包含接口认证和 OpenAPI Schema；GPT不能同时使用Apps和Actions。如果编辑器开启了Apps，先关闭Apps。官方说明：<https://help.openai.com/en/articles/9442513-configuring-actions-in-gpts>

1. 打开自定义 GPT 编辑器 → `配置`。
2. 把 `01-Custom-GPT-Instructions-v2.1.txt` 全文复制到“指令”。
3. 知识库只上传 `02-Knowledge-Reference-v2.1.md`。
4. 找到 `Actions/操作` → `Create new action/创建新操作`。
5. Authentication选择 `API Key` → `Custom header`。
6. Header名称填写：`X-Action-Key`。
7. 密钥填写 Render 中相同的 `ACTION_API_KEY`。
8. Schema优先选择“从URL导入”，输入：

   `https://你的服务.onrender.com/openapi.json`

9. 如果URL导入失败，打开包内 `openapi-action.yaml`，把第一处 `YOUR-SERVICE` 换成真实服务名，再粘贴到Schema框。
10. 隐私政策URL填写：

    `https://你的服务.onrender.com/privacy`

11. 在Action测试中先运行 `getHealth`，再用一个测试公司运行 `lookupBuyerLedger`。

## 七、首次完整验收

新开一个聊天，只粘贴一条海关数据，不再补任何提示词。合格结果必须满足：

1. 调查开始前真实调用 `lookupBuyerLedger`；
2. 找到公司的官网、地图、社媒、法律/登记、决策路径和全部公开联系方式，并附直链；
3. 调查后真实调用 `mergeBuyerLedger`；
4. 报告展示服务器返回的 previous/added/total counts 和 ledger hash；
5. 有合格邮箱时真实调用 `validateOutreachDraft`；
6. `SENDABLE_DRAFT` 才显示 `mailto`；
7. `DRAFT_BLOCKED` 时 To为空、没有可点击邮件链接；
8. 第二次调查同一公司时，旧邮箱仍存在，并只增加新邮箱；
9. 单个邮箱退信只封锁这个地址，不影响同域其他地址。

若出现 `LEDGER_NOT_LOADED`，检查Render是否休眠并等待约一分钟后重试。若出现401，检查自定义GPT和Render中的 `ACTION_API_KEY` 是否完全一致。若出现503，检查GitHub Token是否过期、仓库名称是否准确、是否有Contents读写权限。

## 八、企业微信邮箱说明

`mailto_url`只调用Windows默认邮件程序。若企业微信邮箱能接管Windows的 `MAILTO` 协议，会打开其草稿；如果不能，GPT仍会提供已核验的To、主题和正文，人工复制到企业微信邮箱即可。

该Action绝不自动发送，也不声称已经在服务器端创建草稿。真正发送结果必须由用户确认或邮箱连接器回执写回账本。

## 九、数据与隐私

- 仓库必须保持私有；
- `GITHUB_TOKEN`和`ACTION_API_KEY`只放Render环境变量；
- 不把私人邮箱、敏感个人资料或无合法业务依据的数据写入账本；
- 公开商业联系方式仍需遵守目标国家的隐私、反垃圾邮件和营销规则；
- 删除某条材料前先确认是否需要保留审计历史。
