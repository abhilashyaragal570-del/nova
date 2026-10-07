from tools.file_tools import WriteFileTool


def test_overwrite_parameter_tells_model_to_leave_it_off():
    desc = WriteFileTool.parameters["properties"]["overwrite"]["description"].lower()
    assert "only" in desc and "explicitly" in desc


def test_tool_description_tells_model_to_ask_before_overwriting():
    desc = WriteFileTool.description.lower()
    assert "explicitly" in desc and "ask" in desc