"""``update`` サブコマンドの実体。``uv tool upgrade`` で自分自身を更新する。

このツールは ``uv tool install git+...`` で配布しているため、更新は
``uv tool upgrade aitool-iroiro`` に委ねる。uv はインストール時に記録した
requirement（git URL）を読み直して既定ブランチの最新コミットを取得するので、
ここでリポジトリ URL を持つ必要はない。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from importlib import metadata

from aitool.errors import AitoolError

DISTRIBUTION_NAME = "aitool-iroiro"
"""``uv tool upgrade`` に渡すパッケージ名。``pyproject.toml`` の ``project.name`` と一致させる。"""


class UpdateError(AitoolError):
    """自己更新を実行できる環境ではない、または ``uv`` の実行に失敗した場合に送出する。"""


def installed_commit() -> str | None:
    """インストール済みパッケージの git コミット ID を返す。

    ``uv tool install git+...`` でインストールされていれば、パッケージの
    ``direct_url.json``（PEP 610）に取得元コミットが記録されている。
    ``uv run`` などの開発環境（editable）や、git 以外からの導入では ``None``。

    Returns:
        コミット ID。git 由来でなければ ``None``。
    """
    try:
        raw = metadata.distribution(DISTRIBUTION_NAME).read_text("direct_url.json")
    except metadata.PackageNotFoundError:
        return None
    if not raw:
        return None
    try:
        info = json.loads(raw)
    except json.JSONDecodeError:
        return None
    vcs_info = info.get("vcs_info")
    if not isinstance(vcs_info, dict):
        return None
    commit = vcs_info.get("commit_id")
    return commit if isinstance(commit, str) else None


def run_upgrade() -> int:
    """``uv tool upgrade`` を実行し、その終了コードを返す。

    uv の出力はそのままユーザーの端末へ流す。

    Returns:
        ``uv`` プロセスの終了コード。

    Raises:
        UpdateError: git 由来のインストールでない、または ``uv`` が見つからない場合。
    """
    if installed_commit() is None:
        raise UpdateError(
            "This aitool was not installed with 'uv tool install git+...', so it cannot update itself. "
            "Reinstall with: uv tool install git+https://github.com/Nu424/aitool-iroiro.git"
        )

    uv_path = shutil.which("uv")
    if uv_path is None:
        raise UpdateError(
            "'uv' was not found on PATH. Install uv (https://docs.astral.sh/uv/) and run: "
            f"uv tool upgrade {DISTRIBUTION_NAME}"
        )

    completed = subprocess.run([uv_path, "tool", "upgrade", DISTRIBUTION_NAME], check=False)
    return completed.returncode
