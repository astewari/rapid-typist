def test_import_package():
    import rapid_typist
    assert hasattr(rapid_typist, "__version__")

def test_import_cli():
    from rapid_typist import cli
    assert hasattr(cli, "main")

