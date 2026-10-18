# LaTeX 书籍翻译工作流

独立的 oh-my-pi Agent Plugin。输入 **PDF / EPUB / MOBI / DjVu，含扫描版和混合文本/扫描页**；输出 LaTeX 编译的 PDF。适用于可授权处理、能够逐页核对来源的完整书籍，不提供 DRM 绕过，也不将 OCR 或编译成功等同于译文可靠。

## 复制和显式激活

将整个 `translator/` 复制到目标项目的 `.agents/translator/` 或 `.omp/translator/`。已有同名目录时先审阅，不覆盖修改。进入目标项目后，每次需要此工作流都显式启动：

```sh
omp --plugin-dir .agents/translator
# 或：
omp --plugin-dir .omp/translator
```

在 TUI 中提交 `/skill:book-translator` 及实际翻译任务。**复制本身不会自动启用任意子目录**；无需全局 settings、额外 extension、仓库根指导文件或 `ref_repo/`。`--skills` 是已发现名称的过滤器，不是路径加载参数；不要使用不存在的 `--skill`。本包的阶段文档是 skill 的操作协议，不冒称跨 harness 通用的 task-agent 定义。

## 默认版式

| 设置 | 默认值与解释 |
|---|---|
| 纸张与单双面 | A5，双面镜像版心 |
| 非装订长边 | 8 mm |
| 装订侧 | 最小边距 20 mm，不叠加装订补偿 |
| 上、下 | 各 15 mm |
| 原书页码 | 依据原书内容提取并核对，置于非装订长边、距纸边 3 mm；不是阅读器绝对页序 |
| 注释 | 被注释处当页下侧，横线分隔；存在时至少一行，每页最多半个正文高度；过长续排至后续页底 |
| 代理译者序 | agents 编写，编译后最多 2 页 |
| 人类核对译者序 | 可选，单独放置，不伪造人类署名 |

“最小边距 20 mm”在本包中指装订侧的完整边距，不会覆盖明确要求的外侧 8 mm 和上下 15 mm。版式值保存在任务的 `layout` 中，不设置额外的装订补偿。原书无印刷页码时不补造页码；罗马数字、前缀和重复页码保留来源身份。

## 翻译与版面不变量

- 公式及正文引用公式中的变量名不翻译；代码块连同注释原样保留。
- 人名保留原文；以人名命名的专有名词仅翻译非人名部分。
- 专有名词遵循相关规范；每项记录规范、版本/定位与选择依据。无可核实规范时明确记录领域惯例或不确定性，不伪造引用。
- 首次出现的术语为**加粗斜体并带编号上标**；附录术语表列出原文、译名、依据及首次出现的**译本页码**，不以原书页码代替。
- 嵌入图片不翻译。段落、页界、图片及图片组保留阅读顺序、左右关系与组内几何位置；整幅图片/图片组不可跨两页截断。可以移至下一页或独占一页，允许正文较少与留白。
- 所有正文、图注、表格和注释都需有来源覆盖。难以可靠重建的公式/表格可以保留为原图，但不能猜测重写。

结构化稿件保存段落 ID、原书页界、文字/非文字关系和不可翻译片段。机械校验能检查已声明保护区，却不能自动证明所有人名、变量或 OCR 错误都已被发现；审核仍必须对照原书与实际 PDF。

## 阶段与模型限制

| 阶段 | 输入与结果 |
|---|---|
| 0：提取 / OCR | 原文件、页图、原生文本、OCR 文本与坐标；人工/代理核对后形成并封存源稿 |
| 1：文体 / 专业 / 术语 | 封存源稿 → 有依据的术语表、文体决策与阶段 2 交接 |
| 2：翻译 / 排版 | 源稿、术语、交接 → 完整译稿、代理译者序、编译 PDF |
| 3：审核 | 逐块来源核对与实际页面检查 → 通过，或完整问题清单退回阶段 2 |

**阶段 1、2 不允许 OpenAI/GPT。** 默认最多 3 个完整的“翻译—审核”轮次；第三轮仍未通过则停止，不能以编译通过或部分译稿交付。增加上限必须显式选择。

本包采用独立会话启动器而不是依赖 task-agent 的 `model:`：omp 的认证/重试可能回退至父模型。启动器仅支持明确的直连 `anthropic/claude-*`、`google/gemini-*` 身份；拒绝 OpenAI/GPT、未知供应商、别名、auto 和聚合路由。隔离 HOME、agent 配置和工作目录，只传选定供应商凭据；发送正文前核对实际解析的 provider/model。模型示例并非供应商持续提供服务的保证。

这是**启动配置和身份核验边界，不是网络沙箱**。它不能防御恶意 shell 绕过、被篡改的 omp 或虚报身份的端点；真正逐请求强制限制需要另行部署可信 egress/SDK gate，本包不静默安装、不冒称已有。源码依据与本机执行版本分开记录于 [omp-contract.md](skills/book-translator/references/omp-contract.md)。

## 本地依赖

Python 3.10+、PyMuPDF、Pillow、jsonschema；已执行的 Python 依赖版本固定于 [requirements.txt](skills/book-translator/requirements.txt)。可在目标项目隔离的 virtualenv 中执行 `python3 -m pip install -r "$skill/requirements.txt"`，无需全局安装。排版需要 XeLaTeX、ctex 等 TeX 包和适用字体；latexmk 可选，缺失时使用多轮 XeLaTeX。扫描 OCR 还需可用的 Tesseract 引擎与对应语言数据；即使 PyMuPDF 自带引擎，缺语言数据也不能识别。DjVu 需要真实的 `ddjvu` 解码器。运行 `doctor` 获取当前能力，不用不存在的工具继续假装成功。

PyMuPDF/MuPDF 使用 AGPL 或商业授权；是否符合目标项目的分发/服务使用方式需独立核查。其他依赖也遵循各自许可证。本包不附带上游二进制、OCR 语言数据或第三方书籍，不修改全局配置。

## 操作与工件

令 `skill` 指向复制后的 skill 目录；任务目录不要放在插件内：

```sh
skill=.agents/translator/skills/book-translator
python3 "$skill/scripts/translator.py" doctor
python3 "$skill/scripts/translator.py" init /path/book.pdf /path/book-job --source-language en --target-language zh-CN
python3 "$skill/scripts/translator.py" extract /path/book-job --ocr auto --language eng
```

随后由阶段 0 对照页图重建 `book-source.json`，核对段落/页码/保护区/图片组，再 `seal-source`。工作流不会把未经审核的 OCR 自动晋升为可交付源稿。

```sh
python3 "$skill/scripts/translator.py" seal-source /path/book-job
python3 "$skill/scripts/translator.py" configure-model /path/book-job terminology --provider anthropic --model claude-sonnet-4-5
python3 "$skill/scripts/translator.py" configure-model /path/book-job translation --provider anthropic --model claude-sonnet-4-5
python3 "$skill/scripts/translator.py" stage /path/book-job terminology --check
# 供应商凭据由对应环境变量提供；--check 不发送模型请求。
python3 "$skill/scripts/translator.py" stage /path/book-job terminology
python3 "$skill/scripts/translator.py" stage /path/book-job translation
python3 "$skill/scripts/translator.py" build /path/book-job
# 独立审核记录所检查的 content_digest 与 pdf_sha256 后生成 report.json：
python3 "$skill/scripts/translator.py" review /path/book-job /path/report.json
python3 "$skill/scripts/translator.py" accept /path/book-job
```

`book.json` 为完整译稿，`terms.json` 为术语依据，`handoff.md` 为交接，`reviews/` 保存每轮审核及内容绑定记录，`provenance/` 保存阶段启动证据，`build/` 保存 TeX/PDF/机械检查结果。审核报告必须自带被审核稿件及 PDF 的 SHA256 身份，提交时不能把旧报告重新标记为当前报告。只有通过当前审核与新鲜度检查后才释放 `output.pdf`。更改源稿需显式重新封存，并作废下游批准；旧审核归档而不丢失，未改变源稿的重新封存不能清零轮次。恢复任务时读取磁盘记录，不依赖短期 conversation 或 task ID。

完整字段与操作协议见 [format.md](skills/book-translator/references/format.md)、[operation.md](skills/book-translator/references/operation.md) 及 `stages/`。除本 README 外，包内文件均为 English agent-facing assets；书籍译文自然使用所请求的目标语言。

## 验证与边界

```sh
python3 -m unittest discover -s translator/skills/book-translator/tests -v
python3 translator/skills/book-translator/scripts/verify_install.py
```

复制后将上述路径替换为实际包路径。注册检查在隔离 `.agents/translator` 与 `.omp/translator` 两种布局执行正反对照，不发送模型请求。实际编译、输入格式、OCR、状态转换及视觉检查的执行结果与未覆盖项记录于 [verification.md](skills/book-translator/references/verification.md)。

无模型凭据时只能验证身份解析、拒绝路径和离线机械流程，不能声称已完成真实书籍的非 OpenAI 翻译、专业审核或翻译效果评估。复杂扫描、公式识别、图片旁长正文和极窄页码列都可能需要源结构修正；不以裁图、吞注释、伪造原页码或静默降级解决。
