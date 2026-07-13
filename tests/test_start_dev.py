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


def test_backend_start_process_uses_quoted_command_for_space_safe_paths():
    start_dev = read_repo_file("start_dev.ps1")

    assert "$BackendScript = Join-Path $ProjectRoot \"start_web.ps1\"" in start_dev
    assert "Set-Location -LiteralPath $(Quote-ForPowerShell $ProjectRoot)" in start_dev
    assert "& $(Quote-ForPowerShell $BackendScript)" in start_dev
    assert '"-Command", $BackendCommand' in start_dev
    assert 'Start-Process powershell -ArgumentList $BackendArgs -WorkingDirectory $ProjectRoot' in start_dev


def test_readme_documents_default_and_custom_vite_proxy_target():
    readme = read_repo_file("README.md")

    assert "默认代理到 `http://127.0.0.1:8000`" in readme
    assert "`BackendHost` / `BackendPort`" in readme
    assert "VITE_BACKEND_PROXY_TARGET" in readme


def test_start_dev_checks_native_command_exit_codes():
    start_dev = read_repo_file("start_dev.ps1")

    assert "function Assert-LastExitCode" in start_dev
    assert "Assert-LastExitCode \"npm --version\"" in start_dev
    assert "Assert-LastExitCode \"pip install\"" in start_dev
    assert "Assert-LastExitCode \"npm install\"" in start_dev
    assert "Assert-LastExitCode \"backend startup checks\"" in start_dev
