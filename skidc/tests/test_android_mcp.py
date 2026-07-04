from __future__ import annotations

from skidc.android_mcp.adb import parse_uiautomator_xml


def test_parse_uiautomator_xml_extracts_useful_nodes() -> None:
    xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
    <hierarchy rotation="0">
      <node text="" resource-id="" class="android.widget.FrameLayout" package="p" clickable="false" enabled="true" bounds="[0,0][100,100]">
        <node text="登录" resource-id="com.demo:id/login" class="android.widget.Button" package="p" clickable="true" enabled="true" bounds="[10,20][80,60]" />
        <node text="" content-desc="更多" resource-id="" class="android.widget.ImageButton" package="p" clickable="true" enabled="true" bounds="[80,20][100,60]" />
      </node>
    </hierarchy>
    """

    nodes = parse_uiautomator_xml(xml)

    assert nodes == [
        {
            "text": "登录",
            "resource_id": "com.demo:id/login",
            "content_desc": "",
            "class": "android.widget.Button",
            "package": "p",
            "clickable": True,
            "enabled": True,
            "bounds": "[10,20][80,60]",
        },
        {
            "text": "",
            "resource_id": "",
            "content_desc": "更多",
            "class": "android.widget.ImageButton",
            "package": "p",
            "clickable": True,
            "enabled": True,
            "bounds": "[80,20][100,60]",
        },
    ]


def test_parse_uiautomator_xml_returns_empty_on_invalid_xml() -> None:
    assert parse_uiautomator_xml("<bad") == []

