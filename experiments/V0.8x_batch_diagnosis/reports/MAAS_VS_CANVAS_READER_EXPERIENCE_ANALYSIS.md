# V0.8.2 原版 CANVAS 与当前 Maas 阅读器的读者体验对照

## 结论

当前 Maas HTML 应当直接废弃，不能继续修改几段文字后作为候选版。它已经复用了 CANVAS 的页面壳层，但没有完成论文阅读内容的生产。读者看到的是 PDF 解析结果被机械填入页面：英文标题占据中文标题位置，作者为占位符，一页概览由首页文本、页数、文本块数量和 Ethics statement 拼成，正文中文全部复制英文，章节目录由 PDF 文本框和出版附录标题组成，16 张图全部只显示 `Fig.` 或 `Extended Data Fig.`，图注没有翻译，参考文献区还混入正文段落。

因此，当前问题不是“Maas 与 CANVAS 还差一些润色”，而是两者处于不同内容完成度。原版 CANVAS 是面向读者整理完成的论文产品；当前 Maas 只是装入相同外壳的解析中间件。外壳一致不能被算作阅读器完成。

## 一、读者打开页面后的第一屏

| 项目 | 0.82 原版 CANVAS | 当前 Maas | 对读者的实际影响 |
|---|---|---|---|
| 中文标题 | 完整学术翻译：基于组织病理的细胞结构与邻域信息虚拟空间肿瘤分析 | 英文标题原样复制 | 读者无法快速建立中文语义 |
| 作者 | 24 名作者完整列出 | `Authors listed in the source PDF` | 页面像未完成模板 |
| 单位 | 7 组单位及作者关系 | 0 | 无法判断研究团队和机构 |
| 出版信息 | Publisher、完整时间线、卷页、期刊定位、领域定位 | Publisher 为空，时间线只有 2026 | 无法判断论文出处和发表状态 |
| 页面信息 | 只展示读者需要的信息 | 暴露 SHA256 和 extraction diagnostics | 构建日志污染读者界面 |

Maas 源 PDF 已提供 Received 30 October 2024、Accepted 10 December 2025、Published online 9 February 2026，以及 Nature Genetics 58, 341–354 (2026)。作者与单位集中在主文末页和在线方法部分。当前代码没有提取这些内容，却把文件哈希和解析方式展示给读者，说明字段优先级完全颠倒。

正确的 Maas 第一屏应让读者立即知道：这是一篇研究脑膜瘤分子分型、肿瘤微环境和分类器可解释性的 Nature Genetics 论文；它不是单纯提出新分类，而是在解释现有 DNA 甲基化分类器为何形成这些类别，并将多组学发现转化为 PU.1/CD68 风险指标。

## 二、一页概览

原版 CANVAS 的六个问题分别承担研究动机、数据、输入输出、生物学发现、临床结果和限制的功能。每个答案是重新组织过的中文结论，方法流程是一条有顺序的研究链。

当前 Maas 的六个位置虽然存在，但内容全部失效：

| 概览位置 | 当前 Maas 实际内容 | 应当生成的内容 |
|---|---|---|
| 研究解决什么问题 | DOI、标题、收稿日期、首页引言连续拼接 | 分类器信号究竟来自肿瘤细胞还是微环境；NF2 突变型脑膜瘤是离散亚型还是风险连续谱 |
| 核心数据 | 32 pages、199 blocks、16 assets、82 references | 26 例 snRNA-seq、120 例 IHC/部分 MIBI、37 例空间 RNA-seq、4,502 例甲基化发现集、7,495 例跨肿瘤参考集和 1,378 例 PU.1 TMA |
| 输入与输出 | Ethics statement 和细胞核提取实验步骤 | 输入为甲基化、snRNA、空间 RNA、CNV、IHC 和结局；输出为肿瘤/基质信号分解、连续风险结构和可临床量化的免疫指标 |
| 生物学发现 | 重复首页文本 | 低风险病例富含微胶质样细胞；高风险病例 TAM 总量下降但更偏浸润、增殖和免疫抑制状态；分类器同时读取肿瘤与微环境信号 |
| 临床结果 | 再次重复首页文本 | 低免疫细胞比例与复发相关；PU.1 加入 WHO 分级后 C-index 由 0.63 提升至 0.66；WHO 2 级中间/低免疫组 HR 2.91 |
| 限制 | 固定免责声明 | 缺少证明连续谱机制的功能实验；观察性多组学不能证明因果；WHO 3 级高免疫病例过少；PU.1 阈值仍需前瞻性跨中心验证 |

从读者角度看，一页概览是最严重的失败，因为它位于正文之前，却没有提供任何论文理解。它不只是“不够好”，而是在误导读者认为页数和解析块数量是研究数据。

## 三、目录与正文论证顺序

原版 CANVAS 的结果目录使用描述性标题，读者仅看目录就能理解论证链：先建立空间图谱，再识别邻域和生态单元，随后训练 CANVAS，最后进入大队列预后和免疫治疗验证。

Maas 来源 PDF 已经自带清晰的结果结构：

1. Cellular composition of the tumor microenvironment  
2. Stromal signal contribution to meningioma ML classification  
3. Stromal and neoplastic epigenetic signatures  
4. Meningioma subclones  
5. Clinical impact of TME composition  

当前 HTML 没有保留这些小节，只剩 `Results`，随后出现多个 `References`、`Online content`、`Additional information` 和 `Front matter`。更严重的是，Figure 3–6 被图表索引归到 `References` 下，读者会看到图与正文论证完全脱节。

代码不应依靠字号或文本框长度猜章节。Nature PDF 已提供书签和明确标题，生成流程应优先读取 PDF TOC，再以版面识别补充。结果小节、Discussion 和 Methods 必须分别建树；Online content、作者行、日期、页眉和参考文献标题不得进入科学目录。

## 四、双语正文

| 指标 | 0.82 原版 CANVAS | 当前 Maas |
|---|---:|---:|
| 双语单元 | 111 | 199 |
| 中文缺失或与英文相同 | 5 | 199 |
| 少于 50 字符的碎块 | 6 | 48 |
| 疑似句中截断或不完整块 | 25 | 94 |
| 页眉/出版信息泄漏 | 0 | 2 |

Maas 的199个所谓“双语单元”全部没有中文翻译。数量比 CANVAS 多并不代表更完整，而是图中轴标签、图例文本、页眉、标题碎片和真正段落都被统一包装成正文卡片。读者连续阅读时会不断遇到只有几个词的块、半句话、图中标签和大段 Methods 文本，正文节奏完全被破坏。

正确做法不是按字符数再切一次，而是恢复来源段落。对于双栏跨页文章，需要判断上一栏末尾和下一栏开头是否属于同一自然段；图注和坐标轴文本必须进入图资产，不进入正文；Methods 可以保留完整小节，但不能挤占结果叙事。

## 五、图表入口和图像质量

原版 CANVAS 的图表索引把每张图放在其论证小节下，并显示完整英文标题和中文主题。当前 Maas 只有三个索引分组：Results、References、Additional information。16个按钮全部显示 `Fig.` 或 `Extended Data Fig.`，读者无法知道任何一张图的内容。

Maas 来源 PDF 中实际包含6张主图和10张扩展图，主图标题均可直接从 PDF 提取：

- Figure 1. Meningioma molecular classification models and snRNA cohort overview
- Figure 2. Tumor-associated macrophages are the largest subset of non-neoplastic cells that differ in number and phenotype by meningioma grade and MC
- Figure 3. NF2-mutant meningiomas contain a mixture of neoplastic and stromal epigenetic signatures
- Figure 4. NF2-mutant meningioma is a spectrum rather than distinct tumor subtypes
- Figure 5. The number of immune cells in a meningioma can predict the risk for recurrence
- Figure 6. TAM cell quantification by immunohistochemical PU.1 staining can facilitate risk prediction in meningioma

当前代码丢失这些标题，不是因为 PDF 没有，而是 caption 正则只截取了 `Fig.`。

图像也存在明显可读性差距。原版 CANVAS 图像中位宽度约为2395像素，主图宽度为3102像素；当前 Maas 所有图像只有896–906像素宽。Nature Genetics 的主图包含大量小字号热图标签、分组名称、样本量、统计值和生存曲线，900像素图在2K屏右侧查看和放大时无法承担精读任务。图像生成应使用完整图区域，并至少达到原版 CANVAS 的约3000像素主图宽度，而不是把页面裁剪后压缩到900像素。

## 六、图注与图表精读

当前 Maas 的中文图题全部是英文复制，16张图的中文图注都没有中文内容。图表精读也没有进行论文层级解释：caption 被重复用作整图说明、子图说明和结论。

真正的图表精读需要根据每张图的论证作用生成。例如 Figure 2 不是简单罗列 a–j，而应按以下顺序帮助读者理解：

首先用 a–c 建立细胞类型和甲基化类别间的差异；随后用 d–g 通过 snRNA、CD68 IHC、MIBI和标志基因区分低风险微胶质样细胞与高风险浸润性巨噬细胞；最后用 h–j 的空间图模型和细胞反卷积说明局部微环境可以预测甲基化类别。读者需要知道各面板的对象、横纵轴、组间方向、统计证据以及它们如何共同支持“TAM 状态随风险连续变化”这一结论。

Figure 4 应说明文章为何从“分类器受微环境影响”推进到“NF2 突变型是连续谱”：a比较脑膜瘤与髓母细胞瘤、室管膜瘤的分群边界，后续面板连接分类分数、CNV、复发转换、空间亚克隆和 CD68 状态。Figure 6 则应把 PU.1 TMA 的样本筛选、自动定量、分层生存、WHO 2级 HR、C-index变化和临床适用边界串起来。

只要逐子图解释没有生成，页面就不应显示“图表精读”按钮为可完成状态。

## 七、表格和补充材料

Maas 的32页 PDF没有内嵌正式 Table 或 Extended Data Table，因此“0个表卡”本身不是主要错误。该文正文引用了 Supplementary Table，补充表位于独立补充材料中。正确处理方式是建立 source bundle，下载补充文件后生成表卡或下载入口；不能凭空要求主 PDF 产生表格，也不能完全忽略正文中的补充表引用。

这与 CANVAS 不同。CANVAS 原版已经纳入 Table S1–S5，因此其5个表卡来自额外补充数据，不是主论文 PDF 自动解析得到。代码必须把“论文主 PDF”和“补充材料”作为一组来源管理。

## 八、参考文献

Maas 来源 PDF共有86条参考文献，当前 HTML显示82条。实际问题比“少4条”更严重：至少10个 reference-item 是正文段落，例如当前第1条以“Conversely, probes separating MC mal...”开头，第2条是 WHO 分级正文，第5条是 CNV 结果，第7条混入通讯邮箱和首页文本。这些条目随后被重新编号为1–82，掩盖了原始缺口。

参考文献解析必须保留源编号，检测1–86是否连续，并验证条目是否具有作者、题名、期刊和年份等文献特征。正文段落不能因为开头存在数字或引用上标就进入参考文献。任何缺号都应在构建报告中明确列出，不能通过重新编号伪装完整。

## 九、代码应当如何改变

当前流程把 PDF parser 直接当成 reader writer，这是根本错误。后续流程必须拆成四个明确阶段：

**证据提取阶段**只负责来源英文段落、页码、PDF TOC、图像区域、完整图注、原始参考文献编号和补充材料链接，不生成任何面向读者的结论。

**论文理解阶段**根据全文和图表建立研究问题、队列关系、分析输入输出、主要发现、临床结果、局限、结果论证树以及每张图在全文中的作用。这里必须按论文逐篇生成，不能使用“首句、末句、页数、Methods前1200字”等固定填充规则。

**语言与阅读辅助阶段**完成逐段中文翻译、术语统一、图注翻译、逐子图解释和图级结论。任何英文复制中文、通用免责声明或 caption 复用都应失败。

**固定渲染阶段**只把通过内容门禁的数据装入 CANVAS 组件。固定壳层只保证按钮和布局不退化，不能替代前三个阶段。

## 最终判断

新版固定壳层解决了旧批量版“按钮和布局被砍掉”的问题，但尚未解决“文章内容由谁真正完成”的问题。当前 Maas 与0.82原版 CANVAS的差距主要不在CSS，而在整篇论文的理解、重组、翻译和图表教学。现有 Maas 不应继续修补，应从证据 manifest 重新生成读者内容；完成标题与元数据、一页概览、真实章节、逐段翻译、16张图的完整标题与精读、补充材料入口和86条参考文献之后，再进入固定壳层渲染。
