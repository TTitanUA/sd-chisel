import pytest

from app.storage import images


def test_session_image_dir_creates(tmp_path):
    d = images.session_image_dir("abc", data_root=tmp_path)
    assert d.exists() and d.is_dir()
    assert d.name == "abc"


def test_remove_session_images_is_idempotent(tmp_path):
    d = images.session_image_dir("xyz", data_root=tmp_path)
    (d / "source.png").write_bytes(b"\x89PNG")
    images.remove_session_images("xyz", data_root=tmp_path)
    assert not d.exists()
    # Idempotent: calling twice doesn't raise.
    images.remove_session_images("xyz", data_root=tmp_path)


def test_remove_session_images_rejects_path_traversal(tmp_path):
    with pytest.raises(ValueError):
        images.remove_session_images("../evil", data_root=tmp_path)
