# V0.8.1 CANVAS candidate

本分支基于已正式发布的 V0.8 构建。V0.8.1 修复右侧图解和图表精读图注无法展开的问题，分离正文前图表预览卡片中的“右侧”和“精读”动作，统一按钮排版，并将图 4–5 的子图精读从分点式文本改为与图 1–3 一致的连续陈述，同时保留原有数据、实验逻辑、生物学解释和证据边界。

## 构建

```bash
python releases/V0.8.1/build.py
python releases/V0.8.1/validators/validate.py \
  published/V0.8.1_CANVAS_Cellular_architecture_and_neighborhood-informed_virtual_spatial_tumor_profiling.html \
  --sha256 6b5e13ae62361b2b10ac2d3abdbb51eda0188a102195b0384b037463cb3ab013
```

构建过程从正式 V0.8 HTML 应用带有基线哈希和目标哈希的确定性补丁。任一锚点、基线文件或目标结果不一致时均会终止。

## 内容边界

英文正文、中文翻译、完整中英文图注、参考文献、图卡、表卡和资源顺序保持锁定。可变范围仅包括用户明确要求修改的图 4–5 图表精读文本，以及对应的 UI 和交互路由。

完整修改说明见 `CHANGELOG.md`，精读生成约束见 `FIGURE_STUDY_GENERATION_CONTRACT.md`，工程设计见 `AI_ENGINEERING_NOTES.md`。
