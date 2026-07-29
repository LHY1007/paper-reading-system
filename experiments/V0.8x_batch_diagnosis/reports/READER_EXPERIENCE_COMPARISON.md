# V0.8.2 读者体验实测对照

本报告直接读取三个 HTML 中读者可见的内容以及图表精读运行时数据。0.82 原版 CANVAS 是目标范本；新版 CANVAS 用于判断同一论文重新生成后丢失了什么；Maas 用于判断跨论文迁移是否真正完成。

## 总体判定

| 文件 | 标题信息 | 一页概览 | 目录 | 双语正文 | 图表 | 表格 | 参考文献 | 总分 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 00_ORIGINAL_V082_CANVAS.html | 5 | 5 | 5 | 4.8 | 4.4 | 5 | 5 | 34.2/35 |
| new_canvas.html | 0 | 0 | 2 | 0 | 3.7 | 0 | 5.0 | 10.7/35 |
| maas.html | 0 | 0 | 3 | 0 | 2.9 | 0 | 3.7 | 9.6/35 |

这里的分数只表达能否作为论文阅读器，不表达 DOM 或按钮是否存在。新版 CANVAS 和 Maas 即使沿用了同一外壳，也会因为读者内容错误而判定为失败。

## 00_ORIGINAL_V082_CANVAS.html

标题区：中文标题有效；作者 24 人；单位 7 条；读者元数据完整；没有暴露机器审计字段。

一页概览：6 个回答均为针对论文的中文综合，没有英文原文、解析诊断、Methods 原段或固定免责声明。

目录：共 64 个章节，没有明显的首页残片、句子或非章节标题。

正文：111 个双语单元；英文与中文相同 4 个，占 3.6%；无中文 5 个；短碎片 8 个；页眉泄漏 0 个。

图表：19 个图卡；通用图名 0；简介缺失 0；图注没有正文污染。主图均具有完整标题、读者简介和图表精读。补充材料中有少量未完成项，因此原版本身也不是无条件满分。

表格：5 个结构化表卡。参考文献：112 条。

首个图卡实测：

- 标题：Graphical abstract
- 中文标题：图形摘要
- 简介：用一张图串联 CODEX 细胞邻域发现、H&E 生境预测和人群尺度临床建模。
- 图表精读子块：3 个
- 英文图注长度：179；中文图注长度：72

## new_canvas.html

标题区：中文标题直接复制英文；作者被错误提取为 slides；单位为空；Publisher、Journal scope 和领域定位缺失；Source PDF SHA256 与 Extraction 被错误显示给读者。

一页概览：6 个回答全部失败。研究问题仅为标题残片；核心数据写成 29 页、154 个文本块、6 个资产和 111 条参考文献；输入输出由 Methods 小节列表拼接；生物学结果与临床结果重复标题残片；局限为固定免责声明。

目录：共 25 个章节，首页标题残片、Highlights 子句和 KEY RESOURCES TABLE 被当成正文章节。

正文：154 个双语单元；英文与中文相同 145 个，占 94.2%；154 个单元均无真正中文；短碎片 27 个；页眉泄漏 4 个。段落数量多于原版并不代表内容更完整，而是 PDF 文本框被过度拆分。

图表：6 个图卡；所有中文图注均未翻译；图形摘要的标题、中文标题和简介都只是 Graphical abstract；图表精读没有子块。主图标题被压缩为 Figure 1. 这一类无科学信息的名称。

表格：0 个结构化表卡。参考文献：111 条。

概览错误示例：

- 研究问题：virtual spatial tumor profiling from histopathology
- 核心数据：The source PDF contains 29 pages, 154 extracted natural text blocks, 6 figure or table assets and 111 references.
- 输入输出：由 Sample preparation、CODEX staining、H&E staining 等 Methods 小节标题连续拼接

错误章节示例：

- CANVAS enables virtual spatial profiling at the population
- CANVAS identifies H&E-based spatial signature of
- KEY RESOURCES TABLE

首个图卡实测：

- 标题：Graphical abstract
- 中文标题：Graphical abstract
- 简介：Graphical abstract
- 图表精读子块：0 个
- 英文图注长度：18；中文图注长度：18

## maas.html

标题区：中文标题直接复制英文；作者为 Authors listed in the source PDF；单位为空；Publisher、Journal scope 和领域定位缺失；Source PDF SHA256 与 Extraction 被显示给读者。

一页概览：6 个回答全部失败。研究问题吸收 DOI、日期、Check for updates 和正文开头；核心数据写成 32 页、199 个文本块、16 个资产和 82 条参考文献；输入输出直接复制 Ethics statement 与 nuclei isolation；生物学结果和临床结果复制首页文字；局限仍是固定免责声明。

目录：共 20 个章节，Front matter 和 Online content 被当成科学章节；多个真正结果小节没有形成清楚的论证链。

正文：199 个双语单元；英文与中文相同 199 个，占 100%；全部没有中文翻译；短碎片 57 个。首页、日期、坐标轴、图内标签、图注和正文边界发生混合。

图表：16 个图卡；16 个标题全部退化为 Fig. 或 Extended Data Fig.；16 个中文图注全部复制英文；没有结构化表格。首图图注长达 3,532 字符，其中吸收了图后正文、图内标签和下一段内容。首图虽然生成了 13 个所谓子块，但它们来自 snRNA、n=26、WHO grade 等图内短标签，并非逐子图解释。

表格：0 个结构化表卡。参考文献：82 条，原文应为 86 条。

概览错误示例：

- 研究问题：从 DOI 开始，连续包含文章标题、Received、Accepted、Published online 和 Check for updates
- 核心数据：The source PDF contains 32 pages, 199 extracted natural text blocks, 16 figure or table assets and 82 references.
- 输入输出：Ethics statement 与 Nuclei isolation from fresh frozen tissue 原文

错误章节示例：Front matter；Online content。

首个图卡实测：

- 标题：Fig.
- 中文标题：Fig.
- 简介：整段英文图注截断
- 图表精读子块：13 个机器切出的图内标签
- 英文图注长度：3,532；中文图注长度：3,532

## 直接结论

0.82 原版 CANVAS 的优势不是组件数量，而是每个位置都承担明确阅读任务：标题区完成论文识别，一页概览完成全文压缩，目录呈现论证链，正文保持自然段和上下文翻译，图卡先告诉读者图的作用，再提供完整图注和逐子图解释。

新版 CANVAS 已经证明当前生成器无法复现自己的范本：同一篇论文重新生成后，作者变成 slides，中文标题复制英文，发表信息被年份和 SHA 取代，概览由 PDF 统计和方法目录拼接，章节被首页标题和 Highlights 污染，图卡退化为 Figure 1.，图表精读为空。

Maas 的问题更严重：除了上述全部退化，还把 Ethics statement 和 nuclei isolation 放入输入输出，把正文与坐标轴文字吸入图注，把 16 张图全部命名为 Fig. 或 Extended Data Fig.，并且没有任何结构化表格。它不是 CANVAS 的跨论文迁移，而是将 PDF 文本框塞进 CANVAS 外观。

因此下一版代码不能继续由解析器自动填满最终 manifest。解析器只生成证据包；每个模块必须有独立生成任务和证据范围；内容门禁必须在 HTML 渲染之前执行。