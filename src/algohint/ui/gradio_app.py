"""Gradio アプリの公開入口。

既存の import 経路を維持しつつ、文脈統合型ワークスペースへ委譲する。
"""

from algohint.ui.gradio_workspace import build_app

__all__ = ["build_app"]
