# 讲义中文逐页翻译工具

本目录把 DSE 2025 各讲的英文 PDF 讲义做成逐页对照的中文版，做法与
`01_Miller/ccp_chinese/slides_translation/` 中的 CCP 讲义一致：

- 原 PDF 的每一页作为矢量背景保留（公式、图表、版式、主题配色都不动）；
- 只删去需要翻译的英文字形，在原坐标上用 XeLaTeX + ctex（Fandol 字体）排入中文；
- 公式、代码、参考文献条目、表格中的数字列保持原样。

成果文件的作者、创建者等元数据统一为“孙翊铭”。

## 成果位置

每讲的中文 PDF 在对应讲次目录下的 `chinese/` 文件夹中，例如
`04_Iskhakov_egm/chinese/L04_DCEGM_CN.pdf`。全部讲义及其中文标题见 `decks.json`
（`out` 为目录，`name` 为文件名）。

两讲用替换录像对应的课件：

| 讲次 | 替换课件（英文原件） | 中文版 |
| --- | --- | --- |
| Lecture 5（Miller） | `01_Miller/DSE2022AUS_Lecture7/Abridged Unobserved Heterogeneity and Finite Dependence.pdf`（DSE 2022 AUS） | `01_Miller/chinese/L05_DSE2022AUS_Unobserved_Heterogeneity_Finite_Dependence_CN.pdf` |
| Lecture 6（Aguirregabiria） | `06_Aguirregabiria/Lecture_6_Structural_DDC_with_Fixed_Effects/DSE2024_slides/slides_fe_ddc_madison_august2024.pdf`（DSE 2024） | `06_Aguirregabiria/chinese/L06_DSE2024_Structural_DDC_Fixed_Effects_CN.pdf` |

## 工作目录

每份讲义的中间文件在 `<讲次目录>/chinese/src/<deck>/`：

| 文件 | 内容 |
| --- | --- |
| `translation.txt` | 译文（手写，唯一需要编辑的文件） |
| `source.txt` | 抽取出的英文原文，按页列出各区域 |
| `regions.json`、`obstacles.json` | 区域坐标与周围字形（`extract` 生成） |
| `layout.pdf` | 删去英文后的背景页 |
| `<name>.tex`、`build/` | 中文排版源文件与编译目录 |
| `qa/` | 原文与中文对照的抽查图 |

## 用法

```bash
python3 -I tools/cn_slides/cnslides.py extract <deck>   # 抽取英文区域，写 source.txt
python3 -I tools/cn_slides/cnslides.py build <deck>     # 删字、排版、编译
python3 -I tools/cn_slides/cnslides.py verify <deck>    # 检查区域外的像素改动与元数据
```

`build` 发现没有译文的区域时会停下，并把它们列在 `missing.txt` 中。

## 译文文件的写法

每行一个区域：`k1a2b3c | 中文译文`。区域编号由原文字形算出，文本不变编号就不变。

- `=`：保留英文原样（公式、代码、文献条目、合并了多列的表头等）。
- `⏎`：强制换行，用于原文按行对齐的图例、表格行标签。
- `⟪…⟫`：用原文的强调色排版（对应原文中变色的文字）。
- `**…**`：粗体。
- 行内公式照常写 `$…$`；`%` 写成 `\%`。

相同的英文在各讲之间共享译文（翻译记忆），本讲自己的译文优先。
