# LaTeX 书籍翻译工作流

独立的 oh-my-pi Agent Plugin。输入 **PDF / EPUB / MOBI / DjVu，含扫描版和混合文本/扫描页**；输出 LaTeX 编译的 PDF。适用于可授权处理、能够逐页核对来源的完整书籍；经用户明确授权也可处理残本或节选，但必须标明范围与缺失内容。不得将残本称为全书，不提供 DRM 绕过，也不将 OCR 或编译成功等同于译文可靠。

## 复制和显式激活

将整个 `translator/` 复制到目标项目的 `.agents/translator/` 或 `.omp/translator/`。已有同名目录时先审阅，不覆盖修改。进入目标项目，在新会话启动时同时显式加载插件与原生 hook：

```sh
omp --plugin-dir .agents/translator -e .agents/translator/hooks/pre/translator.ts
# 或：
omp --plugin-dir .omp/translator -e .omp/translator/hooks/pre/translator.ts
```

在 TUI 中提交 `/skill:book-translator` 及实际翻译任务。**复制、skill 发现或启动后的热重载本身都不能证明 hook 已加载**；若原会话启动时未加载，须按上述命令重启。`--plugin-dir` 注册 skill，`-e` 显式加载本包 hook；不需要修改全局 settings、安装全局 extension、仓库根指导文件或 `ref_repo/`。`--skills` 是已发现名称的过滤器，不是路径加载参数；不要使用不存在的 `--skill`。开始前须在该会话确认四个 `book-*` 原生 task agents 和 `book_translator_prepare`、`book_translator_finish` 两个工具可用；存在文件或 skill 名称并非原生子任务执行证据。

## 默认版式

| 设置 | 默认值与解释 |
|---|---|
| 纸张与单双面 | A5，双面镜像版心 |
| 非装订长边 | 8 mm |
| 装订侧 | 最小边距 20 mm，不叠加装订补偿 |
| 上、下 | 各 15 mm |
| 译本页码 | 正文由显式 `main_body_start` 起从 1 编号；书名、译者序及其他前置页不印页码，正文页码放在页眉外侧，不放页脚 |
| 章、节页眉 | 按 PDF 实际摊开方向：左页内侧为章名，右页内侧为节名；新章清除旧节名，不随正文编号重置而颠倒装订侧 |
| 原书页码 | 依据原书内容提取并核对，置于非装订长边、距纸边 3 mm；不是阅读器绝对页序 |
| 注释 | 被注释处当页下侧，横线分隔；存在时至少一行，每页最多半个正文高度；过长续排至后续页底 |
| 代理译者序 | agents 编写，编译后最多 2 页 |
| 人类核对译者序 | 可选，单独放置，不伪造人类署名 |
| 段落与列表 | 正文段首缩进 2 字宽；有序、无序列表保留原标记和层级，续行悬挂对齐 |
| 原书留白页 | 默认不排入译本，也不生成“原书此处留白”等说明；有实际内容的稀疏页不删除，不为奇偶配页额外插白页 |
| 图片与文字比例 | 优先按核对过的源文字号 `source_em` 保持相对大小；不放大铺满；仅允许有显式可读性下限及审核依据的整图等比缩小 |
| 术语对照表 | 中文表头，仅编号、原文、译文、首次出现页码四列；依据与决策保留在审计数据中，不印入表格 |

“最小边距 20 mm”指装订侧的完整边距，不叠加补偿。译本正文页码与 PDF 物理页序分开：不为配页插白，因此正文第 1 页可以处于物理左页，装订侧、页眉和边距始终按实际左右页处理。原书页码是独立的源文定位边注；无真实印刷页码时不补造，罗马数字、前缀和重复标签保留来源身份。

## 翻译与版面不变量

- 公式及正文引用公式中的变量名不翻译；逐符号核对后可走已有的受保护 LaTeX 公式排版路径，否则保留公式原图。代码块连同注释原样保留。当前没有通用原生表格/自动表格重排渲染器，不能以此承诺处理宽表。
- 人名保留原文；以人名命名的专有名词仅翻译非人名部分。
- 专有名词遵循相关规范；每项记录规范、版本/定位与选择依据。无可核实规范时明确记录领域惯例或不确定性，不伪造引用。
- 首次出现的术语为**加粗斜体并带编号上标**；中文表头的四列附录只列编号、原文、译名、首次出现页码。正文内引用正文相对页码，正文前首现明确标为前置页及 PDF 物理页序，不挪到正文制造“第 1 次”。规范来源、定位和决策依据继续保存在 `terms.json`、交接和凭证中。
- 图片、图片组和行内栅格数学符号保持原图、阅读顺序、组内偏移/间距与基线。显示图以核对过的正常正文 `source_em` 为优先比例，不能拿图内小字、较小图注、DPI 或字框高度作放大依据。优先尺寸为“源图尺寸 ÷ 源正文 em × 译本文字 em”；不因目标栏宽而放大。当前页余量不足时先将完整对象移至下一页；整页/图栏仍放不下时，可提出 `min(1, 可用宽/优先宽, 可用高/优先高)` 的候选等比缩小，预留不缩小的图注、旁文和脚注。只有显式记录缩放选择、经实际尺寸检查的可读性下限和依据，并且编译后最小标注/下标/线条仍清楚，才允许采用。整张画布及所有面板共用一个比例，不改 `source_em` 来强行塞入；无可行比例就阻塞并提出具体取舍。整图/组不得裁剪、跨页拆开或拉伸，不能静默改纸张/边距，也不承诺未实现的横页或折页。字段统一见 format.md。
- 所有正文、图注、表格和注释都需有来源覆盖。**解释性脚注正文必须翻译，包括原来是图片的脚注**：先核对并转录为语义文本，普通原脚注图只作为非输出的 `source_evidence` 保存并绑定哈希。混合脚注中的公式、变量、人名和代码仍保护；代码块自己的程序注释不因此改写。不得用“图片不翻译”让整句英文脚注原样混入译本。
- **污损普通文字默认在证据支持时补全**：在内部不可变的补全元数据及证据中区分已确认读法和有依据的猜测，不把上下文推断说成恢复了原始墨迹。补全文字后紧接唯一注释，印出的内容仅为简短的目标语补全提示、原始片段和所提供原件的污损裁片；不印源页定位、重复的补全文字、已确认/猜测状态、依据或其他说明。这些源页、补全文字、状态及依据仍须保留在封存的审计元数据中供核验。必须在 `note.target` 中写出可见提示并保留原始片段和裁片；渲染器只印作者编写的注释，不自动输出审计元数据。干净的旁证不能替代污损原图；该声明的污损裁片是审计图不输出规则的狭义例外。数字、单位、公式、标识符及表格数据若仍歧义，不能猜成确定值；须保留不确定性并阻塞相关交接，不能用流畅文字掩盖。

结构化稿件保存段落 ID、原书页界、文字/非文字关系和不可翻译片段。机械校验能检查已声明保护区，却不能自动证明所有人名、变量或 OCR 错误都已被发现；审核仍必须对照原书与实际 PDF。

当前源稿采用 **Book version 2**：必须明确正文起点、显示图的源字号校准、列表结构、真实空白页分类和脚注内容类型；有补全时遵循规范的补全注释契约。旧版已封存任务不能靠补默认值、改凭证或重置轮次直接升级；需保留历史，重新核对源稿并取得新的源封存及下游模型/审校凭证。本次规则不自动迁移既有任务，也不自动追加模型调用。

## 阶段与本次模型选择

| 阶段 | 输入与结果 |
|---|---|
| 0：提取 / OCR | 原文件、页图、原生文本、OCR 文本与坐标；人工/代理核对后形成并封存源稿 |
| 1：文体 / 专业 / 术语 | 封存源稿 → 有依据的术语表、文体决策与阶段 2 交接 |
| 2：翻译 / 排版 | 源稿、术语、交接 → 完整译稿、代理译者序、编译 PDF |
| 3：审核 | 逐块来源核对与实际页面检查 → 通过，或完整问题清单退回阶段 2 |

**取消阶段 1、2 的非 OpenAI 限制；四个角色都可以选择实际可用的 OpenAI 或非 OpenAI 模型。每次新工作流开始前必须通过 ask 询问 source、terminology、translation、review 的实际可用选项和用户选择。** 不能把旧预设、当前父模型、task/default 配置或例子当作授权；只有用户明确选“沿用当前配置”时才解析并记录所沿用的精确角色模型。缺项或选定模型不可用时须停下重新询问，不允许擅自回退。多个角色可共用模型，但也必须由本次选择覆盖。完整询问协议集中在 [operation.md](skills/book-translator/references/operation.md)。默认最多 3 个完整的“翻译—审核”轮次；第三轮仍未通过则停止，不能以编译通过或部分译稿交付。增加上限必须显式选择。

四个角色统一走当前 omp 会话的原生路径：`book_translator_prepare` → 按返回 agent 与完整 assignment（含不透明 run 标记）派发**恰好一个原生 task** → 等 task 完成后调用 `book_translator_finish`。不要猜测 task 的 `model` 参数。基于 eval 的 book agent 不准入，是因为此流程必须取得原生 task 的最终结果证据，不是 omp 没有 eval 委派能力。模型路由只改当前父会话中的命名 book 角色，子会话单独禁用模型回退，并核对实际子任务身份；不启动独立 omp/RPC，不修改全局配置。现有原生模型注册、认证、OAuth、自定义和无密钥供应商能力继续保留。精确接口集中在 [format.md](skills/book-translator/references/format.md)，原生机制与限制见 [omp-contract.md](skills/book-translator/references/omp-contract.md)。

这是**父会话局部路由与已观察身份的准入边界，不是恶意代理或网络沙箱**，也不独立证明端点身份。hook 可失效、超时或被禁用；只有完整原生证据通过控制器准入才有凭证，安装或任务成功标记本身不够。本包不静默安装额外 SDK/egress gate，也不承诺阻止任意 shell/network 绕过。

## 本地依赖

Python 3.10+、PyMuPDF、Pillow、jsonschema；已执行的 Python 依赖版本固定于 [requirements.txt](skills/book-translator/requirements.txt)。可在目标项目隔离的 virtualenv 中执行 `python3 -m pip install -r "$skill/requirements.txt"`，无需全局安装。排版需要 XeLaTeX、ctex 等 TeX 包、适用字体，以及提供 `build/column/baselineattach` 的 LaTeX 输出 socket API；本次执行环境为 TeX Live 2026，缺能力会明确编译报错，不静默跳过页底尺寸修正。latexmk 可选，缺失时使用多轮 XeLaTeX。扫描 OCR 还需可用的 Tesseract 引擎与对应语言数据；即使 PyMuPDF 自带引擎，缺语言数据也不能识别。DjVu 需要真实的 ddjvu 解码器。运行 doctor 获取依赖能力；实际编译与字体覆盖仍需运行验证。

PyMuPDF/MuPDF 使用 AGPL 或商业授权；是否符合目标项目的分发/服务使用方式需独立核查。其他依赖也遵循各自许可证。本包不附带上游二进制、OCR 语言数据或第三方书籍，不修改全局配置。

## 操作与工件

令 `skill` 指向复制后的 skill 目录；任务目录不要放在插件内。**先通过 ask 完成本次四个角色的模型选择**，再将下列变量设为用户实际选择的精确供应商/模型，不从旧任务或默认配置自动取值：

```sh
skill=.agents/translator/skills/book-translator
python3 "$skill/scripts/translator.py" doctor
python3 "$skill/scripts/translator.py" init /path/book.pdf /path/book-job --source-language en --target-language zh-CN
python3 "$skill/scripts/translator.py" configure-model /path/book-job source --provider "$SOURCE_PROVIDER" --model "$SOURCE_MODEL"
python3 "$skill/scripts/translator.py" configure-model /path/book-job terminology --provider "$TERMINOLOGY_PROVIDER" --model "$TERMINOLOGY_MODEL"
python3 "$skill/scripts/translator.py" configure-model /path/book-job translation --provider "$TRANSLATION_PROVIDER" --model "$TRANSLATION_MODEL"
python3 "$skill/scripts/translator.py" configure-model /path/book-job review --provider "$REVIEW_PROVIDER" --model "$REVIEW_MODEL"
python3 "$skill/scripts/translator.py" extract /path/book-job --ocr auto --language eng
```

接着在已激活的原生会话按上述 prepare/task/finish 顺序完成 source。协调者检查其工件与准入凭证后另行执行：

```sh
python3 "$skill/scripts/translator.py" validate /path/book-job --source
python3 "$skill/scripts/translator.py" seal-source /path/book-job
```

依次以同一路径完成 terminology、translation。翻译准入先持久保存完整作者证据，再构建并成功完成一次轮次；当前编译 PDF 供独立 review 检查。review 的 finish 准入成功后，协调者提交同一报告，并且只在当前报告通过时验收：

```sh
python3 "$skill/scripts/translator.py" review /path/book-job /path/report.json
python3 "$skill/scripts/translator.py" accept /path/book-job
python3 "$skill/scripts/translator.py" status /path/book-job
```

阶段 0 对照页图重建 version-2 `book-source.json`，核对正文起点、段落/列表/空白页、原书页码、保护区、图文相对尺寸、脚注转录和补全注释。来源缺少可靠字号校准、没有可辩护的辨读或技术值仍有实质歧义时应阻塞；有依据且在内部元数据明确标为猜测的普通文字补全不因此一律拒绝。不能把未经核对的 OCR 晋升为可交付源稿。source 与 review 的原生凭证分别是封存与报告提交的必要前提，但完成角色不自动封存源稿、提交审核或验收，协调者须另行执行。

通过当前 omp 的原生注册与认证使用所选模型，不额外转发凭据，不构造私有注册表，也不将认证限制为 API key。原生已支持的 OAuth、自定义或无密钥模型保持可用；具体身份仍须实际解析和核对，不承诺所有模型免费或持续可用。注册、认证可用、实际请求成功和翻译质量是不同证据；失败时重新取得用户选择，不能静默换模型。

`book.json` 为完整译稿，`terms.json` 为术语依据，`handoff.md` 为交接，`reviews/` 保存每轮报告及内容绑定，`provenance/` 保存原生请求、执行证据、trace 和准入凭证，`build/` 保存 TeX/PDF/十一项机械门槛结果。审核报告必须绑定实际检查的内容与 PDF 身份；提交不能把旧报告改标为当前报告，且必须有匹配的原生 reviewer 凭证。只有当前审核与新鲜度检查通过后才释放 `output.pdf`。恢复时读磁盘记录，不依赖短期 conversation、task ID 或 run token。

封存后的源稿修正先记录反馈/范围，并以 `book_translator_prepare` 的 source 修订模式准备新原生任务（Python 桥接为 `prepare-native JOB source --revise`）。完成后得到匹配新源稿的凭证，**旧 seal、状态与轮次不因此改变**；协调者仍须显式执行 `seal-source JOB --reseal` 才替换 seal、作废下游准入/构建/批准并归档旧审核。未改变源稿的重新封存不能清零轮次。术语若在首次翻译前被独立审查退回，则保留只读反馈并链接进历史，以同一原生路径准备 terminology 修订；仍只接受 `terminology_ready`、第 0 轮且当前凭证/工件绑定完整的任务，不得用来绕过审核、修改封存源稿或重置轮次。完整恢复流程见 operation.md。

可见书名中的术语由准入译者以 `title_terms` 显式标注，先于译者序参与整本书首现格式和定位统计；不靠字符串匹配猜概念。正文前首现保留前置页定位，正文首现使用从正文起算的译本页码。原书页边标记仍保留真实印刷标签；超宽标签只在其外侧页码带内按测量结果适配，不改源标签、基线或 3 mm 锚点，这不构成图片任意缩放的许可。

模型完成后先保存内容作者证据，再进行可能失败的编译。若存在完整有效且内容未变的待构建作者证据，协调者可执行 `python3 "$skill/scripts/translator.py" finalize-translation JOB`，不重新调用模型，也不复用旧构建；成功后才增加一次翻译轮次，随后仍须审核和验收。没有该证据的旧失败稿、手工拼出的稿件或已更改的内容，不能用此命令补造准入。

完整字段与操作协议见 [format.md](skills/book-translator/references/format.md)、[operation.md](skills/book-translator/references/operation.md) 及 `stages/`。除本 README 外，包内文件均为 English agent-facing assets；书籍译文自然使用所请求的目标语言。

## 验证与边界

```sh
python3 -m unittest discover -s translator/skills/book-translator/tests -v
python3 translator/skills/book-translator/scripts/verify_install.py
```

复制后将上述路径替换为实际包路径。`verify_install.py` 用于检查 `.agents/translator` 与 `.omp/translator` 两种完整复制布局在显式启动时的 skill、四个 agents 和两个 hook 工具注册，不发送模型请求；注册不等于子任务或推理证据。实际执行结果、历史验证和未覆盖项记录于 [verification.md](skills/book-translator/references/verification.md)，不能把旧结果解释为已验证本次原生切换。

未实际完成选定模型的原生子任务、完整来源/PDF 审核及控制器准入，就不能声称已完成真实书籍翻译、专业审核或效果评估。复杂扫描、公式识别、图片旁长正文和极窄页码列都可能需要源结构修正；不以裁图、吞注释、伪造原页码、无可读性依据的缩放或静默换模型解决。
