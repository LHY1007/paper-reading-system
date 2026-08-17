# Paper Reading System

面向学术论文的双语精读与图表精读阅读器。

## 当前最新标准

当前 V0.8.2 的读者级参考标准固定为：

`Andani 等 - 2025 - Histopathology-based protein multiplex generation using deep learning_V0.8.2_FINAL_VALIDATED2.html`

参考文件 SHA-256：

`e66cc0fd7b2b7add744afd3db5f0d02106f3871bc954932f46053850e6ed5569`

该版本不是只作为 Andani 单篇结果保存，而是作为后续所有 V0.8.2 论文阅读器的最低功能与内容标准。详细锁定合同见 `config/v082_latest_reader_standard.json`，内容生成规范见 `config/v082_reader_content_blueprint.json`。

后续生成不得退化以下功能：双语精读默认开启、逐句一一对应与逐句高亮、文内引用原位可点开、图表引用原位可点开、术语高亮、完整图表预览、复杂大图逐子图精读、参考文献弹窗及既有固定阅读器交互。不得重新恢复“快速了解”作为可见独立模式。

## 版本规则

- 每次更新发布新的独立版本，不覆盖历史版本。
- 发布文件以版本号为前缀，其余名称使用下划线连接。
- 论文英文原文、中文逐句翻译、完整图注、图表映射、原位引用、术语层和既有核心功能属于锁定内容。
- UI、交互与性能可以迭代，但不得借此删减、重排或改写锁定内容。
- 新版本只有在功能和内容合同不弱于当前最新标准时，才能替代该标准。
