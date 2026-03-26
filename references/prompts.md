# Prompt 模板索引

> **重要**：每个 Prompt 已拆分为独立文件，**只在对应步骤时读取需要的那个文件**。
> 禁止一次性读取所有 Prompt 文件（会浪费 ~16K tokens 的上下文空间）。

| Prompt | 文件 | 对应步骤 | 大小估计 |
|--------|------|---------|---------|
| #1 需求调研 | `references/prompts/prompt_1_survey.md` | Step 1 | ~1.5K tokens |
| #2 大纲架构师 | `references/prompts/prompt_2_outline.md` | Step 3 | ~1.2K tokens |
| #3 内容分配与策划稿 | `references/prompts/prompt_3_planning.md` | Step 4 | ~1.8K tokens |
| #4 HTML 设计稿生成 | `references/prompts/prompt_4_design.md` | Step 5d | ~10K tokens |
| #5 演讲备注 | `references/prompts/prompt_5_notes.md` | 可选 | ~0.3K tokens |

## 使用流程

```
Step 1 -> 读取 prompt_1_survey.md（需求调研）
Step 2 -> 搜索（不需要 Prompt）
Step 3 -> 读取 prompt_2_outline.md（大纲架构师）
Step 4 -> 读取 prompt_3_planning.md（内容分配与策划稿）
Step 5a -> 读取 style-system.md（风格选择）
Step 5b -> 如有 generate_image，为需要的页面生成配图
Step 5c -> 读取 icon-guide.md + 运行 icon_resolver.py（图标匹配）
Step 5d -> 读取 prompt_4_design.md（HTML 设计稿），逐页生成
         必须同时遵守 pipeline-compat.md 中的 CSS 禁止清单
Step 6 -> 后处理脚本（html_packager → html2svg → svg2pptx）
可选  -> 读取 prompt_5_notes.md（演讲备注）
```
