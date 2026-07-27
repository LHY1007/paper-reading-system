# V0.8.2 CANVAS candidate

V0.8.2 基于锁定的 V0.8.1 候选产物构建，重点修复三类问题：图表精读术语覆盖不足、正文打开右侧图栏时精读入口缺失，以及正文引用数字在 PDF 读取阶段被错误当作普通文本。

## 构建

```bash
python releases/V0.8.2/build.py
python releases/V0.8.2/validators/validate.py \
  published/V0.8.2_CANVAS_Cellular_architecture_and_neighborhood-informed_virtual_spatial_tumor_profiling.html \
  --sha256 84c37e235f40e782c79de6625ddd9369cba64095f28bff75ae702fb5893f6ff1
```

构建器拼接 `source/patch_chunks/` 中的 7 个补丁分块，并通过 `tools/apply_line_patch.py` 对锁定基线执行带 SHA256 校验的确定性修改。任何基线偏移、操作锚点缺失或目标哈希不一致都会阻断构建。

## 核心约束

- 术语匹配采用规范化本体、最长别名优先和严格拉丁字符边界。
- 所有具有精读数据的图在正文右侧栏中均显示精读入口；普通表格不显示。
- 引用在 PDF span 解析阶段区分为 `text` 与 `citation`，HTML 不再通过普通数字正则猜测。
- 英文正文、中文翻译、图卡、表卡、中英文完整图注和图表精读数据继续保持内容锁。
