"""프로젝트 .env가 실제로 프로세스 환경에 로드되는지 검증.

.env.example로 .env 사용을 안내하지만 코드에서 load_dotenv()를 호출하지
않으면 설정이 조용히 무시된다 (2026-08-01: SSG_PROXY 설정이 먹지 않는
문제로 발견). config를 읽기 전에 로드되어야 한다.
"""

import os
import subprocess
import sys
import textwrap

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_dotenv_values_reach_environment(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("PERFUME_TEST_TOKEN=from-dotenv\n", encoding="utf-8")

    script = textwrap.dedent(
        f"""
        import os, sys
        sys.path.insert(0, {PROJECT_ROOT!r})
        os.chdir({str(tmp_path)!r})
        import app  # noqa: F401 — import 시점에 .env를 로드해야 한다
        print(os.environ.get("PERFUME_TEST_TOKEN"))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.stdout.strip() == "from-dotenv", result.stderr[-500:]
