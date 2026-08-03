"""解析适配器层。

隔离外部解析组件（Rust sidecar ck3-reader / 未来自研 Python PDX 文本解析器），
使上层 UI/后端不直接依赖其内部结构。协议见 SaveParserAdapter。
"""
