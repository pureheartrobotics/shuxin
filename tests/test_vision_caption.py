from shuxin.voice.vision_caption import attach_scene, decode_jpeg_base64, is_look_intent


def test_look_intent_phrases() -> None:
    assert is_look_intent("看看这是什么")
    assert is_look_intent("前面有什么")
    assert is_look_intent("看一下")
    assert is_look_intent("你能看见吗")
    assert is_look_intent("摄像头接上了吗")
    assert not is_look_intent("今天天气怎么样")
    assert not is_look_intent("往前走一点")


def test_attach_scene() -> None:
    assert "杯子" in attach_scene("这是什么", "桌上有一只杯子")


def test_decode_jpeg_rejects_garbage() -> None:
    assert decode_jpeg_base64("not-jpeg") is None
    assert decode_jpeg_base64("") is None
