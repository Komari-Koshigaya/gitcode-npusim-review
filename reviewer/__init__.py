"""npu-simulator PR 自动检视工具。

纯标准库实现：通过 `gitcode` CLI 访问 GitCode API，使用确定性规则与可选 LLM
对每个 open PR 生成检视意见，并输出 HTML 日报供 GitHub Pages 展示。
"""

__version__ = "0.1.0"
