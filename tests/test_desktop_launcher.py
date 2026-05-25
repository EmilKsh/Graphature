from graphature_desktop import HOST, _streamlit_command


def test_streamlit_desktop_command_uses_local_headless_server():
    command = _streamlit_command(9876)

    assert command[:3][-2:] == ["-m", "streamlit"]
    assert f"--server.address={HOST}" in command
    assert "--server.port=9876" in command
    assert "--server.headless=true" in command
    assert "--browser.gatherUsageStats=false" in command
