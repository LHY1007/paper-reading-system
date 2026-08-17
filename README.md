# Paper Reading System

面向学术论文的双语精读与图表精读阅读器。

## 当前最新正式版

当前正式版本为 **V0.8.3**。

V0.8.3 继承 V0.8.2 `FINAL_VALIDATED2` 的全部内容与交互合同，并修复术语交互缺陷：正文、右侧图表查看器以及全屏“图表精读”中的 `.term-pop` 术语均必须能够通过鼠标点击或键盘 Enter/Space 打开解释弹窗。

V0.8.3 的术语事件采用**捕获阶段的委托处理**，不再依赖普通冒泡，因此不会被逐句高亮、批注、图表卡片等旧事件处理器的 `stopPropagation` / `stopImmediatePropagation` 截断。动态生成的图表精读术语也无需重新绑定事件。

正式版合同见 `config/v083_release.json`；确定性修补器见 `tools/patch_v083_term_interaction.py`；静态门禁见 `tools/validate_v083_term_interaction.py`。

V0.8.2 读者级参考标准仍保留为：

`Andani 等 - 2025 - Histopathology-based protein multiplex generation using deep learning_V0.8.2_FINAL_VALIDATED2.html`

参考文件 SHA-256：

`e66cc0fd7b2b7add744afd3db5f0d02106f3871bc954932f46053850e6ed5569`

V0.8.3 本地正式参考文件 SHA-256：

`c65aa3996657300180ba6c983c6145496f8efe221d1b1aeb58eb6e59037b0915`

后续生成不得退化以下功能：双语精读默认开启、逐句一一对应与逐句高亮、文内引用原位可点开、图表引用原位可点开、术语高亮及术语解释、完整图表预览、复杂大图逐子图精读、参考文献弹窗及既有固定阅读器交互。不得重新恢复“快速了解”作为可见独立模式。

## 版本规则

- 每次更新发布新的独立版本，不覆盖历史版本。
- 发布文件以版本号为前缀，其余名称使用下划线连接。
- 论文英文原文、中文逐句翻译、完整图注、图表映射、原位引用、术语层和既有核心功能属于锁定内容。
- UI、交互与性能可以迭代，但不得借此删减、重排或改写锁定内容。
- 新版本只有在功能和内容合同不弱于当前最新正式版时，才能替代该标准。
