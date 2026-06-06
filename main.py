"""ローカル開発用のエントリポイント。

``uv run python main.py`` または ``python main.py`` で CLI を起動できる。
"""

from aitool.cli import app

if __name__ == "__main__":
    app()
