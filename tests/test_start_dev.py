from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_repo_file(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_frontend_proxy_target_is_supplied_by_start_dev_backend_args():
    start_dev = read_repo_file("start_dev.ps1")
    vite_config = read_repo_file("frontend/vite.config.ts")

    assert "VITE_BACKEND_PROXY_TARGET" in vite_config
    assert 'process.env.VITE_BACKEND_PROXY_TARGET ?? "http://127.0.0.1:8000"' in vite_config
    assert '"http://${BackendHost}:${BackendPort}"' in start_dev
    assert "$env:VITE_BACKEND_PROXY_TARGET" in start_dev


def test_start_dev_checks_native_command_exit_codes():
    start_dev = read_repo_file("start_dev.ps1")

    assert "function Assert-LastExitCode" in start_dev
    assert "Assert-LastExitCode \"npm --version\"" in start_dev
    assert "Assert-LastExitCode \"pip install\"" in start_dev
    assert "Assert-LastExitCode \"npm install\"" in start_dev
    assert "Assert-LastExitCode \"backend startup checks\"" in start_dev
