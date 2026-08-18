# Paper Reading System

面向学术论文的双语精读与图表精读阅读器。

## 当前最新主线版本

当前正式版本为 **V0.8.3**，并作为仓库当前生产主线使用。

其他使用者默认直接使用：

- `main`：当前生产主线，默认推荐；
- `v0.8.3`：V0.8.3 固定版本分支；
- `latest`：当前稳定版本别名。

`main`、`v0.8.3` 与 `latest` 在 V0.8.3 作为当前正式版本期间保持指向同一生产提交。版本号见根目录 `VERSION`，当前标准合同见 `config/latest_reader_standard.json`。

## 当前验收参考

当前 V0.8.3 验收参考为 Haviv et al. 2024：

`Haviv_et_al_2024_COVET_ENVI_V0.8.3_FORMAT_LOCKED.html`

论文：*The covariance environment defines cellular niches for spatial inference*，Nature Biotechnology，DOI `10.1038/s41587-024-02193-4`。

参考 HTML SHA-256：

`b94592fa77f3168d8f41cb3a7c7a0047fd5c49de84db91a3657c8e29d095138a`

验收记录：`releases/V0.8.3/reference/haviv-covet-envi-validation.json`。

该版本已验证固定文本组件、逐句中英对应、原位文献引用、原位图表引用、术语点击解释、完整图表预览、全屏图表精读及动态图表精读术语交互。Haviv 验收页包含 16 张主图/Extended Data 图的图表精读入口，共 117 个子图或逻辑单元解释。

该验收页用于锁定阅读器行为、结构与排版标准，不降低后续论文的全文来源完整性要求。

## V0.8.3 锁定要求

V0.8.3 继承 V0.8.2 `FINAL_VALIDATED2` 的内容与交互合同，并新增/固定以下约束：

- 正文、右侧图表查看器以及全屏“图表精读”中的 `.term-pop` 术语均必须能够通过鼠标点击或键盘 Enter/Space 打开解释弹窗；
- 术语事件使用捕获阶段委托处理，不能被逐句高亮、批注、图表卡片等旧事件的 `stopPropagation` / `stopImmediatePropagation` 截断；
- 动态生成的图表精读术语无需重新绑定事件；
- Hero 论文信息、一页概览、方法概括与概览结论必须使用固定组件 DOM 与冻结样式，不允许论文级生成器自行发明新的排版类；
- 双语精读默认开启，逐句一一对应与逐句高亮；
- 文内引用必须位于原句原位并可点击，禁止统一移至段尾；
- 图表引用必须位于原句原位并可点击打开对应图表，禁止统一移至段尾；
- 术语必须高亮且可交互；
- 图表必须有完整预览，大图必须逐子图或逐逻辑单元精读；
- 参考文献弹窗、批注工具、阅读设置和既有固定阅读器交互不得删减；
- 不得重新恢复“快速了解”作为可见独立模式；
- 正文明确引用补充图表而主 PDF 未内嵌时，生成器必须主动取得最终发表版 Supplementary Information，不能以“用户未上传”为理由省略。

正式版合同见 `config/v083_release.json`；最新标准见 `config/latest_reader_standard.json`；术语修补器见 `tools/patch_v083_term_interaction.py`；静态门禁见 `tools/validate_v083_term_interaction.py` 与 `tools/validate_v083_component_format.py`。

## 版本规则

- 每次更新发布新的独立版本，不覆盖历史版本。
- 发布文件以版本号为前缀，其余名称使用下划线连接。
- 论文英文原文、中文逐句翻译、完整图注、图表映射、原位引用、术语层和既有核心功能属于锁定内容。
- UI、交互与性能可以迭代，但不得借此删减、重排或改写锁定内容。
- 新版本只有在功能和内容合同不弱于当前最新正式版时，才能替代该标准。
