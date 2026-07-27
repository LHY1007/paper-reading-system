# 本地候选 HTML

完整候选文件由 `build.py` 从仓库内已发布的 V0.7.8 HTML 和 `source/` 中的 V0.8 交互层确定性生成。

目标文件名：

`V0.8_CANVAS_Cellular_architecture_and_neighborhood-informed_virtual_spatial_tumor_profiling.html`

SHA256：

`c02aad24689eefaed372decb3068f339a83d5c15fdf8b45f259c019418ceece2`

构建命令：

```bash
python releases/V0.8-candidate/build.py
python releases/V0.8-candidate/validators/validate.py \
  published/V0.7.8_CANVAS_Cellular_architecture_and_neighborhood-informed_virtual_spatial_tumor_profiling.html \
  published/V0.8_CANVAS_Cellular_architecture_and_neighborhood-informed_virtual_spatial_tumor_profiling.html
```

本候选分支不修改主分支的已发布 HTML。
